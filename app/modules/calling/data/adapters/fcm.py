"""Firebase Cloud Messaging adapter — implements IPushSender.

This is the first code in the codebase that SENDS a push. `firebase_admin` was
already a dependency but only ever used to verify OTP ID tokens in onboarding,
so the app is reused here rather than initialised a second time.

Everything is data-only (no `notification` block) so the client renders its own
full-screen incoming-call UI.

iOS limitation, deliberate: a data-only push is an APNs *background* push, which
iOS throttles and will not use to wake a killed app. Ringing a killed iPhone
needs a PushKit VoIP push, and a VoIP push cannot go through FCM — the token is
a raw APNs device token and the `.voip` topic is a different one from the app's.
So VoIP targets are skipped here and wait for a direct-APNs sender. On iOS this
adapter reaches foreground and backgrounded apps only; Android is unaffected.

Contract: never raises. A push failure must not break a call — the Socket.IO
event is the fast path and the client can still poll GET /calls/{id}.
"""
from __future__ import annotations

import logging
from typing import Callable

from app.modules.calling.domain.entities import PushTarget
from app.modules.calling.domain.interfaces.push_sender import IPushSender

log = logging.getLogger(__name__)

# firebase_admin.messaging exception classes that mean "this token is dead".
_DEAD_TOKEN_ERRORS = {"UnregisteredError", "SenderIdMismatchError"}


class FcmPushSender(IPushSender):

    def send_data(
        self,
        targets: list[PushTarget],
        data: dict[str, str],
        on_dead: Callable[[str], None] | None = None,
    ) -> int:
        # A PushKit token is not an FCM token; sending it here is a guaranteed
        # InvalidArgument from FCM and would look like a dead device.
        tokens = [t.fcm_token for t in targets
                  if t.fcm_token and t.token_type != "voip"]
        skipped = sum(1 for t in targets if t.token_type == "voip")
        if skipped:
            log.info("skipped %d VoIP target(s): direct APNs not configured", skipped)
        if not tokens:
            return 0

        try:
            from firebase_admin import messaging
            # Reuse the app onboarding already initialised for OTP verification.
            from app.modules.onboarding.data.adapters.firebase import _get_firebase_app

            app = _get_firebase_app()
        except Exception as exc:
            log.warning("FCM unavailable, skipping push: %s", exc)
            return 0

        # FCM requires every data value to be a string.
        payload = {k: ("" if v is None else str(v)) for k, v in data.items()}

        delivered = 0
        for token in tokens:
            try:
                messaging.send(
                    messaging.Message(
                        token=token,
                        data=payload,
                        android=messaging.AndroidConfig(priority="high"),
                        # APNs rejects apns-push-type=voip unless the topic is
                        # <bundle-id>.voip, which FCM does not use, and rejects
                        # priority 10 on a background push. These are the only
                        # headers valid for a data-only message via FCM.
                        apns=messaging.APNSConfig(
                            headers={
                                "apns-priority": "5",
                                "apns-push-type": "background",
                            },
                            payload=messaging.APNSPayload(
                                aps=messaging.Aps(content_available=True)
                            ),
                        ),
                    ),
                    app=app,
                )
                delivered += 1
            except Exception as exc:
                # One dead token must not stop the rest of the fan-out.
                # UnregisteredError/SenderIdMismatch mean the token will never
                # work again — anything else (network, quota) is transient and
                # the token must be kept.
                if on_dead is not None and type(exc).__name__ in _DEAD_TOKEN_ERRORS:
                    on_dead(token)
                log.warning("FCM send failed for one token: %s", exc)

        return delivered
