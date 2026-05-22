from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.modules.chat.data.models import ChatAttachment, Conversation, ConversationMember, Message
from app.modules.chat.domain.entities import ConvSendGuard, ConvStatus, ConversationEntity, LastMessage, MessageEntity, UserSnap
from app.modules.chat.domain.repository import IChatRepository
from app.modules.groups.models import Group, GroupMember
from app.modules.profile.models import Profile


def _profile_snap(profile: Profile) -> UserSnap:
    return UserSnap(
        user_id=profile.users_id,
        profile_id=profile.id,
        name=profile.name,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
    )


def _last_message(db: Session, context_id: UUID) -> Optional[LastMessage]:
    row = (
        db.query(Message)
        .filter(Message.context_type == "dm", Message.context_id == context_id, Message.is_deleted.is_(False))
        .order_by(Message.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return LastMessage(id=row.id, body=row.body, message_type=row.message_type, sender_id=row.sender_id, sent_at=row.created_at)


def _unread_count(db: Session, conv_id: UUID, user_id: UUID) -> int:
    member = (
        db.query(ConversationMember)
        .filter(ConversationMember.conversation_id == conv_id, ConversationMember.user_id == user_id)
        .first()
    )
    if member is None:
        return 0
    q = db.query(func.count(Message.id)).filter(
        Message.context_type == "dm",
        Message.context_id == conv_id,
        Message.is_deleted.is_(False),
        Message.sender_id != user_id,
    )
    if member.last_read_at is not None:
        q = q.filter(Message.created_at > member.last_read_at)
    return q.scalar() or 0


def _build_conversation(db: Session, conv: Conversation, requesting_user_id: UUID) -> Optional[ConversationEntity]:
    members = db.query(ConversationMember).filter(ConversationMember.conversation_id == conv.id).all()
    other_member = next((m for m in members if m.user_id != requesting_user_id), None)
    my_member = next((m for m in members if m.user_id == requesting_user_id), None)

    if other_member is None or my_member is None:
        return None

    other_profile = db.query(Profile).filter(Profile.users_id == other_member.user_id).first()
    if other_profile is None:
        return None

    return ConversationEntity(
        id=conv.id,
        status=conv.status,
        initiator_id=conv.initiator_id,
        participant=_profile_snap(other_profile),
        last_message=_last_message(db, conv.id),
        unread_count=_unread_count(db, conv.id, requesting_user_id),
        is_muted=my_member.is_muted,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _build_message(db: Session, msg: Message) -> MessageEntity:
    sender_profile = db.query(Profile).filter(Profile.users_id == msg.sender_id).first()
    sender_snap = (
        _profile_snap(sender_profile)
        if sender_profile
        else UserSnap(user_id=msg.sender_id, profile_id=0, name="Unknown", is_user_verified=False, is_business_verified=False)
    )
    return MessageEntity(
        id=msg.id,
        context_id=msg.context_id,
        context_type=msg.context_type,
        sender=sender_snap,
        message_type=msg.message_type,
        body=msg.body,
        media_url=msg.media_url,
        media_metadata=msg.media_metadata,
        location_lat=msg.location_lat,
        location_lon=msg.location_lon,
        reply_to_id=msg.reply_to_id,
        is_deleted=msg.is_deleted,
        sent_at=msg.created_at,
    )


class ChatRepository(IChatRepository):

    def __init__(self, db: Session):
        self.db = db

    # ── Conversations ─────────────────────────────────────────────────────────

    def get_or_create_dm(self, sender_id: UUID, participant_id: UUID) -> tuple[ConversationEntity, bool]:
        cm1 = aliased(ConversationMember)
        cm2 = aliased(ConversationMember)

        existing = (
            self.db.query(Conversation)
            .join(cm1, and_(cm1.conversation_id == Conversation.id, cm1.user_id == sender_id))
            .join(cm2, and_(cm2.conversation_id == Conversation.id, cm2.user_id == participant_id))
            .filter(Conversation.type == "dm")
            .first()
        )

        if existing:
            return _build_conversation(self.db, existing, sender_id), False

        now = datetime.now(timezone.utc)
        conv = Conversation(
            id=uuid4(),
            type="dm",
            status=ConvStatus.REQUESTED,
            initiator_id=sender_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        self.db.flush()

        self.db.add(ConversationMember(conversation_id=conv.id, user_id=sender_id, joined_at=now))
        self.db.add(ConversationMember(conversation_id=conv.id, user_id=participant_id, joined_at=now))
        self.db.commit()
        self.db.refresh(conv)

        return _build_conversation(self.db, conv, sender_id), True

    def get_conversation(self, conv_id: UUID, requesting_user_id: UUID) -> Optional[ConversationEntity]:
        conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv is None or not self.is_member(conv_id, requesting_user_id):
            return None
        return _build_conversation(self.db, conv, requesting_user_id)

    def get_conversations(self, user_id: UUID, page: int, per_page: int) -> list[ConversationEntity]:
        offset = (page - 1) * per_page
        conv_ids = self.db.query(ConversationMember.conversation_id).filter(ConversationMember.user_id == user_id).subquery()
        convs = (
            self.db.query(Conversation)
            .filter(Conversation.id.in_(conv_ids))
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        return [e for conv in convs if (e := _build_conversation(self.db, conv, user_id))]

    def set_conversation_status(self, conv_id: UUID, status: str) -> ConversationEntity:
        conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
        conv.status = status
        conv.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conv)
        member = self.db.query(ConversationMember).filter(ConversationMember.conversation_id == conv_id).first()
        return _build_conversation(self.db, conv, member.user_id)

    # ── Messages ──────────────────────────────────────────────────────────────

    def save_message(
        self,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_url: Optional[str] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
    ) -> MessageEntity:
        now = datetime.now(timezone.utc)
        msg = Message(
            id=uuid4(),
            context_type=context_type,
            context_id=context_id,
            sender_id=sender_id,
            message_type=message_type,
            body=body,
            media_url=media_url,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            is_deleted=False,
            created_at=now,
        )
        self.db.add(msg)
        self.db.flush()

        if media_url and message_type in ("image", "video", "document", "audio"):
            self.db.add(ChatAttachment(
                id=uuid4(),
                message_id=msg.id,
                context_type=context_type,
                context_id=context_id,
                media_type=message_type,
                media_url=media_url,
                created_at=now,
            ))

        if context_type == "dm":
            self.db.query(Conversation).filter(Conversation.id == context_id).update({"updated_at": now})

        self.db.commit()
        self.db.refresh(msg)
        return _build_message(self.db, msg)

    def get_messages(self, context_type: str, context_id: UUID, before: Optional[datetime], limit: int) -> list[MessageEntity]:
        q = self.db.query(Message).filter(Message.context_type == context_type, Message.context_id == context_id)
        if before is not None:
            q = q.filter(Message.created_at < before)
        rows = q.order_by(Message.created_at.desc()).limit(limit).all()
        return [_build_message(self.db, m) for m in rows]

    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        self.db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        ).update({"last_read_at": datetime.now(timezone.utc)})
        self.db.commit()

    # ── DM membership helpers ─────────────────────────────────────────────────

    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        return (
            self.db.query(ConversationMember)
            .filter(ConversationMember.conversation_id == conv_id, ConversationMember.user_id == user_id)
            .first()
        ) is not None

    def get_other_member_id(self, conv_id: UUID, user_id: UUID) -> Optional[UUID]:
        row = (
            self.db.query(ConversationMember.user_id)
            .filter(ConversationMember.conversation_id == conv_id, ConversationMember.user_id != user_id)
            .first()
        )
        return row[0] if row else None

    def get_conv_send_info(self, conv_id: UUID, sender_id: UUID) -> Optional[ConvSendGuard]:
        """
        Single JOIN query replacing 10 separate queries in the old send path:
          - verifies sender is a member (join cm_sender)
          - fetches the other member's user_id (join cm_receiver)
          - fetches conversation status + initiator_id
          - fetches sender's profile for the message payload
        Returns None if conv doesn't exist or sender is not a member.
        """
        cm_sender   = aliased(ConversationMember)
        cm_receiver = aliased(ConversationMember)

        row = (
            self.db.query(
                Conversation.status,
                Conversation.initiator_id,
                cm_receiver.user_id.label("receiver_id"),
                Profile.id.label("profile_id"),
                Profile.name,
                Profile.is_user_verified,
                Profile.is_business_verified,
            )
            .join(cm_sender,   and_(cm_sender.conversation_id   == Conversation.id, cm_sender.user_id   == sender_id))
            .join(cm_receiver, and_(cm_receiver.conversation_id == Conversation.id, cm_receiver.user_id != sender_id))
            .join(Profile, Profile.users_id == sender_id)
            .filter(Conversation.id == conv_id)
            .first()
        )

        if row is None:
            return None

        return ConvSendGuard(
            status=row.status,
            initiator_id=row.initiator_id,
            receiver_id=row.receiver_id,
            sender_snap=UserSnap(
                user_id=sender_id,
                profile_id=row.profile_id,
                name=row.name,
                is_user_verified=row.is_user_verified,
                is_business_verified=row.is_business_verified,
            ),
        )

    def persist_message(
        self,
        msg_id: UUID,
        sent_at: datetime,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str],
        message_type: str,
        media_url: Optional[str],
        media_metadata: Optional[dict],
        location_lat: Optional[float],
        location_lon: Optional[float],
        reply_to_id: Optional[UUID],
    ) -> None:
        """
        Background INSERT — runs after HTTP response is already sent.
        Creates its own session because the request session is closed by this point.
        """
        from app.core.database.session import SessionLocal
        db = SessionLocal()
        try:
            msg = Message(
                id=msg_id,
                context_type=context_type,
                context_id=context_id,
                sender_id=sender_id,
                message_type=message_type,
                body=body,
                media_url=media_url,
                media_metadata=media_metadata,
                location_lat=location_lat,
                location_lon=location_lon,
                reply_to_id=reply_to_id,
                is_deleted=False,
                created_at=sent_at,
            )
            db.add(msg)
            if context_type == "dm":
                db.query(Conversation).filter(Conversation.id == context_id).update({"updated_at": sent_at})
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ── Group helpers ─────────────────────────────────────────────────────────

    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        row = (
            self.db.query(GroupMember.role)
            .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .first()
        )
        return row[0] if row else None

    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        row = (
            self.db.query(GroupMember.is_frozen)
            .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .first()
        )
        return bool(row[0]) if row else False

    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        row = self.db.query(Group.chat_perm).filter(Group.id == group_id).first()
        return row[0] if row else None

    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        rows = self.db.query(GroupMember.user_id).filter(GroupMember.group_id == group_id).all()
        return [r[0] for r in rows]
