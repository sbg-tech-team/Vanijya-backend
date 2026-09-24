from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from collections import defaultdict

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.chat.data.models import ChatAttachment, Conversation, ConversationMember, Message
from app.modules.chat.domain.interfaces.repository import IChatRepository
from app.modules.chat.domain.value_objects import ConversationStatus
from app.modules.translation.data.models import (
    MessageTranslation,
    ReaderConversationTranslationPref,
)
from app.modules.chat.domain.entities import (
    CallSnap, ChatAttachmentEntity, ChatListItem, ConvSendGuard, ConversationEntity,
    DMLastMessage, DealSnap, GroupConversationEntity, GroupLastMessage, MessageEntity,
    PostSnap, UserSnap, ShareDMItem, ShareGroupItem, ShareRecipientsResult,
)
from app.modules.groups.data.models import Group, GroupDeal, GroupMember, PersonalDeal
from app.modules.post.data.models import Post
from app.modules.profile.data.models import Commodity, Profile
from app.shared.utils.storage import StorageError, path_from_url

_CHAT_STORAGE_BUCKET = os.environ.get("CHAT_STORAGE_BUCKET", "chat")


def _storage_path_for(url: str) -> Optional[str]:
    """Derive the bucket object path from a chat media URL so the object can be
    cleaned up on delete. Returns None for external/foreign URLs."""
    try:
        return path_from_url(_CHAT_STORAGE_BUCKET, url)
    except StorageError:
        return None


# Fixed lookup dicts — roles and post categories are seeded with stable int IDs
ROLE_NAMES = {1: "Trader", 2: "Broker", 3: "Exporter"}
CATEGORY_NAMES = {1: "Market Update", 2: "Knowledge", 3: "Discussion", 4: "Deal/Requirements"}


# ── Private builder helpers ────────────────────────────────────────────────────

def _profile_snap(profile: Profile) -> UserSnap:
    return UserSnap(
        user_id=profile.users_id,
        profile_id=profile.id,
        name=profile.name,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        avatar_url=profile.avatar_url,
        role=ROLE_NAMES.get(profile.role_id, "Trader"),
        is_online=False,  # runtime state — set by ConnectionManager at presentation layer
    )


def _last_message(db: Session, context_id: UUID) -> Optional[DMLastMessage]:
    row = (
        db.query(Message)
        .filter(Message.context_type == "dm", Message.context_id == context_id, Message.is_deleted.is_(False))
        .order_by(Message.sent_at.desc())
        .first()
    )
    if row is None:
        return None
    return DMLastMessage(
        id=row.id,
        body=row.body,
        message_type=row.message_type,
        sender_id=row.sender_id,
        sent_at=row.sent_at,
    )


def _group_last_message(db: Session, group_id: UUID) -> Optional[GroupLastMessage]:
    row = (
        db.query(Message)
        .filter(Message.context_type == "group", Message.context_id == group_id, Message.is_deleted.is_(False))
        .order_by(Message.sent_at.desc())
        .first()
    )
    if row is None:
        return None
    sender = db.query(Profile.name).filter(Profile.users_id == row.sender_id).first()
    return GroupLastMessage(
        id=row.id,
        sender_id=row.sender_id,
        sender_name=sender[0] if sender else "Unknown",
        body=row.body,
        message_type=row.message_type,
        sent_at=row.sent_at,
    )


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
        q = q.filter(Message.sent_at > member.last_read_at)
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


def _build_conversations_batch(
    db: Session, convs: list[Conversation], requesting_user_id: UUID
) -> dict[UUID, ConversationEntity]:
    """Batched form of _build_conversation for a whole page of conversations —
    5 queries total instead of 5 per conversation (members, other-profiles,
    last messages, unread counts, in one round-trip each)."""
    if not convs:
        return {}
    conv_ids = [c.id for c in convs]

    members = (
        db.query(ConversationMember)
        .filter(ConversationMember.conversation_id.in_(conv_ids))
        .all()
    )
    members_by_conv: dict[UUID, list[ConversationMember]] = defaultdict(list)
    for m in members:
        members_by_conv[m.conversation_id].append(m)

    other_member_by_conv: dict[UUID, ConversationMember] = {}
    my_member_by_conv: dict[UUID, ConversationMember] = {}
    other_user_ids: set[UUID] = set()
    for conv_id, mlist in members_by_conv.items():
        other = next((m for m in mlist if m.user_id != requesting_user_id), None)
        mine = next((m for m in mlist if m.user_id == requesting_user_id), None)
        if other is None or mine is None:
            continue
        other_member_by_conv[conv_id] = other
        my_member_by_conv[conv_id] = mine
        other_user_ids.add(other.user_id)

    profiles = db.query(Profile).filter(Profile.users_id.in_(other_user_ids)).all()
    profile_by_user = {p.users_id: p for p in profiles}

    last_msg_rows = (
        db.query(Message)
        .distinct(Message.context_id)
        .filter(
            Message.context_type == "dm",
            Message.context_id.in_(conv_ids),
            Message.is_deleted.is_(False),
        )
        .order_by(Message.context_id, Message.sent_at.desc())
        .all()
    )
    last_msg_by_conv = {
        row.context_id: DMLastMessage(
            id=row.id, body=row.body, message_type=row.message_type,
            sender_id=row.sender_id, sent_at=row.sent_at,
        )
        for row in last_msg_rows
    }

    unread_rows = (
        db.query(Message.context_id, func.count(Message.id))
        .join(
            ConversationMember,
            and_(
                ConversationMember.conversation_id == Message.context_id,
                ConversationMember.user_id == requesting_user_id,
            ),
        )
        .filter(
            Message.context_type == "dm",
            Message.context_id.in_(conv_ids),
            Message.is_deleted.is_(False),
            Message.sender_id != requesting_user_id,
            or_(
                ConversationMember.last_read_at.is_(None),
                Message.sent_at > ConversationMember.last_read_at,
            ),
        )
        .group_by(Message.context_id)
        .all()
    )
    unread_by_conv = {cid: cnt for cid, cnt in unread_rows}

    result: dict[UUID, ConversationEntity] = {}
    for conv in convs:
        other_member = other_member_by_conv.get(conv.id)
        my_member = my_member_by_conv.get(conv.id)
        if other_member is None or my_member is None:
            continue
        other_profile = profile_by_user.get(other_member.user_id)
        if other_profile is None:
            continue
        result[conv.id] = ConversationEntity(
            id=conv.id,
            status=conv.status,
            initiator_id=conv.initiator_id,
            participant=_profile_snap(other_profile),
            last_message=last_msg_by_conv.get(conv.id),
            unread_count=unread_by_conv.get(conv.id, 0),
            is_muted=my_member.is_muted,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        )
    return result


def _group_last_messages_batch(db: Session, group_ids: list[UUID]) -> dict[UUID, GroupLastMessage]:
    """Batched form of _group_last_message for a whole page of groups — 2
    queries total instead of up to 2 per group."""
    if not group_ids:
        return {}
    rows = (
        db.query(Message)
        .distinct(Message.context_id)
        .filter(
            Message.context_type == "group",
            Message.context_id.in_(group_ids),
            Message.is_deleted.is_(False),
        )
        .order_by(Message.context_id, Message.sent_at.desc())
        .all()
    )
    sender_ids = {row.sender_id for row in rows}
    sender_names = {
        p.users_id: p.name
        for p in db.query(Profile.users_id, Profile.name).filter(Profile.users_id.in_(sender_ids))
    }
    return {
        row.context_id: GroupLastMessage(
            id=row.id,
            sender_id=row.sender_id,
            sender_name=sender_names.get(row.sender_id, "Unknown"),
            body=row.body,
            message_type=row.message_type,
            sent_at=row.sent_at,
        )
        for row in rows
    }


def _deal_snap(db: Session, deal_id: UUID) -> Optional[DealSnap]:
    deal = db.query(GroupDeal).filter(GroupDeal.id == deal_id).first()
    if deal is None:
        return None
    commodity = db.query(Commodity).filter(Commodity.id == deal.commodity_id).first()
    return DealSnap(
        deal_id=deal.id,
        title=deal.title,
        commodity_name=commodity.name if commodity else "",
        grain_type=deal.grain_type,
        grain_size=deal.grain_size,
        commodity_quantity=float(deal.commodity_quantity),
        quantity_unit=deal.quantity_unit,
        commodity_price=float(deal.commodity_price),
        price_type=deal.price_type,
        image_urls=deal.image_urls,
        is_closed=deal.is_closed,
        caption=deal.caption,
    )


def _personal_deal_snap(db: Session, personal_deal_id: UUID) -> Optional[DealSnap]:
    deal = db.query(PersonalDeal).filter(PersonalDeal.id == personal_deal_id).first()
    if deal is None:
        return None
    commodity = db.query(Commodity).filter(Commodity.id == deal.commodity_id).first()
    return DealSnap(
        deal_id=deal.id,
        title=deal.title,
        commodity_name=commodity.name if commodity else "",
        grain_type=deal.grain_type,
        grain_size=deal.grain_size,
        commodity_quantity=float(deal.commodity_quantity),
        quantity_unit=deal.quantity_unit,
        commodity_price=float(deal.commodity_price),
        price_type=deal.price_type,
        image_urls=deal.image_urls,
        is_closed=deal.is_closed,
        caption=deal.caption,
    )


def _post_snap(db: Session, post_id: int) -> Optional[PostSnap]:
    post = db.query(Post).filter(Post.id == post_id).first()
    if post is None:
        return None
    author = db.query(Profile).filter(Profile.id == post.profile_id).first()
    return PostSnap(
        post_id=post.id,
        title=post.title,
        image_urls=post.image_urls,
        caption=post.caption,
        category_id=post.category_id,
        category_name=CATEGORY_NAMES.get(post.category_id, ""),
        author_name=author.name if author else "",
    )


def _call_snap(msg: Message) -> Optional["CallSnap"]:
    """Build the call card from the message's media_metadata.

    The calling module writes the payload there rather than adding columns to
    `messages` — a call card is a rendering concern, and the authoritative record
    lives in `calls`.
    """
    meta = msg.media_metadata or {}
    call_id = meta.get("call_id")
    if not call_id:
        return None
    return CallSnap(
        call_id=str(call_id),
        media=meta.get("media", "audio"),
        status=meta.get("status", "ended"),
        end_reason=meta.get("end_reason"),
        duration_seconds=int(meta.get("duration_seconds") or 0),
    )


def _attachment_snap(a: ChatAttachment) -> ChatAttachmentEntity:
    return ChatAttachmentEntity(
        id=a.id,
        message_id=a.message_id,
        context_type=a.context_type,
        context_id=a.context_id,
        media_type=a.media_type,
        media_url=a.media_url,
        storage_path=a.storage_path,
        created_at=a.created_at,
    )


def _build_message(
    db: Session,
    msg: Message,
    delivered: Optional[bool] = None,
    read: Optional[bool] = None,
    attachments: Optional[list[ChatAttachment]] = None,
    translated_text: Optional[str] = None,
    target_lang: Optional[str] = None,
) -> MessageEntity:
    sender_profile = db.query(Profile).filter(Profile.users_id == msg.sender_id).first()
    sender_snap = (
        _profile_snap(sender_profile)
        if sender_profile
        else UserSnap(
            user_id=msg.sender_id, profile_id=0, name="Unknown",
            is_user_verified=False, is_business_verified=False,
            avatar_url=None, role="Trader", is_online=False,
        )
    )
    # attachments=None means "not batched by the caller" — fetch this one
    # message's rows directly. Callers building a list of messages should
    # batch-fetch once and pass the matching slice in to avoid N+1.
    if attachments is None:
        attachments = db.query(ChatAttachment).filter(ChatAttachment.message_id == msg.id).all()
    return MessageEntity(
        id=msg.id,
        context_id=msg.context_id,
        context_type=msg.context_type,
        sender=sender_snap,
        message_type=msg.message_type,
        body=msg.body,
        media_urls=msg.media_urls,
        media_metadata=msg.media_metadata,
        location_lat=msg.location_lat,
        location_lon=msg.location_lon,
        reply_to_id=msg.reply_to_id,
        is_deleted=msg.is_deleted,
        sent_at=msg.sent_at,
        deal=_deal_snap(db, msg.deal_id) if msg.deal_id else (
            _personal_deal_snap(db, msg.personal_deal_id) if msg.personal_deal_id else None
        ),
        post=_post_snap(db, msg.post_id) if msg.post_id else None,
        call=_call_snap(msg) if msg.message_type == "call" else None,
        attachments=[_attachment_snap(a) for a in attachments],
        delivered=delivered,
        read=read,
        translated_text=translated_text,
        target_lang=target_lang,
    )


# ── Repository ─────────────────────────────────────────────────────────────────

class ChatRepository(IChatRepository):

    def __init__(self, db: Session):
        self.db = db

    # ── Conversations ──────────────────────────────────────────────────────────

    def get_conversation(self, conv_id: UUID, requesting_user_id: UUID) -> Optional[ConversationEntity]:
        conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv is None or not self.is_member(conv_id, requesting_user_id):
            return None
        return _build_conversation(self.db, conv, requesting_user_id)

    def get_conversations(self, user_id: UUID, page: int, per_page: int) -> list[ConversationEntity]:
        offset = (page - 1) * per_page
        conv_ids = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user_id)
        convs = (
            self.db.query(Conversation)
            .filter(Conversation.id.in_(conv_ids))
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        by_conv = _build_conversations_batch(self.db, convs, user_id)
        return [by_conv[conv.id] for conv in convs if conv.id in by_conv]

    # ── Messages ───────────────────────────────────────────────────────────────

    def save_message(
        self,
        context_type: str,
        context_id: UUID,
        sender_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_urls: Optional[list[str]] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
        deal_id: Optional[UUID] = None,
        personal_deal_id: Optional[UUID] = None,
        post_id: Optional[int] = None,
        article_id: Optional[UUID] = None,
    ) -> MessageEntity:
        now = datetime.now(timezone.utc)
        msg = Message(
            id=uuid4(),
            context_type=context_type,
            context_id=context_id,
            sender_id=sender_id,
            message_type=message_type,
            body=body,
            media_urls=media_urls,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            deal_id=deal_id,
            personal_deal_id=personal_deal_id,
            post_id=post_id,
            article_id=article_id,
            is_deleted=False,
            sent_at=now,
        )
        self.db.add(msg)
        self.db.flush()

        if media_urls and message_type in ("image", "video", "document", "audio"):
            for url in media_urls:
                self.db.add(ChatAttachment(
                    id=uuid4(),
                    message_id=msg.id,
                    context_type=context_type,
                    context_id=context_id,
                    media_type=message_type,
                    media_url=url,
                    storage_path=_storage_path_for(url),
                    created_at=now,
                ))

        if context_type == "dm":
            self.db.query(Conversation).filter(Conversation.id == context_id).update({"updated_at": now})

        self.db.commit()
        self.db.refresh(msg)
        return _build_message(self.db, msg)

    def reader_continuous_target(self, user_id: UUID, conv_id: UUID) -> Optional[str]:
        """The language to serve translations in, or None if this reader has
        continuous mode off. Owned by the translation module; read here so the
        message list can be served in one round trip instead of the client
        making a second call per conversation."""
        row = self.db.get(ReaderConversationTranslationPref, (user_id, conv_id))
        if row is None or not row.continuous_enabled:
            return None
        return row.target_lang

    def get_messages(
        self,
        context_type: str,
        context_id: UUID,
        before: Optional[datetime],
        limit: int,
        translate_to: Optional[str] = None,
    ) -> list[MessageEntity]:
        q = self.db.query(Message).filter(
            Message.context_type == context_type,
            Message.context_id == context_id,
            Message.is_deleted.is_(False),
        )
        if before is not None:
            q = q.filter(Message.sent_at < before)
        rows = q.order_by(Message.sent_at.desc()).limit(limit).all()

        # Batch-fetch attachments for the whole page in one query to avoid N+1.
        message_ids = [m.id for m in rows]
        attach_map: dict[UUID, list[ChatAttachment]] = {}
        if message_ids:
            for a in self.db.query(ChatAttachment).filter(ChatAttachment.message_id.in_(message_ids)).all():
                attach_map.setdefault(a.message_id, []).append(a)

        # One query for the whole page, same reason as attachments above.
        trans_map: dict[UUID, str] = {}
        if translate_to and message_ids:
            trans_map = {
                t.message_id: t.translated_text
                for t in self.db.query(MessageTranslation).filter(
                    MessageTranslation.message_id.in_(message_ids),
                    MessageTranslation.target_lang == translate_to,
                ).all()
            }

        def _tr(m):
            return {"translated_text": trans_map.get(m.id),
                    "target_lang": translate_to if trans_map.get(m.id) else None}

        if context_type != "dm":
            # Group receipts aren't tracked yet (no per-member cursors on group_members).
            return [
                _build_message(self.db, m, attachments=attach_map.get(m.id, []), **_tr(m))
                for m in rows
            ]

        # DM: derive each message's delivered/read tick from the *peer's* cursors.
        # peer = the member who did not send the message (exactly one in a DM).
        members = (
            self.db.query(ConversationMember.user_id, ConversationMember.last_delivered_at, ConversationMember.last_read_at)
            .filter(ConversationMember.conversation_id == context_id)
            .all()
        )
        cursors = {m.user_id: (m.last_delivered_at, m.last_read_at) for m in members}

        out: list[MessageEntity] = []
        for m in rows:
            peer = next((c for uid, c in cursors.items() if uid != m.sender_id), (None, None))
            last_delivered_at, last_read_at = peer
            delivered = last_delivered_at is not None and last_delivered_at >= m.sent_at
            read = last_read_at is not None and last_read_at >= m.sent_at
            out.append(_build_message(
                self.db, m, delivered=delivered, read=read,
                attachments=attach_map.get(m.id, []), **_tr(m),
            ))
        return out

    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        self.db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        ).update({"last_read_at": datetime.now(timezone.utc)})
        self.db.commit()

    def soft_delete_message(self, message_id: UUID, user_id: UUID) -> Optional[dict]:
        """Flip is_deleted for a message the caller owns. Returns context + the
        storage object paths to clean up, or None if not found / not owner / already gone."""
        msg = self.db.query(Message).filter(Message.id == message_id).first()
        if msg is None or msg.sender_id != user_id or msg.is_deleted:
            return None

        paths = [
            a.storage_path
            for a in self.db.query(ChatAttachment).filter(ChatAttachment.message_id == message_id).all()
            if a.storage_path
        ]
        # Fall back to deriving paths from media_urls for rows saved before storage_path existed.
        if not paths and msg.media_urls:
            paths = [p for url in msg.media_urls if (p := _storage_path_for(url))]

        context_type, context_id = msg.context_type, msg.context_id
        msg.is_deleted = True
        self.db.commit()

        return {
            "message_id": message_id,
            "context_type": context_type,
            "context_id": context_id,
            "storage_paths": paths,
        }

    # ── DM membership helpers ──────────────────────────────────────────────────

    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        return (
            self.db.query(ConversationMember)
            .filter(ConversationMember.conversation_id == conv_id, ConversationMember.user_id == user_id)
            .first()
        ) is not None

    def get_conv_send_info(self, conv_id: UUID, sender_id: UUID) -> Optional[ConvSendGuard]:
        """Single JOIN replacing multiple queries: verifies membership, fetches status + initiator + receiver + sender profile."""
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
                Profile.avatar_url,
                Profile.role_id,
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
                avatar_url=row.avatar_url,
                role=ROLE_NAMES.get(row.role_id, "Trader"),
                is_online=True,  # sender is actively sending
            ),
        )
    
    def create_personal_deal(
        self,
        conv_id: UUID,
        sender_id: UUID,
        commodity_id: int,
        title: str,
        caption: str,
        grain_type: str,
        grain_size: str,
        commodity_quantity: float,
        quantity_unit: str,
        commodity_price: float,
        price_type: str,
        image_urls: Optional[list[str]],
    ) -> MessageEntity:
        from app.modules.groups.data.models import PersonalDeal
        now = datetime.now(timezone.utc)
        deal = PersonalDeal(
            id=uuid4(),
            conversation_id=conv_id,
            posted_by=sender_id,
            commodity_id=commodity_id,
            title=title,
            caption=caption,
            grain_type=grain_type,
            grain_size=grain_size,
            commodity_quantity=commodity_quantity,
            quantity_unit=quantity_unit,
            commodity_price=commodity_price,
            price_type=price_type,
            image_urls=image_urls,
        )
        self.db.add(deal)
        self.db.flush()   # get deal.id

        return self.save_message(
            context_type="dm",
            context_id=conv_id,
            sender_id=sender_id,
            message_type="deal",
            personal_deal_id=deal.id,
        )

    


    
    

    # ── Post helpers ──────────────────────────────────────────────────────────

    def post_exists(self, post_id: int) -> bool:
        return self.db.query(Post.id).filter(Post.id == post_id).first() is not None

    # ── Share recipients ───────────────────────────────────────────────────────

    def get_share_recipients(self, user_id: UUID) -> ShareRecipientsResult:
        """
        Two queries — no N+1.
          dm_connections : active DMs sorted by most recent activity
          groups         : groups user belongs to (unfrozen), sorted by name
        """
        cm_me = aliased(ConversationMember)
        cm_other = aliased(ConversationMember)

        dm_rows = (
            self.db.query(
                Conversation.id.label("conv_id"),
                Conversation.updated_at.label("last_message_at"),
                cm_other.user_id.label("other_user_id"),
                Profile.id.label("profile_id"),
                Profile.name,
                Profile.avatar_url,
            )
            .join(cm_me,   and_(cm_me.conversation_id   == Conversation.id, cm_me.user_id   == user_id))
            .join(cm_other, and_(cm_other.conversation_id == Conversation.id, cm_other.user_id != user_id))
            .join(Profile, Profile.users_id == cm_other.user_id)
            .filter(Conversation.status == ConversationStatus.ACTIVE)
            .order_by(Conversation.updated_at.desc())
            .all()
        )

        group_rows = (
            self.db.query(
                Group.id.label("group_id"),
                Group.name,
                Group.image_url,
                Group.member_count,
                Group.chat_perm,
                GroupMember.role,
            )
            .join(GroupMember, and_(
                GroupMember.group_id == Group.id,
                GroupMember.user_id  == user_id,
                GroupMember.is_frozen == False,
            ))
            .order_by(Group.name)
            .all()
        )

        return ShareRecipientsResult(
            dm_connections=[
                ShareDMItem(
                    conversation_id=row.conv_id,
                    profile_id=row.profile_id,
                    user_id=row.other_user_id,
                    name=row.name,
                    avatar_url=row.avatar_url,
                    last_message_at=row.last_message_at,
                )
                for row in dm_rows
            ],
            groups=[
                ShareGroupItem(
                    group_id=row.group_id,
                    name=row.name,
                    avatar_url=row.image_url,
                    member_count=row.member_count,
                    can_send=row.chat_perm == "all_members" or row.role == "admin",
                )
                for row in group_rows
            ],
        )

    # ── Socket-handler support (connection_manager) ─────────────────────────────

    def is_group_member(self, group_id: UUID, user_id: UUID) -> bool:
        return self.db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        ).first() is not None

    def dm_member_ids(self, conv_id: UUID) -> list[str]:
        rows = (
            self.db.query(ConversationMember.user_id)
            .filter(ConversationMember.conversation_id == conv_id)
            .all()
        )
        return [str(r[0]) for r in rows]

    def mark_delivered_and_get_peer(self, conv_id: UUID, user_id: UUID, now):
        """Stamp last_delivered_at for this member and return the other member's id.

        Returns None when the caller is not a member (nothing is committed).
        """
        updated = (
            self.db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id == user_id,
            )
            .update({"last_delivered_at": now}, synchronize_session=False)
        )
        if not updated:
            self.db.rollback()
            return None
        peer = (
            self.db.query(ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id != user_id,
            )
            .first()
        )
        self.db.commit()
        return peer

    def get_or_create_dm(self, user_id: UUID, target_user_id: UUID) -> dict:
        """Get existing DM between user and target, or create a new ACTIVE one. Idempotent."""
        cm_a = aliased(ConversationMember)
        cm_b = aliased(ConversationMember)
        conv = (
            self.db.query(Conversation)
            .join(cm_a, and_(cm_a.conversation_id == Conversation.id, cm_a.user_id == user_id))
            .join(cm_b, and_(cm_b.conversation_id == Conversation.id, cm_b.user_id == target_user_id))
            .filter(Conversation.type == "dm")
            .first()
        )

        now = datetime.now(timezone.utc)
        created = False
        if conv is None:
            conv = Conversation(
                id=uuid4(), type="dm", status=ConversationStatus.ACTIVE,
                initiator_id=user_id, created_at=now, updated_at=now,
            )
            self.db.add(conv)
            self.db.flush()
            self.db.add(ConversationMember(conversation_id=conv.id, user_id=user_id, joined_at=now))
            self.db.add(ConversationMember(conversation_id=conv.id, user_id=target_user_id, joined_at=now))
            self.db.commit()
            created = True

        return {"conversation_id": conv.id, "status": conv.status, "created": created}

    # ── Group conversations ─────────────────────────────────────────────────────

    def get_group_conversations(self, user_id: UUID) -> list[GroupConversationEntity]:
        """Every group the user belongs to, built as a chat-list entity.

        Note: groups have no per-user read tracking yet (GroupMember has no
        last_read_at), so unread_count is 0 until that column exists. updated_at
        reflects the last group message so the unified list can sort on it."""
        rows = (
            self.db.query(Group, GroupMember.is_muted)
            .join(GroupMember, and_(GroupMember.group_id == Group.id, GroupMember.user_id == user_id))
            .all()
        )
        last_by_group = _group_last_messages_batch(self.db, [group.id for group, _ in rows])
        result = []
        for group, is_muted in rows:
            last = last_by_group.get(group.id)
            result.append(GroupConversationEntity(
                id=group.id,
                group_name=group.name,
                group_avatar=group.image_url,
                member_count=group.member_count,
                last_message=last,
                unread_count=0,
                is_muted=bool(is_muted),
                created_at=group.created_at,
                updated_at=last.sent_at if last else group.created_at,
            ))
        return result

    # ── Unified chat list ───────────────────────────────────────────────────────

    def get_all_chats(self, user_id: UUID, page: int, per_page: int) -> list[ChatListItem]:
        """DMs + groups merged into one list, newest activity first.

        A correct global sort needs every chat gathered before slicing, so this
        builds all of the user's DMs and groups, sorts by last activity, then
        paginates in memory (bounded per user — fine for a chat list)."""
        conv_ids = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user_id)
        convs = self.db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all()
        dms_by_conv = _build_conversations_batch(self.db, convs, user_id)

        items: list[ChatListItem] = []
        for conv in convs:
            dm = dms_by_conv.get(conv.id)
            if dm is None:
                continue
            last_activity = dm.last_message.sent_at if dm.last_message else dm.updated_at
            items.append(ChatListItem(type="dm", last_activity=last_activity, dm=dm))

        for group in self.get_group_conversations(user_id):
            last_activity = group.last_message.sent_at if group.last_message else group.updated_at
            items.append(ChatListItem(type="group", last_activity=last_activity, group=group))

        # Strip tzinfo for the comparison so naive (DB-read) and aware datetimes
        # never collide; None sinks to the bottom.
        def _key(item: ChatListItem):
            dt = item.last_activity
            return dt.replace(tzinfo=None) if dt else datetime.min

        items.sort(key=_key, reverse=True)

        offset = (page - 1) * per_page
        return items[offset:offset + per_page]

    # ── Group helpers ──────────────────────────────────────────────────────────

    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        row = self.db.query(GroupMember.role).filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id).first()
        return row[0] if row else None

    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        row = self.db.query(GroupMember.is_frozen).filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id).first()
        return bool(row[0]) if row else False

    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        row = self.db.query(Group.chat_perm).filter(Group.id == group_id).first()
        return row[0] if row else None

    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        rows = self.db.query(GroupMember.user_id).filter(GroupMember.group_id == group_id).all()
        return [r[0] for r in rows]
