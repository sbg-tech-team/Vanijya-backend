"""SQLAlchemy implementation of ICallingRepository.

The only file in the calling module that touches the database.

Cross-module reads (Profile, GroupMember, UserBlock, Conversation) are done here
rather than by calling into those modules' services, matching how chat and
connections already reach across for identity and membership.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased, selectinload

from app.modules.calling.data.models import Call, CallParticipant, UserDevice
from app.modules.calling.domain.entities import (
    CallEntity,
    CallHistoryItem,
    GroupSnap,
    ParticipantEntity,
    PushTarget,
    UserSnap,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.value_objects import (
    BUSY_STATUSES,
    MAX_CALL_DURATION_SECONDS,
    CallStatus,
    ParticipantRole,
    ParticipantState,
)
from app.modules.chat.data.models import Conversation, ConversationMember
from app.modules.chat.domain.value_objects import ConversationStatus
from app.modules.groups.data.models import Group, GroupMember
from app.modules.profile.data.models import NotificationPreferences, Profile, User
from app.modules.safety.data.models import UserBlock

log = logging.getLogger(__name__)


def _to_participant(row: CallParticipant, snap: UserSnap | None) -> ParticipantEntity:
    return ParticipantEntity(
        user_id=row.user_id,
        profile_id=snap.profile_id if snap else 0,
        name=snap.name if snap else "Unknown",
        avatar_url=snap.avatar_url if snap else None,
        role=row.role,
        state=row.state,
        joined_at=row.joined_at,
        left_at=row.left_at,
    )


class CallingRepository(ICallingRepository):

    def __init__(self, db: Session) -> None:
        self.db = db


    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    # ── Identity / targets ────────────────────────────────────────────────────

    def get_user_snap(self, user_id: UUID) -> UserSnap | None:
        row = (
            self.db.query(Profile.users_id, Profile.id, Profile.name, Profile.avatar_url)
            .filter(Profile.users_id == user_id)
            .first()
        )
        if row is None:
            return None
        return UserSnap(user_id=row[0], profile_id=row[1], name=row[2], avatar_url=row[3])

    def get_user_snaps(self, user_ids: list[UUID]) -> dict[UUID, UserSnap]:
        if not user_ids:
            return {}
        rows = (
            self.db.query(Profile.users_id, Profile.id, Profile.name, Profile.avatar_url)
            .filter(Profile.users_id.in_(user_ids))
            .all()
        )
        return {
            r[0]: UserSnap(user_id=r[0], profile_id=r[1], name=r[2], avatar_url=r[3])
            for r in rows
        }

    def get_group_snap(self, group_id: UUID) -> GroupSnap | None:
        row = (
            self.db.query(Group.id, Group.name, Group.image_url)
            .filter(Group.id == group_id)
            .first()
        )
        if row is None:
            return None
        return GroupSnap(group_id=row[0], name=row[1], image_url=row[2])

    def is_group_member(self, group_id: UUID, user_id: UUID) -> bool:
        return self.db.query(GroupMember.user_id).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        ).first() is not None

    def group_member_ids(self, group_id: UUID) -> list[UUID]:
        rows = (
            self.db.query(GroupMember.user_id)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.is_frozen.is_(False),
            )
            .all()
        )
        return [r[0] for r in rows]

    def either_blocked(self, user_a: UUID, user_b: UUID) -> bool:
        """Symmetric block check. The safety module owns user_blocks; this reads
        it directly rather than importing safety's service, matching how chat and
        connections reach across module boundaries for shared facts."""
        return self.db.query(UserBlock).filter(
            or_(
                and_(UserBlock.blocker_id == user_a, UserBlock.blocked_id == user_b),
                and_(UserBlock.blocker_id == user_b, UserBlock.blocked_id == user_a),
            )
        ).first() is not None

    def get_or_create_dm_id(self, user_a: UUID, user_b: UUID) -> UUID:
        cm_a = aliased(ConversationMember)
        cm_b = aliased(ConversationMember)
        conv = (
            self.db.query(Conversation)
            .join(cm_a, and_(cm_a.conversation_id == Conversation.id, cm_a.user_id == user_a))
            .join(cm_b, and_(cm_b.conversation_id == Conversation.id, cm_b.user_id == user_b))
            .filter(Conversation.type == "dm")
            .first()
        )
        if conv is not None:
            return conv.id

        now = datetime.now(timezone.utc)
        conv = Conversation(
            id=uuid4(), type="dm", status=ConversationStatus.ACTIVE,
            initiator_id=user_a, created_at=now, updated_at=now,
        )
        self.db.add(conv)
        self.db.flush()
        self.db.add(ConversationMember(conversation_id=conv.id, user_id=user_a, joined_at=now))
        self.db.add(ConversationMember(conversation_id=conv.id, user_id=user_b, joined_at=now))
        return conv.id

    # ── Concurrency ───────────────────────────────────────────────────────────

    def lock_users_for_call(self, user_ids: list[UUID]) -> None:
        """Postgres transaction-scoped advisory locks, one per user.

        Advisory rather than row locks because there is no single row that
        represents "this user is on a call" — the fact is derived from a join.
        hashtext() gives a stable bigint key from the UUID; collisions only cost
        a little unnecessary serialisation, never correctness.

        Sorted so two requests involving the same two people always acquire in
        the same order and cannot deadlock.
        """
        for uid in sorted(str(u) for u in user_ids):
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"call:{uid}"}
            )

    def lock_call(self, call_id: UUID) -> bool:
        row = self.db.execute(
            text("SELECT id FROM calls WHERE id = :cid FOR UPDATE"), {"cid": str(call_id)}
        ).first()
        return row is not None

    # ── Call lifecycle ────────────────────────────────────────────────────────

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
    ) -> CallEntity:
        call = Call(
            id=call_id,
            stream_call_type=stream_call_type,
            stream_call_id=stream_call_id,
            call_type=call_type,
            media=media,
            status=CallStatus.RINGING.value,
            context_id=context_id,
            initiator_id=initiator_id,
            created_at=now,
        )
        self.db.add(call)
        self.db.flush()

        # Initiator is already in the call; everyone else is ringing.
        for uid in participant_ids:
            is_caller = uid == initiator_id
            self.db.add(CallParticipant(
                call_id=call_id,
                user_id=uid,
                role=ParticipantRole.CALLER.value if is_caller else ParticipantRole.CALLEE.value,
                state=ParticipantState.JOINED.value if is_caller else ParticipantState.RINGING.value,
                joined_at=now if is_caller else None,
            ))
        self.db.flush()
        return self._build_call(call_id)

    def get_call(self, call_id: UUID) -> CallEntity | None:
        return self._build_call(call_id)

    def busy_call_id(self, user_id: UUID) -> UUID | None:
        """A call only makes you busy while it could plausibly still be live.

        The age bound matters: if a sweep is delayed or fails, a dead call would
        otherwise mark both participants busy indefinitely and lock them out of
        calling entirely. Better to allow a new call than to strand the user on
        a call that no longer exists.
        """
        horizon = datetime.now(timezone.utc) - timedelta(
            seconds=MAX_CALL_DURATION_SECONDS
        )
        row = (
            self.db.query(Call.id)
            .join(CallParticipant, CallParticipant.call_id == Call.id)
            .filter(
                CallParticipant.user_id == user_id,
                CallParticipant.state.in_([
                    ParticipantState.RINGING.value, ParticipantState.JOINED.value,
                ]),
                Call.status.in_(list(BUSY_STATUSES)),
                Call.created_at >= horizon,
            )
            .first()
        )
        return row[0] if row else None

    def mark_participant_joined(self, call_id: UUID, user_id: UUID, now: datetime) -> None:
        self.db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        ).update(
            {"state": ParticipantState.JOINED.value, "joined_at": now},
            synchronize_session=False,
        )

    def mark_participant_rejected(self, call_id: UUID, user_id: UUID, now: datetime) -> None:
        self.db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        ).update(
            {"state": ParticipantState.REJECTED.value, "left_at": now},
            synchronize_session=False,
        )

    def mark_participant_left(self, call_id: UUID, user_id: UUID, now: datetime) -> None:
        self.db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        ).update(
            {"state": ParticipantState.LEFT.value, "left_at": now},
            synchronize_session=False,
        )

    def activate_call(self, call_id: UUID, now: datetime) -> datetime:
        call = self.db.query(Call).filter(Call.id == call_id).first()
        if call is None:
            return now
        if call.started_at is None:
            call.started_at = now
        call.status = CallStatus.ACTIVE.value
        return call.started_at

    def end_call(
        self, call_id: UUID, status: str, end_reason: str, now: datetime
    ) -> CallEntity:
        call = self.db.query(Call).filter(Call.id == call_id).first()
        if call is not None:
            call.status = status
            call.ended_at = now
            call.end_reason = end_reason
            if call.started_at is not None:
                started = call.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                call.duration_seconds = max(0, int((now - started).total_seconds()))
            else:
                call.duration_seconds = 0

            # Anyone still ringing when the call dies was never reached.
            self.db.query(CallParticipant).filter(
                CallParticipant.call_id == call_id,
                CallParticipant.state == ParticipantState.RINGING.value,
            ).update(
                {"state": ParticipantState.MISSED.value, "left_at": now},
                synchronize_session=False,
            )
            self.db.query(CallParticipant).filter(
                CallParticipant.call_id == call_id,
                CallParticipant.state == ParticipantState.JOINED.value,
            ).update(
                {"state": ParticipantState.LEFT.value, "left_at": now},
                synchronize_session=False,
            )
            self.db.flush()
        return self._build_call(call_id)

    def active_participant_count(self, call_id: UUID) -> int:
        return (
            self.db.query(func.count(CallParticipant.user_id))
            .filter(
                CallParticipant.call_id == call_id,
                CallParticipant.state == ParticipantState.JOINED.value,
            )
            .scalar()
        ) or 0

    def participant_count(self, call_id: UUID) -> int:
        return (
            self.db.query(func.count(CallParticipant.user_id))
            .filter(CallParticipant.call_id == call_id)
            .scalar()
        ) or 0

    # ── History ───────────────────────────────────────────────────────────────

    def list_calls(
        self,
        user_id: UUID,
        limit: int,
        cursor: datetime | None,
        call_type: str | None,
    ) -> tuple[list[CallHistoryItem], datetime | None]:
        q = (
            self.db.query(Call)
            .join(CallParticipant, CallParticipant.call_id == Call.id)
            .filter(CallParticipant.user_id == user_id)
        )
        if call_type:
            q = q.filter(Call.call_type == call_type)
        if cursor is not None:
            q = q.filter(Call.created_at < cursor)

        calls = q.order_by(Call.created_at.desc()).limit(limit).all()
        if not calls:
            return [], None

        call_ids = [c.id for c in calls]

        # Batch every lookup the page needs — three queries total, no N+1.
        part_rows = (
            self.db.query(CallParticipant)
            .filter(CallParticipant.call_id.in_(call_ids))
            .all()
        )
        by_call: dict[UUID, list[CallParticipant]] = {}
        for p in part_rows:
            by_call.setdefault(p.call_id, []).append(p)

        other_ids = {
            p.user_id for p in part_rows if p.user_id != user_id
        }
        snaps = self.get_user_snaps(list(other_ids))

        group_ids = [c.context_id for c in calls if c.call_type == "group"]
        groups: dict[UUID, GroupSnap] = {}
        if group_ids:
            for g in (
                self.db.query(Group.id, Group.name, Group.image_url)
                .filter(Group.id.in_(group_ids))
                .all()
            ):
                groups[g[0]] = GroupSnap(group_id=g[0], name=g[1], image_url=g[2])

        items: list[CallHistoryItem] = []
        for c in calls:
            parts = by_call.get(c.id, [])
            counterparty = None
            group = None
            if c.call_type == "dm":
                other = next((p for p in parts if p.user_id != user_id), None)
                counterparty = snaps.get(other.user_id) if other else None
            else:
                group = groups.get(c.context_id)

            items.append(CallHistoryItem(
                call_id=c.id,
                call_type=c.call_type,
                media=c.media,
                status=c.status,
                direction="outgoing" if c.initiator_id == user_id else "incoming",
                end_reason=c.end_reason,
                created_at=c.created_at,
                started_at=c.started_at,
                ended_at=c.ended_at,
                duration_seconds=c.duration_seconds,
                counterparty=counterparty,
                group=group,
                participant_count=len(parts),
            ))

        next_cursor = calls[-1].created_at if len(calls) == limit else None
        return items, next_cursor

    # ── Chat call card ────────────────────────────────────────────────────────

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
        """Drop a `call` message into the thread so the call shows inline in chat.

        Shares the caller's transaction but must never break it: a failed card
        write is logged and swallowed, the call still ends cleanly.
        """
        from app.modules.chat.data.models import Message

        try:
            self.db.add(Message(
                context_type=context_type,
                context_id=context_id,
                sender_id=sender_id,
                message_type="call",
                body=None,
                media_metadata={
                    "call_id": str(call_id),
                    "media": media,
                    "status": status,
                    "end_reason": end_reason,
                    "duration_seconds": duration_seconds,
                },
                sent_at=sent_at,
            ))
            self.db.flush()
        except Exception as exc:
            log.warning("call card write failed for call %s: %s", call_id, exc)

    # ── Push ──────────────────────────────────────────────────────────────────

    def push_targets(
        self, user_ids: list[UUID], category: str = "push"
    ) -> list[PushTarget]:
        """Every device belonging to these users, minus those who switched this
        category off.

        The preference check lives here because both push call sites route
        through this method — the request path and the sweep jobs. Putting it
        in either caller would leave the other sending regardless.

        `category` is "push" (master only), "group", or "market_alerts". The
        master switch gates everything: off means no push of any kind, calls
        included, which is what a person means by turning push notifications
        off.

        Reads user_devices first, then falls back to the legacy
        users.fcm_token for anyone who has not re-registered since the switch.
        Deduped by token: a device present in both sources must not be rung
        twice.
        """
        if not user_ids:
            return []

        user_ids = self._push_allowed(user_ids, category)
        if not user_ids:
            return []

        seen: set[str] = set()
        out: list[PushTarget] = []

        for uid, token, ttype in (
            self.db.query(UserDevice.user_id, UserDevice.fcm_token, UserDevice.token_type)
            .filter(UserDevice.user_id.in_(user_ids))
            .all()
        ):
            if token and token not in seen:
                seen.add(token)
                out.append(PushTarget(user_id=uid, fcm_token=token, token_type=ttype or "fcm"))

        for uid, token in (
            self.db.query(User.id, User.fcm_token)
            .filter(User.id.in_(user_ids), User.fcm_token.isnot(None))
            .all()
        ):
            if token and token not in seen:
                seen.add(token)
                out.append(PushTarget(user_id=uid, fcm_token=token))

        return out

    def _push_allowed(self, user_ids: list[UUID], category: str) -> list[UUID]:
        """Drop users who switched this category off. A user with no row has
        never opened Settings and keeps the previous all-on behaviour."""
        column = {
            "group": NotificationPreferences.group_enabled,
            "market_alerts": NotificationPreferences.market_alerts_enabled,
        }.get(category)

        q = self.db.query(NotificationPreferences.user_id).filter(
            NotificationPreferences.user_id.in_(user_ids)
        )
        blocked = {
            r[0] for r in q.filter(
                NotificationPreferences.push_enabled.is_(False)
                if column is None
                else (NotificationPreferences.push_enabled.is_(False)) | (column.is_(False))
            ).all()
        }
        return [u for u in user_ids if u not in blocked]

    def register_device(
        self, user_id: UUID, fcm_token: str, platform: str | None, now: datetime,
        token_type: str = "fcm",
    ) -> None:
        """Upsert on the token, not on (user, token): a handset handed to another
        account must ring the new owner, never the old one."""
        stmt = (
            pg_insert(UserDevice)
            .values(
                id=uuid4(), user_id=user_id, fcm_token=fcm_token,
                platform=platform, token_type=token_type,
                last_seen_at=now, created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["fcm_token"],
                set_={"user_id": user_id, "platform": platform,
                      "token_type": token_type, "last_seen_at": now},
            )
        )
        self.db.execute(stmt)

    def delete_devices(self, fcm_tokens: list[str]) -> int:
        """Drop tokens FCM told us are dead (app uninstalled, token rotated).

        Also clears the legacy users.fcm_token copy, otherwise push_targets
        keeps resurrecting the same dead token from the fallback branch.
        """
        if not fcm_tokens:
            return 0
        n = (
            self.db.query(UserDevice)
            .filter(UserDevice.fcm_token.in_(fcm_tokens))
            .delete(synchronize_session=False)
        )
        (
            self.db.query(User)
            .filter(User.fcm_token.in_(fcm_tokens))
            .update({"fcm_token": None}, synchronize_session=False)
        )
        return n

    def delete_device_for_user(self, user_id: UUID, fcm_token: str) -> int:
        """Forget one device, but only if it belongs to this user.

        The user_id is in the WHERE clause deliberately: an unscoped
        delete-by-token would let anyone silence a phone whose token they had
        obtained.
        """
        n = (
            self.db.query(UserDevice)
            .filter(UserDevice.user_id == user_id, UserDevice.fcm_token == fcm_token)
            .delete(synchronize_session=False)
        )
        # The legacy single-token column would otherwise resurrect it via the
        # fallback branch of push_targets.
        (
            self.db.query(User)
            .filter(User.id == user_id, User.fcm_token == fcm_token)
            .update({"fcm_token": None}, synchronize_session=False)
        )
        return n

    # ── Jobs ──────────────────────────────────────────────────────────────────

    def expired_ringing_call_ids(self, cutoff: datetime) -> list[UUID]:
        rows = (
            self.db.query(Call.id)
            .filter(Call.status == CallStatus.RINGING.value, Call.created_at < cutoff)
            .all()
        )
        return [r[0] for r in rows]

    def stale_active_call_ids(self, cutoff: datetime) -> list[UUID]:
        rows = (
            self.db.query(Call.id)
            .filter(Call.status == CallStatus.ACTIVE.value, Call.started_at < cutoff)
            .all()
        )
        return [r[0] for r in rows]

    def touch_heartbeat(self, call_id: UUID, user_id: UUID, now: datetime) -> None:
        self.db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        ).update({"last_heartbeat_at": now}, synchronize_session=False)

    def _present_count_subq(self, cutoff: datetime):
        """Per-call count of participants who are actually PRESENT.

        Present means: state=joined AND a heartbeat newer than `cutoff`. The
        COALESCE onto the call's started_at grants a grace period from the start
        of the call, so a client that has not yet sent its first ping — or one
        too old to send any — is not swept instantly.

        This replaces inferring presence from `state` alone. `state` records
        intent (we mark the caller joined the moment they ring), whereas this
        records evidence.
        """
        return (
            self.db.query(
                CallParticipant.call_id.label("cid"),
                func.count(CallParticipant.user_id).label("present"),
            )
            .join(Call, Call.id == CallParticipant.call_id)
            .filter(
                CallParticipant.state == ParticipantState.JOINED.value,
                func.coalesce(CallParticipant.last_heartbeat_at, Call.started_at) >= cutoff,
            )
            .group_by(CallParticipant.call_id)
            .subquery()
        )

    def dead_heartbeat_call_ids(self, cutoff: datetime) -> list[UUID]:
        """Active calls where NOBODY is present any more — every client is gone.

        LEFT JOIN, because a call with zero present participants has no row in
        the subquery at all; an inner join would silently skip exactly the calls
        we are hunting.
        """
        present = self._present_count_subq(cutoff)
        rows = (
            self.db.query(Call.id)
            .outerjoin(present, present.c.cid == Call.id)
            .filter(
                Call.status == CallStatus.ACTIVE.value,
                func.coalesce(present.c.present, 0) == 0,
            )
            .all()
        )
        return [r[0] for r in rows]

    def overlong_call_ids(self, cutoff: datetime) -> list[UUID]:
        rows = (
            self.db.query(Call.id)
            .filter(Call.status == CallStatus.ACTIVE.value, Call.started_at < cutoff)
            .all()
        )
        return [r[0] for r in rows]

    def solo_participant_call_ids(self, cutoff: datetime, started_before: datetime) -> list[UUID]:
        """Active calls where exactly one participant is still PRESENT.

        Presence is measured by heartbeat, not by `state`, so this now catches
        the case the previous `left_at`-based version could not: a peer whose
        app died without hanging up never sets `left_at`, so there was no
        "someone left" event to key off and the call ran until the hard cap.

        `started_before` keeps a just-started call out of the sweep while the
        second participant is still connecting.
        """
        present = self._present_count_subq(cutoff)
        rows = (
            self.db.query(Call.id)
            .join(present, present.c.cid == Call.id)
            .filter(
                Call.status == CallStatus.ACTIVE.value,
                Call.started_at < started_before,
                present.c.present == 1,
            )
            .all()
        )
        return [r[0] for r in rows]

    def active_call_ids_started_before(self, cutoff: datetime) -> list[UUID]:
        """Every active call old enough to judge. Presence itself is decided in
        Redis; this is only the candidate set, kept deliberately cheap."""
        rows = (
            self.db.query(Call.id)
            .filter(
                Call.status == CallStatus.ACTIVE.value,
                Call.started_at.isnot(None),
                Call.started_at < cutoff,
            )
            .all()
        )
        return [r[0] for r in rows]

    def live_call_ids_between(self, user_a: UUID, user_b: UUID) -> list[UUID]:
        """Ringing or active calls both users are in. Used when a block lands
        mid-call: refusing new calls while leaving the current one connected
        would make the block look broken to the person who set it."""
        cp_a = aliased(CallParticipant)
        cp_b = aliased(CallParticipant)
        rows = (
            self.db.query(Call.id)
            .join(cp_a, and_(cp_a.call_id == Call.id, cp_a.user_id == user_a))
            .join(cp_b, and_(cp_b.call_id == Call.id, cp_b.user_id == user_b))
            .filter(Call.status.in_(list(BUSY_STATUSES)))
            .all()
        )
        return [r[0] for r in rows]

    def mark_provider_ended(self, call_id: UUID, now: datetime) -> None:
        self.db.query(Call).filter(Call.id == call_id).update(
            {"provider_ended_at": now}, synchronize_session=False
        )

    def unterminated_provider_call_ids(self, since: datetime) -> list[UUID]:
        """Terminal calls whose provider session was never confirmed ended.

        A failed mark_ended is the one failure that keeps costing money after
        everything else has finished, and nothing else retries it: the other
        sweeps all skip terminal calls.
        """
        rows = (
            self.db.query(Call.id)
            .filter(
                Call.status.notin_(list(BUSY_STATUSES)),
                Call.provider_ended_at.is_(None),
                Call.ended_at >= since,
            )
            .all()
        )
        return [r[0] for r in rows]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_call(self, call_id: UUID) -> CallEntity | None:
        call = (
            self.db.query(Call)
            .options(selectinload(Call.participants))
            .filter(Call.id == call_id)
            .first()
        )
        if call is None:
            return None

        snaps = self.get_user_snaps([p.user_id for p in call.participants])
        return CallEntity(
            id=call.id,
            stream_call_type=call.stream_call_type,
            stream_call_id=call.stream_call_id,
            call_type=call.call_type,
            media=call.media,
            status=call.status,
            context_id=call.context_id,
            initiator_id=call.initiator_id,
            created_at=call.created_at,
            started_at=call.started_at,
            ended_at=call.ended_at,
            duration_seconds=call.duration_seconds,
            end_reason=call.end_reason,
            participants=[
                _to_participant(p, snaps.get(p.user_id)) for p in call.participants
            ],
        )
