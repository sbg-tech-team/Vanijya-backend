from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.chat.data.models import ChatAttachment, Conversation, ConversationMember, Message
from app.modules.chat.domain.entities import (
    ChatListItem, ConvSendGuard, ConvStatus, ConversationEntity, DMLastMessage,
    DealSnap, GroupConversationEntity, GroupLastMessage, MessageEntity, PostSnap, UserSnap,
    ShareDMItem, ShareGroupItem, ShareRecipientsResult,
)
from app.modules.groups.models import Group, GroupDeal, GroupMember, PersonalDeal
from app.modules.post.models import Post
from app.modules.profile.models import Commodity, Profile
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


def _build_message(db: Session, msg: Message) -> MessageEntity:
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
    )


# ── Repository ─────────────────────────────────────────────────────────────────

class ChatRepository:

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
        return [e for conv in convs if (e := _build_conversation(self.db, conv, user_id))]

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

    def get_messages(self, context_type: str, context_id: UUID, before: Optional[datetime], limit: int) -> list[MessageEntity]:
        q = self.db.query(Message).filter(
            Message.context_type == context_type,
            Message.context_id == context_id,
            Message.is_deleted.is_(False),
        )
        if before is not None:
            q = q.filter(Message.sent_at < before)
        rows = q.order_by(Message.sent_at.desc()).limit(limit).all()
        return [_build_message(self.db, m) for m in rows]

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
        from app.modules.groups.models import PersonalDeal
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
            .filter(Conversation.status == ConvStatus.ACTIVE)
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
        result = []
        for group, is_muted in rows:
            last = _group_last_message(self.db, group.id)
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

        items: list[ChatListItem] = []
        for conv in convs:
            dm = _build_conversation(self.db, conv, user_id)
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
