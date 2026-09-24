"""Sentry error tracking and tracing.

`sentry-sdk[fastapi]` has been in requirements.txt for a while but was never
initialised, so nothing has ever been reported. This wires it up.

No-ops without SENTRY_DSN, so local and CI runs report nothing and nothing
breaks — the DSN is the on switch.

What you get per request: endpoint, method, status code, duration, and the full
stack trace on any 5xx. Note Sentry does NOT record response bodies, and request
bodies only when send_default_pii is on — which it is not here, because these
payloads carry phone numbers and auth tokens. For call-specific visibility the
calling module attaches its own context (call_id, call_type, status) via
`set_call_context` below, which is what makes one call's lifecycle traceable.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_enabled = False


def init_sentry() -> bool:
    """Initialise Sentry once at startup. Returns whether it is active."""
    global _enabled
    if _enabled:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("SENTRY_DSN not set — error tracking disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except Exception as exc:
        log.warning("sentry-sdk unavailable, continuing without it: %s", exc)
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", "development"),
            release=os.getenv("RELEASE", None),
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            # Traces are what let you see latency per endpoint. Sampled because
            # every trace is billable; 20% is plenty to spot a slow endpoint.
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2")),
            # OFF deliberately: these requests carry phone numbers, JWTs and
            # Stream tokens. Turning it on would ship all of that to Sentry.
            send_default_pii=False,
            # Scheduler jobs raise in worker threads; without this their failures
            # would never be reported.
            attach_stacktrace=True,
        )
    except Exception as exc:
        log.warning("Sentry init failed, continuing without it: %s", exc)
        return False

    _enabled = True
    log.info("Sentry initialised (env=%s)", os.getenv("ENVIRONMENT", "development"))
    return True


def set_user_context(user_id, profile_id=None) -> None:
    """Attach the caller's identity to the current Sentry scope.

    Without this an error tells you something broke but not for whom, so
    "is this one account or everybody" needs a database dig every time. Sentry
    also uses it for the users-affected count on an issue.

    IDs only — no phone number, no name. send_default_pii stays off.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.get_current_scope().set_user(
            {"id": str(user_id), "profile_id": profile_id}
        )
    except Exception as exc:
        log.debug("sentry user context failed: %s", exc)


def set_call_context(
    call_id,
    call_type: str | None = None,
    status: str | None = None,
    **extra,
) -> None:
    """Tag the current Sentry scope with a call's identity.

    Makes a single call's whole lifecycle searchable — `call_id:<uuid>` in Sentry
    pulls up every event across initiate, accept, end and the sweeps. Silent and
    free when Sentry is off.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        scope = sentry_sdk.get_current_scope()
        scope.set_tag("call_id", str(call_id))
        if call_type:
            scope.set_tag("call_type", call_type)
        if status:
            scope.set_tag("call_status", status)
        for k, v in extra.items():
            scope.set_extra(k, v)
    except Exception as exc:
        log.debug("sentry call context failed: %s", exc)


def capture(message: str, level: str = "warning", **extra) -> None:
    """Report something noteworthy that is not an exception — a budget breach, a
    provider termination that failed. These are the events you want to see
    without waiting for a user to complain."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_message(message, level=level)
    except Exception as exc:
        log.debug("sentry capture failed: %s", exc)
