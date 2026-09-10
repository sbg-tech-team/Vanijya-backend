from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

VALID_REASONS = {"spam", "harassment", "inappropriate_content", "scam", "impersonation", "other"}
VALID_TARGET_TYPES = {"user", "group", "post"}


class ReportRequest(BaseModel):
    target_type: str = Field(..., pattern="^(user|group|post)$")
    target_id: UUID
    reason: str = Field(..., pattern="^(spam|harassment|inappropriate_content|scam|impersonation|other)$")
    description: Optional[str] = Field(None, max_length=1000)
