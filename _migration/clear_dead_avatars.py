"""Null out avatar_url values whose storage object no longer exists.

29 profiles point at objects that were deleted from the Supabase bucket. The
client gets an HTTP 400 (Supabase answers 400 with a NoSuchKey body, not a
404), which renders as a broken image rather than the placeholder it would
show for a profile with no avatar at all. A missing avatar is a better answer
than a dead link.

Every distinct URL is checked once — 84 profiles share only 8 URLs — so this
costs 8 requests, not 84.

    PYTHONPATH=. python _migration/clear_dead_avatars.py           # dry run
    PYTHONPATH=. python _migration/clear_dead_avatars.py --apply
"""
from __future__ import annotations

import argparse
import sys

import requests
from sqlalchemy import text

from app.core.database.session import SessionLocal

_TIMEOUT_S = 15


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT avatar_url, count(*) FROM profile "
            "WHERE avatar_url IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )).all()

        dead: list[str] = []
        affected = 0
        print(f"{'apply' if args.apply else 'DRY RUN'} — {len(rows)} distinct URL(s)\n")
        for url, n in rows:
            try:
                # HEAD is enough and avoids pulling the image body.
                code = requests.head(url, timeout=_TIMEOUT_S, allow_redirects=True).status_code
            except requests.RequestException as exc:
                # Unreachable is not the same as absent: leave it alone rather
                # than wiping avatars over a network blip.
                print(f"  SKIP  {str(exc)[:40]:<40} {url[-42:]}")
                continue
            ok = code < 400
            print(f"  {'ok  ' if ok else 'DEAD'}  {code}  x{n:<4} {url[-42:]}")
            if not ok:
                dead.append(url)
                affected += n

        if not dead:
            print("\nnothing to clear")
            return 0
        print(f"\n{len(dead)} dead URL(s) across {affected} profile(s)")

        if not args.apply:
            print("nothing written. re-run with --apply")
            return 0

        updated = db.execute(
            text("UPDATE profile SET avatar_url = NULL WHERE avatar_url = ANY(:urls)"),
            {"urls": dead},
        ).rowcount
        db.commit()
        print(f"cleared {updated} profile(s)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
