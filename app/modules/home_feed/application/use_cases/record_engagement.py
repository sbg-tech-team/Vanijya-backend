"""
Record Engagement use case — acknowledges batched engagement signals.

Signals are not yet forwarded to source modules — taste/forwarding is a
later step. The endpoint acknowledges receipt so the client can batch.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.home_feed.application.schemas import EngagementBatch


def submit_engagement(
    user_id: UUID,
    batch: EngagementBatch,
) -> dict:
    # Signals are not yet forwarded to source modules — taste/forwarding is a
    # later step. The endpoint acknowledges receipt so the client can batch.
    return {"acknowledged": True, "signals_processed": len(batch.signals)}
