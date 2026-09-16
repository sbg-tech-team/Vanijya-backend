"""Stream Video adapter — implements IVideoProvider.

Two kinds of credential are used here:

  * User token  — JWT with `user_id`, handed to the client so it can join.
                  Scoped to a single call via `call_cids`.
  * Server token— JWT with `{"server": true}`, never leaves the backend. Used
                  for the REST calls that provision and terminate sessions.

We deliberately do not pull in the Stream server SDK. PyJWT (already a
dependency) signs both tokens and httpx (already a dependency) makes the two
REST calls we need, so the integration adds no new packages and no import-time
failure mode.

Docs:
  token generation  https://getstream.io/video/docs/api/#token-generation
  server auth       https://getstream.io/docs/platform/authentication/
  call endpoints    https://getstream.io/video/docs/api/calls/
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import jwt

from app.core.config import settings
from app.modules.calling.domain.entities import StreamCredentials
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import STREAM_TOKEN_TTL_SECONDS

log = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_API_BASE = "https://video.stream-io-api.com/api/v2/video"
_HTTP_TIMEOUT_S = 10.0

# Stream's built-in call type for two-way calling. "audio_room" is for
# broadcast-style rooms and is not what we want here.
_STREAM_CALL_TYPE = "default"

# How long after the last participant leaves before Stream ends the session.
# Stream's own default is 30s; we keep it tight so an abandoned call stops
# billing quickly. Valid range is 5s–15min.
_INACTIVITY_TIMEOUT_S = 30


class StreamVideoProvider(IVideoProvider):

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        # Read through getattr so a missing Settings field degrades to "not
        # configured" (-> 503) instead of AttributeError deep in a request.
        self._api_key = api_key or getattr(settings, "STREAM_API_KEY", None)
        self._api_secret = api_secret or getattr(settings, "STREAM_API_SECRET", None)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_secret)

    def new_call_id(self, call_id: UUID) -> tuple[str, str]:
        """Stream call ids must be URL-safe; our UUID with dashes stripped is."""
        return _STREAM_CALL_TYPE, call_id.hex

    # ── User token ────────────────────────────────────────────────────────────

    def issue_token(
        self,
        user_id: UUID,
        stream_call_type: str,
        stream_call_id: str,
    ) -> StreamCredentials:
        if not self.is_configured:
            # Caller turns this into a 503 — never let a missing key surface raw.
            raise RuntimeError("Stream credentials are not configured")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)

        payload = {
            "user_id": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            # Scope to one call: a leaked token cannot join anything else.
            "call_cids": [f"{stream_call_type}:{stream_call_id}"],
        }
        token = jwt.encode(payload, self._api_secret, algorithm=_ALGORITHM)

        return StreamCredentials(
            api_key=self._api_key,
            token=token,
            user_id=user_id,
            call_type=stream_call_type,
            call_id=stream_call_id,
            expires_at=expires_at,
        )

    # ── Server-side operations ────────────────────────────────────────────────

    def provision_call(
        self,
        stream_call_type: str,
        stream_call_id: str,
        created_by_id: UUID,
        max_duration_seconds: int,
    ) -> bool:
        """Create the call up front carrying a hard duration cap.

        This is the guardrail of last resort: `max_duration_seconds` is enforced
        by Stream, so even a total backend outage cannot leave a call billing
        forever. When it fires, Stream removes every participant and ends the
        session.
        """
        body = {
            "data": {
                "created_by_id": str(created_by_id),
                "settings_override": {
                    "limits": {
                        "max_duration_seconds": max_duration_seconds,
                    },
                    "session": {
                        "inactivity_timeout_seconds": _INACTIVITY_TIMEOUT_S,
                    },
                },
            }
        }
        ok = self._post(f"/call/{stream_call_type}/{stream_call_id}", body)
        if not ok:
            # Degraded, not fatal: the client can still create the call by
            # joining, but without Stream's own cap our timers are the only
            # thing bounding spend. Loud on purpose.
            log.error(
                "Stream call provisioning FAILED for %s:%s — call will run "
                "without a provider-side duration cap",
                stream_call_type, stream_call_id,
            )
        return ok

    def end_call_remote(self, stream_call_type: str, stream_call_id: str) -> bool:
        """Terminate the session for everyone, server-side.

        Marking a call ended in our database does not stop Stream billing — the
        session lives until the last participant disconnects. Every terminal
        path calls this.
        """
        ok = self._post(f"/call/{stream_call_type}/{stream_call_id}/mark_ended", {})
        if not ok:
            # Stream's inactivity timeout is the backstop, but it only fires
            # once clients actually disconnect — which is exactly what fails in
            # the forgotten-call case. Worth alerting on.
            log.error(
                "Stream mark_ended FAILED for %s:%s — session may still be "
                "billing; inactivity timeout is the only remaining backstop",
                stream_call_type, stream_call_id,
            )
            # The one failure that keeps costing money silently — worth an alert
            # rather than a log line nobody reads.
            from app.core.monitoring import capture
            capture("Stream mark_ended failed — session may still be billing",
                    level="error", call=f"{stream_call_type}:{stream_call_id}")
        return ok

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _server_token(self) -> str:
        """JWT with `{"server": true}` — full server-side scope. Never sent to a
        client."""
        return jwt.encode({"server": True}, self._api_secret, algorithm=_ALGORITHM)

    def _post(self, path: str, body: dict) -> bool:
        if not self.is_configured:
            log.warning("Stream not configured; skipping POST %s", path)
            return False
        try:
            resp = httpx.post(
                f"{_API_BASE}{path}",
                params={"api_key": self._api_key},
                headers={
                    "Authorization": self._server_token(),
                    "stream-auth-type": "jwt",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=_HTTP_TIMEOUT_S,
            )
        except Exception as exc:
            log.warning("Stream POST %s failed: %s", path, exc)
            return False

        if resp.status_code >= 400:
            # 404 on mark_ended means the session was already gone — that is the
            # outcome we wanted, so don't treat it as a failure.
            if resp.status_code == 404 and path.endswith("/mark_ended"):
                return True
            log.warning("Stream POST %s -> %s: %s", path, resp.status_code, resp.text[:300])
            return False
        return True
