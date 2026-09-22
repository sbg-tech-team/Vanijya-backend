"""Notification switches.

Thin on purpose: the value is not here, it is that
CallingRepository.push_targets consults these before sending, so a preference
is honoured no matter which client version set it.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.profile.domain.entities import NotificationPrefs
from app.modules.profile.domain.interfaces.repository import IProfileRepository


def get_notification_prefs(repo: IProfileRepository, user_id: UUID) -> NotificationPrefs:
    return repo.get_notification_prefs(user_id)


def update_notification_prefs(
    repo: IProfileRepository,
    user_id: UUID,
    push_enabled: bool | None = None,
    market_alerts_enabled: bool | None = None,
    group_enabled: bool | None = None,
) -> NotificationPrefs:
    return repo.set_notification_prefs(
        user_id,
        push_enabled=push_enabled,
        market_alerts_enabled=market_alerts_enabled,
        group_enabled=group_enabled,
    )
