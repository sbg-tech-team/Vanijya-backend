"""Deploy to Render, verify the live app, roll back if it is broken.

    RENDER_API_KEY=... RENDER_SERVICE_ID=srv-... python _migration/render_deploy.py

Render reporting a deploy "live" only means the process started and answered the
health check once. It does not mean the app works. So after every deploy this
smoke-tests the real service, and if the smoke test fails it rolls back to the
deploy that was live before — users get the previous working version instead of
a broken one.

Exit 0 = deployed and healthy. Exit 1 = failed (rolled back if it could).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
KEY = os.environ["RENDER_API_KEY"]
SERVICE = os.environ["RENDER_SERVICE_ID"]

DEPLOY_TIMEOUT = 20 * 60      # Render cold builds are slow
SMOKE_TIMEOUT = 5 * 60        # free tier spins down; first hit can take ~1 min
TERMINAL_BAD = {"build_failed", "update_failed", "canceled", "pre_deploy_failed", "deactivated"}


def api(path: str, method: str = "GET", body: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "{}")


def log(msg: str) -> None:
    print(msg, flush=True)


def service_url() -> str:
    return api(f"/services/{SERVICE}")["serviceDetails"]["url"].rstrip("/")


def live_deploy_id() -> str | None:
    """The deploy currently serving traffic — our rollback target."""
    for row in api(f"/services/{SERVICE}/deploys?limit=20"):
        d = row["deploy"]
        if d["status"] == "live":
            return d["id"]
    return None


def wait_for(deploy_id: str) -> bool:
    deadline = time.time() + DEPLOY_TIMEOUT
    last = None
    while time.time() < deadline:
        status = api(f"/services/{SERVICE}/deploys/{deploy_id}")["status"]
        if status != last:
            log(f"  deploy status: {status}")
            last = status
        if status == "live":
            return True
        if status in TERMINAL_BAD:
            return False
        time.sleep(10)
    log("::error::timed out waiting for the deploy")
    return False


def smoke(base: str) -> bool:
    """Prove the app actually works, not just that the process booted."""
    checks: list[tuple[str, str, int, callable]] = [
        ("root responds", "/", 200, lambda b: b"running" in b),
        ("openapi serves the full app", "/openapi.json", 200,
         lambda b: len(json.loads(b)["paths"]) > 100),
        # An unauthenticated write must be refused. Catches a deploy that came up
        # with auth misconfigured, which a health check would happily call live.
        ("auth is enforced", "/posts/recommendation/jobs/expiry", 401, lambda b: True),
    ]
    deadline = time.time() + SMOKE_TIMEOUT
    for name, path, want, check in checks:
        while True:
            try:
                req = urllib.request.Request(
                    base + path, method="POST" if want == 401 else "GET")
                with urllib.request.urlopen(req, timeout=90) as r:
                    code, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                code, body = e.code, e.read()
            except Exception as exc:
                if time.time() > deadline:
                    log(f"::error::{name}: never responded ({exc})")
                    return False
                time.sleep(10)          # cold start
                continue
            if code == want and check(body):
                log(f"  ok  {name}")
                break
            if time.time() > deadline:
                log(f"::error::{name}: got HTTP {code}, wanted {want}")
                return False
            time.sleep(10)
    return True


def main() -> int:
    previous = live_deploy_id()
    log(f"currently live: {previous or '(none)'}")

    new = api(f"/services/{SERVICE}/deploys", "POST", {"clearCache": "do_not_clear"})["id"]
    log(f"started deploy: {new}")

    if not wait_for(new):
        log("::error::Render build/deploy failed - previous version is still serving")
        return 1

    log(f"smoke testing {service_url()}")
    if smoke(service_url()):
        log("deployed and healthy")
        return 0

    log("::error::smoke test failed on the new deploy")
    if not previous:
        log("::error::no previous deploy to roll back to - service left as is")
        return 1

    log(f"rolling back to {previous}")
    try:
        api(f"/services/{SERVICE}/rollback", "POST", {"deployId": previous})
    except Exception as exc:
        log(f"::error::rollback request failed: {exc}")
        return 1
    log("rollback requested - users are back on the previous version")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
