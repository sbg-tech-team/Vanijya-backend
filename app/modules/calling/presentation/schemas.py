# Re-export every calling schema from the application layer.
# Router imports and the wire format are unchanged.
from app.modules.calling.application.schemas import (  # noqa: F401
    CallCreate,
    CallEndedOut,
    CallHeartbeatOut,
    CallHistoryItemOut,
    CallHistoryOut,
    CallOut,
    CallRejectedOut,
    CallTokenOut,
    DeviceRegisteredOut,
    GroupSnapOut,
    ParticipantOut,
    StreamCredentialsOut,
    UserSnapOut,
)
from pydantic import BaseModel, Field


class DeviceRegister(BaseModel):
    fcm_token: str = Field(min_length=1, max_length=500)
    platform: str | None = Field(default=None, pattern="^(ios|android|web)$")
    # An iOS client holds two tokens and they are indistinguishable by value.
    # Defaults to "fcm" so existing clients keep working unchanged.
    token_type: str = Field(default="fcm", pattern="^(fcm|voip)$")

__all__ = [
    "CallCreate",
    "CallOut",
    "CallRejectedOut",
    "CallEndedOut",
    "CallHeartbeatOut",
    "CallTokenOut",
    "CallHistoryOut",
    "CallHistoryItemOut",
    "ParticipantOut",
    "StreamCredentialsOut",
    "UserSnapOut",
    "GroupSnapOut",
    "DeviceRegister",
    "DeviceRegisteredOut",
]
