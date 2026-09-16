from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.modules.calling.domain.entities import (
    CallEntity,
    CallHistoryItem,
    GroupSnap,
    PushTarget,
    UserSnap,
)


class ICallingRepository(ABC):
    """Every database access in the calling module goes through this interface."""

    # -- identity / targets ----------------------------------------------------

    @abstractmethod
    def get_user_snap(self, user_id: UUID) -> UserSnap | None: ...

    @abstractmethod
    def get_user_snaps(self, user_ids: list[UUID]) -> dict[UUID, UserSnap]:
        """Bulk identity lookup — one query, keyed by user_id."""
        ...

    @abstractmethod
    def get_group_snap(self, group_id: UUID) -> GroupSnap | None: ...

    @abstractmethod
    def is_group_member(self, group_id: UUID, user_id: UUID) -> bool: ...

    @abstractmethod
    def group_member_ids(self, group_id: UUID) -> list[UUID]: ...

    @abstractmethod
    def either_blocked(self, user_a: UUID, user_b: UUID) -> bool:
        """True if either user has blocked the other. Delegates to user_blocks."""
        ...

    @abstractmethod
    def get_or_create_dm_id(self, user_a: UUID, user_b: UUID) -> UUID:
        """Conversation id for the pair, creating an ACTIVE DM if none exists.
        A call is itself consent to converse, matching message-request accept."""
        ...

    # -- concurrency -----------------------------------------------------------

    @abstractmethod
    def lock_users_for_call(self, user_ids: list[UUID]) -> None:
        """Take a transaction-scoped lock on each user before the busy check.

        `busy_call_id` + `create_call` is check-then-act: without this two
        simultaneous requests both see the user as free and both create a call,
        so one person ends up in two calls billing in parallel. Locks are taken
        in sorted order so two calls involving the same pair cannot deadlock.
        Released automatically on commit or rollback.
        """
        ...

    @abstractmethod
    def lock_call(self, call_id: UUID) -> bool:
        """Row-lock one call for the duration of the transaction.

        Serialises the end path. Without it the last two participants can hang
        up simultaneously, each still see the other as present, and neither
        terminalises the call — leaving it billing until a sweep.
        Returns False if the call does not exist.
        """
        ...

    # -- call lifecycle --------------------------------------------------------

    @abstractmethod
    def create_call(
        self,
        call_id: UUID,
        stream_call_type: str,
        stream_call_id: str,
        call_type: str,
        media: str,
        context_id: UUID,
        initiator_id: UUID,
        participant_ids: list[UUID],
        now: datetime,
    ) -> CallEntity: ...

    @abstractmethod
    def get_call(self, call_id: UUID) -> CallEntity | None: ...

    @abstractmethod
    def busy_call_id(self, user_id: UUID) -> UUID | None:
        """Id of the user's ringing/active call, or None if they are free."""
        ...

    @abstractmethod
    def mark_participant_joined(
        self, call_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    @abstractmethod
    def mark_participant_rejected(
        self, call_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    @abstractmethod
    def mark_participant_left(
        self, call_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    @abstractmethod
    def activate_call(self, call_id: UUID, now: datetime) -> datetime:
        """Flip ringing -> active on the first accept. Returns the definitive
        started_at: set once, never moved on later joins."""
        ...

    @abstractmethod
    def end_call(
        self, call_id: UUID, status: str, end_reason: str, now: datetime
    ) -> CallEntity:
        """Terminalise the call and compute duration_seconds from started_at."""
        ...

    @abstractmethod
    def active_participant_count(self, call_id: UUID) -> int:
        """Participants currently joined — drives 'last one out ends the call'."""
        ...

    @abstractmethod
    def participant_count(self, call_id: UUID) -> int:
        """All participants regardless of state — enforces MAX_CALL_PARTICIPANTS."""
        ...

    # -- history ---------------------------------------------------------------

    @abstractmethod
    def list_calls(
        self,
        user_id: UUID,
        limit: int,
        cursor: datetime | None,
        call_type: str | None,
    ) -> tuple[list[CallHistoryItem], datetime | None]:
        """One page of the user's call history plus the next cursor."""
        ...

    # -- chat call card --------------------------------------------------------

    @abstractmethod
    def write_call_card(
        self,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        call_id: UUID,
        media: str,
        status: str,
        end_reason: str | None,
        duration_seconds: int,
        sent_at: datetime,
    ) -> None:
        """Insert the `call` message that renders the call inline in chat.
        Best-effort: implementations must not raise."""
        ...

    # -- push ------------------------------------------------------------------

    @abstractmethod
    def push_targets(self, user_ids: list[UUID]) -> list[PushTarget]:
        """Every device for these users, deduped by token."""
        ...

    @abstractmethod
    def register_device(
        self, user_id: UUID, fcm_token: str, platform: str | None, now: datetime
    ) -> None:
        """Record or refresh one device's push token."""
        ...

    # -- jobs ------------------------------------------------------------------

    @abstractmethod
    def expired_ringing_call_ids(self, cutoff: datetime) -> list[UUID]:
        """Calls still ringing past the ring timeout."""
        ...

    @abstractmethod
    def stale_active_call_ids(self, cutoff: datetime) -> list[UUID]:
        """Calls stuck in active with no end signal — both clients died."""
        ...

    @abstractmethod
    def touch_heartbeat(self, call_id: UUID, user_id: UUID, now: datetime) -> None:
        """Record liveness for ONE participant. Presence is per person, not per
        call: otherwise whoever is still alive keeps the call looking healthy
        while everyone else has vanished."""
        ...

    @abstractmethod
    def dead_heartbeat_call_ids(self, cutoff: datetime) -> list[UUID]:
        """Active calls with no present participant left — every client is gone.
        Participants that never reported a heartbeat fall back to the call's
        started_at, so a client too old to send them is still caught."""
        ...

    @abstractmethod
    def active_call_ids_started_before(self, cutoff: datetime) -> list[UUID]:
        """Candidate set for the presence-driven sweeps. Presence itself is
        decided in Redis, not here."""
        ...

    @abstractmethod
    def live_call_ids_between(self, user_a: UUID, user_b: UUID) -> list[UUID]:
        """Ringing or active calls both users are in."""
        ...

    @abstractmethod
    def mark_provider_ended(self, call_id: UUID, now: datetime) -> None:
        """Record that the provider confirmed the session is terminated."""
        ...

    @abstractmethod
    def unterminated_provider_call_ids(self, since: datetime) -> list[UUID]:
        """Terminal calls whose provider session was never confirmed ended."""
        ...

    @abstractmethod
    def overlong_call_ids(self, cutoff: datetime) -> list[UUID]:
        """Active calls that have run past the maximum allowed duration."""
        ...

    @abstractmethod
    def solo_participant_call_ids(
        self, cutoff: datetime, started_before: datetime
    ) -> list[UUID]:
        """Active calls where exactly one participant is still present — nobody
        left to talk to, so the call is burning participant-minutes for
        nothing."""
        ...

    # -- unit of work ----------------------------------------------------------

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...
