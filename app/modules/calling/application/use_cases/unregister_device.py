"""Push-token removal, on sign-out.

Logging out cleared tokens on the device but left the row in user_devices, so
the phone kept ringing for the account that had signed out of it. Registering
the same token under a new account already moves it, so the gap is only the
case where nobody signs in afterwards — which is exactly the handed-over or
sold phone.

Deleting the token on the client was the other option and is worse: the FCM
token is shared by every feature, so throwing it away to solve a calling
problem deregisters the device for everything.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.calling.application.schemas import DeviceRegisteredOut
from app.modules.calling.domain.interfaces.repository import ICallingRepository


def unregister_device(
    repo: ICallingRepository, *, user_id: UUID, fcm_token: str
) -> DeviceRegisteredOut:
    """Scoped to the caller's own rows on purpose.

    An unscoped delete-by-token would let any authenticated user silence
    anyone else's phone by presenting a token they had harvested, so the
    user_id is part of the WHERE clause, not just the audit trail.
    """
    repo.delete_device_for_user(user_id, fcm_token)
    repo.commit()
    return DeviceRegisteredOut(registered=False, deliverable=False)
