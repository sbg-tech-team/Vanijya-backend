"""Push-token registration.

Every device a user signs in on must be registered here, or it never rings.
One row per token (not per user) is what makes a phone + tablet both ring and
what lets a reinstall be forgotten independently of the user's other devices.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.modules.calling.application.schemas import DeviceRegisteredOut
from app.modules.calling.domain.interfaces.repository import ICallingRepository


def register_device(
    repo: ICallingRepository,
    *,
    user_id: UUID,
    fcm_token: str,
    platform: str | None,
    token_type: str = "fcm",
) -> DeviceRegisteredOut:
    repo.register_device(
        user_id, fcm_token, platform, datetime.now(timezone.utc), token_type=token_type,
    )
    repo.commit()
    # `deliverable` is False for a VoIP token: it is stored and ready, but
    # nothing can push to it until the direct-APNs sender exists. Saying so
    # here stops a client concluding its registration worked when it cannot
    # yet ring.
    return DeviceRegisteredOut(registered=True, deliverable=token_type != "voip")
