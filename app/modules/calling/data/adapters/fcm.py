"""Firebase Cloud Messaging adapter — implements IPushSender.

This is the first code in the codebase that SENDS a push. `firebase_admin` was
already a dependency but only ever used to verify OTP ID tokens in onboarding,
so the app is reused here rather than initialised a second time.

Everything is data-only (no `notification` block) so the client renders its own
full-screen incoming-call UI. iOS additionally needs apns-push-type=voip for
CallKit to be reachable when the app is killed.

Contract: never raises. A push failure must not break a call — the Socket.IO
event is the fast path and the client can still poll GET /calls/{id}.
"""
from __future__ import annotations

import logging

from app.modules.calling.domain.entities import PushTarget
from app.modules.calling.domain.interfaces.push_sender import IPushSender

log = logging.getLogger(__name__)


class FcmPushSender(IPushSender):

    def send_data(self, targets: list[PushTarget], data: dict[str, str]) -> int:
        tokens = [t.fcm_token for t in targets if t.fcm_token]
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
                        apns=messaging.APNSConfig(
                            headers={
                                "apns-priority": "10",
                                "apns-push-type": "voip",
                            }
                        ),
                    ),
                    app=app,
                )
                delivered += 1
            except Exception as exc:
                # One dead token must not stop the rest of the fan-out.
                log.warning("FCM send failed for one token: %s", exc)

        return delivered
