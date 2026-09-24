"""SQLAlchemy implementation of IConnectionsRepository.

The only file in the connections module that touches the database. Every query
body is moved verbatim from the use-case files, so the emitted SQL — including
eager-load options, ordering and the counter floors — is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, text
from sqlalchemy.orm import Session, aliased, joinedload

from app.recommendation.lookup import AmplifyLookupMixin
from app.modules.connections.data.models import MessageRequest, UserConnection
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.modules.profile.data.models import Business, Commodity, Profile, Profile_Commodity, Role


class ConnectionsRepository(AmplifyLookupMixin, IConnectionsRepository):

    def __init__(self, db: Session):
        self.db = db

    # -- profiles --------------------------------------------------------------

    def load_profile(self, user_id: UUID):
        return (
            self.db.query(Profile)
            .options(
                joinedload(Profile.role),
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.users_id == user_id)
            .first()
        )

    def load_profiles_bulk(self, user_ids: list[UUID]) -> dict:
        if not user_ids:
            return {}
        rows = (
            self.db.query(Profile)
            .options(
                joinedload(Profile.role),
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.users_id.in_(user_ids))
            .all()
        )
        return {p.users_id: p for p in rows}

    def bulk_statuses(self, me: UUID, target_ids: list[UUID]) -> dict:
        if not target_ids:
            return {}
        msg_reqs = self.db.query(MessageRequest).filter(
            MessageRequest.sender_id == me,
            MessageRequest.receiver_id.in_(target_ids),
        ).all()
        msg_req_map = {r.receiver_id: r.status for r in msg_reqs}

        follows = self.db.query(UserConnection).filter(
            UserConnection.follower_id == me,
            UserConnection.following_id.in_(target_ids),
        ).all()
        follow_set = {f.following_id for f in follows}

        return {
            uid: {
                "msg_req_status": msg_req_map.get(uid),
                "follow_status": uid in follow_set,
            }
            for uid in target_ids
        }

    # -- follow graph ----------------------------------------------------------

    def get_follow(self, follower_id: UUID, following_id: UUID):
        return self.db.query(UserConnection).filter(
            UserConnection.follower_id == follower_id,
            UserConnection.following_id == following_id,
        ).first()

    def add_follow(self, follower_id: UUID, following_id: UUID) -> None:
        # No counter to bump: follower/following counts are derived from these
        # rows when a profile is read. Maintaining an integer alongside was
        # correct only while every write went through here, and seeding and
        # load-test cleanup did not.
        self.db.add(UserConnection(follower_id=follower_id, following_id=following_id))
        self.db.commit()

    def remove_follow(self, follower_id: UUID, following_id: UUID) -> bool:
        conn = self.get_follow(follower_id, following_id)
        if not conn:
            return False
        self.db.delete(conn)
        # void only the caller's own outgoing message request to this user
        self.db.query(MessageRequest).filter(
            MessageRequest.sender_id == follower_id,
            MessageRequest.receiver_id == following_id,
        ).delete(synchronize_session=False)
        self.db.commit()
        return True

    def list_followers(self, user_id: UUID) -> list:
        return (
            self.db.query(UserConnection)
            .filter(UserConnection.following_id == user_id)
            .order_by(UserConnection.followed_at.desc())
            .all()
        )

    def list_following(self, user_id: UUID) -> list:
        return (
            self.db.query(UserConnection)
            .filter(UserConnection.follower_id == user_id)
            .order_by(UserConnection.followed_at.desc())
            .all()
        )

    # -- message requests ------------------------------------------------------

    def get_message_request(self, sender_id: UUID, receiver_id: UUID):
        return self.db.query(MessageRequest).filter(
            MessageRequest.sender_id == sender_id,
            MessageRequest.receiver_id == receiver_id,
        ).first()

    def get_message_request_by_id(self, request_id: int):
        return self.db.query(MessageRequest).filter(
            MessageRequest.id == request_id
        ).first()

    def get_pending_request_for_receiver(self, request_id: int, me: UUID):
        return self.db.query(MessageRequest).filter(
            MessageRequest.id == request_id,
            MessageRequest.receiver_id == me,
            MessageRequest.status == "pending",
        ).first()

    def add_message_request(self, sender_id: UUID, receiver_id: UUID, message: str | None):
        req = MessageRequest(
            sender_id=sender_id, receiver_id=receiver_id, first_message=message
        )
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)
        return req

    def delete_withdrawable_request(self, sender_id: UUID, receiver_id: UUID) -> bool:
        """Withdraw only a pending/declined request, as app_old did."""
        req = self.db.query(MessageRequest).filter(
            MessageRequest.sender_id == sender_id,
            MessageRequest.receiver_id == receiver_id,
            MessageRequest.status.in_(["pending", "declined"]),
        ).first()
        if not req:
            return False
        self.db.delete(req)
        self.db.commit()
        return True

    def set_message_request_status(self, request, status: str) -> None:
        request.status = status
        request.acted_at = datetime.now(timezone.utc)

    def revive_declined_request(self, request, message: str | None):
        """A declined request can be re-sent: back to pending, acted_at cleared."""
        request.status = "pending"
        request.sent_at = datetime.now(timezone.utc)
        request.acted_at = None
        request.first_message = message
        self.db.commit()
        self.db.refresh(request)
        return request

    def list_received_requests(self, me: UUID) -> list:
        return (
            self.db.query(MessageRequest)
            .filter(MessageRequest.receiver_id == me, MessageRequest.status == "pending")
            .order_by(MessageRequest.sent_at.desc())
            .all()
        )

    def list_sent_requests(self, me: UUID) -> list:
        return (
            self.db.query(MessageRequest)
            .filter(MessageRequest.sender_id == me)
            .order_by(MessageRequest.sent_at.desc())
            .all()
        )

    def commit(self) -> None:
        self.db.commit()

    # -- search ----------------------------------------------------------------

    def find_role_by_name(self, name: str):
        return self.db.query(Role).filter(Role.name.ilike(name)).first()

    def search_profiles(
        self, me: UUID, *, role: str | None, commodity: str | None, city: str | None,
        q: str | None, user_verified_only: bool, business_verified_only: bool,
        page: int, limit: int,
    ) -> tuple[list, int]:
        query = (
            self.db.query(Profile)
            .options(
                joinedload(Profile.role),
                # _fmt_profile dereferences profile.business per row, so without
                # this eager load every page costs `limit` extra queries (N+1).
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.users_id != me)
        )
        if role:
            role_row = self.find_role_by_name(role)
            if not role_row:
                return [], 0
            query = query.filter(Profile.role_id == role_row.id)
        if commodity:
            query = (
                query
                .join(Profile.commodities)
                .join(Profile_Commodity.commodity)
                .filter(Commodity.name.ilike(f"%{commodity}%"))
            )
        if q:
            query = query.filter(
                Profile.name.ilike(f"%{q}%")
                | Profile.id.in_(
                    self.db.query(Business.profile_id).filter(
                        Business.business_name.ilike(f"%{q}%")
                    )
                )
            )
        if city:
            query = query.filter(
                Profile.id.in_(
                    self.db.query(Business.profile_id).filter(Business.city.ilike(f"%{city}%"))
                )
            )
        if user_verified_only:
            query = query.filter(Profile.is_user_verified == True)  # noqa: E712
        if business_verified_only:
            query = query.filter(Profile.is_business_verified == True)  # noqa: E712

        total = query.count()
        rows = query.offset((page - 1) * limit).limit(limit).all()
        return rows, total

    def suggest_profiles(self, q: str, limit: int) -> list:
        return (
            self.db.query(Profile)
            .options(
                joinedload(Profile.role),
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(
                Profile.name.ilike(f"%{q}%")
                | Profile.id.in_(
                    self.db.query(Business.profile_id).filter(
                        Business.business_name.ilike(f"%{q}%")
                    )
                )
            )
            .limit(limit)
            .all()
        )

    # -- chat handoff ----------------------------------------------------------

    def find_dm_between(self, a: UUID, b: UUID):
        from app.modules.chat.data.models import Conversation, ConversationMember

        cm_a = aliased(ConversationMember)
        cm_b = aliased(ConversationMember)
        return (
            self.db.query(Conversation)
            .join(cm_a, and_(cm_a.conversation_id == Conversation.id, cm_a.user_id == a))
            .join(cm_b, and_(cm_b.conversation_id == Conversation.id, cm_b.user_id == b))
            .filter(Conversation.type == "dm")
            .first()
        )

    def create_dm(self, initiator_id: UUID, other_id: UUID, now: datetime) -> UUID:
        from app.modules.chat.data.models import Conversation, ConversationMember
        from app.modules.chat.domain.value_objects import ConversationStatus

        conv = Conversation(
            id=uuid4(), type="dm", status=ConversationStatus.ACTIVE,
            initiator_id=initiator_id, created_at=now, updated_at=now,
        )
        self.db.add(conv)
        self.db.flush()  # populate conv.id
        self.db.add(ConversationMember(conversation_id=conv.id, user_id=initiator_id, joined_at=now))
        self.db.add(ConversationMember(conversation_id=conv.id, user_id=other_id, joined_at=now))
        return conv.id

    def activate_dm(self, conv) -> None:
        from app.modules.chat.domain.value_objects import ConversationStatus

        conv.status = ConversationStatus.ACTIVE
        conv.updated_at = datetime.now(timezone.utc)

    def seed_first_message(self, conv_id: UUID, sender_id: UUID, body: str) -> None:
        from app.modules.chat.data.models import Message

        now = datetime.now(timezone.utc)
        self.db.add(Message(
            id=uuid4(),
            context_type="dm",
            context_id=conv_id,
            sender_id=sender_id,
            message_type="text",
            body=body,
            is_deleted=False,
            sent_at=now,
        ))

    # -- recommendations -------------------------------------------------------

    # Hand-written SQL: the <=> cosine operator has no ORM expression, and the
    # HNSW index is only used when the ORDER BY is written exactly this way.

    # Candidates the user has already acted on never come back. Inlined into
    # both queries below so the count and the page agree on the same pool.
    _BASE_EXCLUSIONS = """
              AND user_id NOT IN (
                  SELECT following_id
                  FROM user_connections
                  WHERE follower_id = CAST(:uid AS uuid)
              )
              AND user_id NOT IN (
                  SELECT receiver_id
                  FROM message_requests
                  WHERE sender_id = CAST(:uid AS uuid)
              )
    """

    @staticmethod
    def _seen_clause(seen_ids: list[str]) -> tuple[str, dict]:
        if not seen_ids:
            return "", {}
        return (
            "AND user_id != ALL(string_to_array(:seen_csv, \',\')::uuid[])",
            {"seen_csv": ",".join(seen_ids)},
        )

    def count_recommendable_users(self, user_id: UUID, seen_ids: list[str]) -> int:
        seen_filter, seen_params = self._seen_clause(seen_ids)
        row = self.db.execute(
            text(f"""
                SELECT COUNT(*) AS cnt
                FROM user_embeddings
                WHERE user_id != CAST(:uid AS uuid)
                  AND is_vector IS NOT NULL
                  {self._BASE_EXCLUSIONS}
                  {seen_filter}
            """),
            {"uid": str(user_id), **seen_params},
        ).mappings().one()
        return int(row["cnt"])

    def ann_user_candidates(
        self, vector: str, user_id: UUID, seen_ids: list[str], limit: int, offset: int
    ) -> list[dict]:
        seen_filter, seen_params = self._seen_clause(seen_ids)
        rows = self.db.execute(
            text(f"""
                SELECT user_id,
                       1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
                FROM user_embeddings
                WHERE user_id != CAST(:uid AS uuid)
                  AND is_vector IS NOT NULL
                  {self._BASE_EXCLUSIONS}
                  {seen_filter}
                ORDER BY is_vector <=> CAST(:vec AS vector)
                LIMIT :lim OFFSET :off
            """),
            {"vec": vector, "uid": str(user_id), "lim": limit, "off": offset, **seen_params},
        ).mappings().all()
        return [dict(m) for m in rows]

    def ann_user_candidates_unfiltered(self, vector: str, limit: int) -> list[dict]:
        rows = self.db.execute(
            text("""
                SELECT user_id,
                       1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
                FROM user_embeddings
                WHERE is_vector IS NOT NULL
                ORDER BY is_vector <=> CAST(:vec AS vector)
                LIMIT :k
            """),
            {"vec": vector, "k": limit},
        ).mappings().all()
        return [dict(m) for m in rows]

