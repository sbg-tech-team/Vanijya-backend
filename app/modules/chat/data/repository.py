from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.chat.data.models import ChatAttachment, Conversation, ConversationMember, Message
from app.modules.chat.domain.entities import (
    ChatListItem, ConvSendGuard, ConvStatus, ConversationEntity, DMLastMessage,
    DealSnap, GroupConversationEntity, GroupLastMessage, MessageEntity, NewsArticleSnap,
    PostSnap, UserSnap, ShareDMItem, ShareGroupItem, ShareRecipientsResult,
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


# ── Snapshot constructors (pure: ORM object → entity, no queries) ────────────────
# Shared by both the single-message send path (_deal_snap etc.) and the batched
# read path (_*_snaps_bulk), so the two never drift.

def _deal_snap_obj(deal, commodity_name: str) -> DealSnap:
    # GroupDeal and PersonalDeal share the same DealSnap shape/attributes.
    return DealSnap(
        deal_id=deal.id,
        title=deal.title,
        commodity_name=commodity_name,
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


def _post_snap_obj(post: Post, author_name: str) -> PostSnap:
    return PostSnap(
        post_id=post.id,
        title=post.title,
        image_urls=post.image_urls,
        caption=post.caption,
        category_id=post.category_id,
        category_name=CATEGORY_NAMES.get(post.category_id, ""),
        author_name=author_name,
    )


def _news_article_snap_obj(article, enriched) -> NewsArticleSnap:
    first_bullet: Optional[str] = None
    if enriched and enriched.summary_bullets:
        bullets = enriched.summary_bullets
        first_bullet = bullets[0] if isinstance(bullets, list) and bullets else None
    return NewsArticleSnap(
        article_id=article.id,
        title=article.title,
        image_url=article.image_url,
        source_name=article.source_name,
        primary_factor=enriched.primary_factor if enriched else None,
        impact_direction=enriched.impact_direction if enriched else None,
        impact_score=enriched.impact_score if enriched else None,
        first_bullet=first_bullet,
    )


# ── Single-row snap helpers (used by the send path — one message at a time) ──────

def _build_conversations(
    db: Session, convs: list[Conversation], requesting_user_id: UUID
) -> list[ConversationEntity]:
    """Batch-build a page of DM conversations with a fixed number of queries (no
    per-conversation N+1): members, participant profiles, last messages and unread
    counts are each fetched in a single query across the whole page."""
    if not convs:
        return []
    conv_ids = [c.id for c in convs]

    # Members for all conversations — one query, grouped by conversation.
    members_by_conv: dict = {}
    for m in db.query(ConversationMember).filter(ConversationMember.conversation_id.in_(conv_ids)).all():
        members_by_conv.setdefault(m.conversation_id, []).append(m)

    # Other participants' profiles — one query.
    other_user_ids = set()
    for c in convs:
        other = next((m for m in members_by_conv.get(c.id, []) if m.user_id != requesting_user_id), None)
        if other:
            other_user_ids.add(other.user_id)
    profile_by_user = (
        {p.users_id: p for p in db.query(Profile).filter(Profile.users_id.in_(other_user_ids)).all()}
        if other_user_ids else {}
    )

    # Last message per conversation — one query (DISTINCT ON keeps the newest row).
    last_by_conv: dict = {}
    last_rows = (
        db.query(Message)
        .filter(Message.context_type == "dm", Message.context_id.in_(conv_ids), Message.is_deleted.is_(False))
        .order_by(Message.context_id, Message.sent_at.desc())
        .distinct(Message.context_id)
        .all()
    )
    for row in last_rows:
        last_by_conv[row.context_id] = DMLastMessage(
            id=row.id, body=row.body, message_type=row.message_type,
            sender_id=row.sender_id, sent_at=row.sent_at,
        )

    # Unread count per conversation — one query. Counts peer messages newer than my
    # last_read_at (or all peer messages when I've never read), mirroring _unread_count.
    my_members = (
        select(ConversationMember.conversation_id, ConversationMember.last_read_at)
        .where(
            ConversationMember.user_id == requesting_user_id,
            ConversationMember.conversation_id.in_(conv_ids),
        )
        .subquery()
    )
    unread_by_conv = {
        cid: cnt
        for cid, cnt in (
            db.query(Message.context_id, func.count(Message.id))
            .join(my_members, my_members.c.conversation_id == Message.context_id)
            .filter(
                Message.context_type == "dm",
                Message.is_deleted.is_(False),
                Message.sender_id != requesting_user_id,
                or_(my_members.c.last_read_at.is_(None), Message.sent_at > my_members.c.last_read_at),
            )
            .group_by(Message.context_id)
            .all()
        )
    }

    out: list[ConversationEntity] = []
    for conv in convs:
        members = members_by_conv.get(conv.id, [])
        other_member = next((m for m in members if m.user_id != requesting_user_id), None)
        my_member = next((m for m in members if m.user_id == requesting_user_id), None)
        if other_member is None or my_member is None:
            continue
        other_profile = profile_by_user.get(other_member.user_id)
        if other_profile is None:
            continue
        out.append(ConversationEntity(
            id=conv.id,
            status=conv.status,
            initiator_id=conv.initiator_id,
            participant=_profile_snap(other_profile),
            last_message=last_by_conv.get(conv.id),
            unread_count=unread_by_conv.get(conv.id, 0),
            is_muted=my_member.is_muted,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        ))
    return out


def _deal_snap(db: Session, deal_id: UUID) -> Optional[DealSnap]:
    deal = db.query(GroupDeal).filter(GroupDeal.id == deal_id).first()
    if deal is None:
        return None
    commodity = db.query(Commodity).filter(Commodity.id == deal.commodity_id).first()
    return _deal_snap_obj(deal, commodity.name if commodity else "")


def _personal_deal_snap(db: Session, personal_deal_id: UUID) -> Optional[DealSnap]:
    deal = db.query(PersonalDeal).filter(PersonalDeal.id == personal_deal_id).first()
    if deal is None:
        return None
    commodity = db.query(Commodity).filter(Commodity.id == deal.commodity_id).first()
    return _deal_snap_obj(deal, commodity.name if commodity else "")


def _post_snap(db: Session, post_id: int) -> Optional[PostSnap]:
    post = db.query(Post).filter(Post.id == post_id).first()
    if post is None:
        return None
    author = db.query(Profile).filter(Profile.id == post.profile_id).first()
    return _post_snap_obj(post, author.name if author else "")


def _news_article_snap(db: Session, article_id: UUID) -> Optional[NewsArticleSnap]:
    from app.modules.news_new.ingestion.models import RawArticle
    from app.modules.news_new.intelligence.models import EnrichedArticle
    article = db.query(RawArticle).filter(RawArticle.id == article_id).first()
    if article is None:
        return None
    enriched = db.query(EnrichedArticle).filter(EnrichedArticle.raw_article_id == article_id).first()
    return _news_article_snap_obj(article, enriched)


# ── Bulk snap helpers (used by the read path — one query per entity type) ────────

def _deal_snaps_bulk(db: Session, deal_ids: set) -> dict:
    if not deal_ids:
        return {}
    deals = db.query(GroupDeal).filter(GroupDeal.id.in_(deal_ids)).all()
    commodity_ids = {d.commodity_id for d in deals}
    names = (
        {c.id: c.name for c in db.query(Commodity).filter(Commodity.id.in_(commodity_ids)).all()}
        if commodity_ids else {}
    )
    return {d.id: _deal_snap_obj(d, names.get(d.commodity_id, "")) for d in deals}


def _personal_deal_snaps_bulk(db: Session, deal_ids: set) -> dict:
    if not deal_ids:
        return {}
    deals = db.query(PersonalDeal).filter(PersonalDeal.id.in_(deal_ids)).all()
    commodity_ids = {d.commodity_id for d in deals}
    names = (
        {c.id: c.name for c in db.query(Commodity).filter(Commodity.id.in_(commodity_ids)).all()}
        if commodity_ids else {}
    )
    return {d.id: _deal_snap_obj(d, names.get(d.commodity_id, "")) for d in deals}


def _post_snaps_bulk(db: Session, post_ids: set) -> dict:
    if not post_ids:
        return {}
    posts = db.query(Post).filter(Post.id.in_(post_ids)).all()
    author_ids = {p.profile_id for p in posts}
    names = (
        {p.id: p.name for p in db.query(Profile).filter(Profile.id.in_(author_ids)).all()}
        if author_ids else {}
    )
    return {p.id: _post_snap_obj(p, names.get(p.profile_id, "")) for p in posts}


def _news_article_snaps_bulk(db: Session, article_ids: set) -> dict:
    if not article_ids:
        return {}
    from app.modules.news_new.ingestion.models import RawArticle
    from app.modules.news_new.intelligence.models import EnrichedArticle
    articles = db.query(RawArticle).filter(RawArticle.id.in_(article_ids)).all()
    enriched_by_raw = {
        e.raw_article_id: e
        for e in db.query(EnrichedArticle).filter(EnrichedArticle.raw_article_id.in_(article_ids)).all()
    }
    return {a.id: _news_article_snap_obj(a, enriched_by_raw.get(a.id)) for a in articles}


def _build_message(
    db: Session,
    msg: Message,
    delivered: Optional[bool] = None,
    read: Optional[bool] = None,
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
        news_article=_news_article_snap(db, msg.article_id) if msg.article_id else None,
        delivered=delivered,
        read=read,
    )


def _build_messages(
    db: Session,
    rows: list[Message],
    receipts: Optional[dict] = None,
) -> list[MessageEntity]:
    """Batch-build a page of messages with a fixed number of queries (no per-row
    N+1). `receipts` maps msg.id -> (delivered, read); messages absent from it get
    (None, None)."""
    if not rows:
        return []
    receipts = receipts or {}

    # Senders: one query for all distinct senders in the page.
    sender_ids = {m.sender_id for m in rows}
    profile_by_user = {
        p.users_id: p for p in db.query(Profile).filter(Profile.users_id.in_(sender_ids)).all()
    }

    # Referenced entities: one query per type for the ids actually present.
    deal_snaps = _deal_snaps_bulk(db, {m.deal_id for m in rows if m.deal_id})
    personal_deal_snaps = _personal_deal_snaps_bulk(db, {m.personal_deal_id for m in rows if m.personal_deal_id})
    post_snaps = _post_snaps_bulk(db, {m.post_id for m in rows if m.post_id})
    article_snaps = _news_article_snaps_bulk(db, {m.article_id for m in rows if m.article_id})

    out: list[MessageEntity] = []
    for msg in rows:
        prof = profile_by_user.get(msg.sender_id)
        sender_snap = (
            _profile_snap(prof)
            if prof
            else UserSnap(
                user_id=msg.sender_id, profile_id=0, name="Unknown",
                is_user_verified=False, is_business_verified=False,
                avatar_url=None, role="Trader", is_online=False,
            )
        )
        if msg.deal_id:
            deal = deal_snaps.get(msg.deal_id)
        elif msg.personal_deal_id:
            deal = personal_deal_snaps.get(msg.personal_deal_id)
        else:
            deal = None
        delivered, read = receipts.get(msg.id, (None, None))
        out.append(MessageEntity(
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
            deal=deal,
            post=post_snaps.get(msg.post_id) if msg.post_id else None,
            news_article=article_snaps.get(msg.article_id) if msg.article_id else None,
            delivered=delivered,
            read=read,
        ))
    return out


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
        return _build_conversations(self.db, convs, user_id)

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

    def get_messages(self, context_type: str, context_id: UUID, before: Optional[datetime], limit: int) -> list[MessageEntity]:
        q = self.db.query(Message).filter(
            Message.context_type == context_type,
            Message.context_id == context_id,
            Message.is_deleted.is_(False),
        )
        if before is not None:
            q = q.filter(Message.sent_at < before)
        rows = q.order_by(Message.sent_at.desc()).limit(limit).all()

        if context_type != "dm":
            # Group receipts aren't tracked yet (no per-member cursors on group_members).
            return _build_messages(self.db, rows)

        # DM: derive each message's delivered/read tick from the *peer's* cursors.
        # peer = the member who did not send the message (exactly one in a DM).
        members = (
            self.db.query(ConversationMember.user_id, ConversationMember.last_delivered_at, ConversationMember.last_read_at)
            .filter(ConversationMember.conversation_id == context_id)
            .all()
        )
        cursors = {m.user_id: (m.last_delivered_at, m.last_read_at) for m in members}

        receipts: dict = {}
        for m in rows:
            peer = next((c for uid, c in cursors.items() if uid != m.sender_id), (None, None))
            last_delivered_at, last_read_at = peer
            delivered = last_delivered_at is not None and last_delivered_at >= m.sent_at
            read = last_read_at is not None and last_read_at >= m.sent_at
            receipts[m.id] = (delivered, read)
        return _build_messages(self.db, rows, receipts)

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

    # def get_share_recipients(self, user_id: UUID) -> ShareRecipientsResult:
    #     """
    #     Two queries — no N+1.
    #       dm_connections : active DMs sorted by most recent activity
    #       groups         : groups user belongs to (unfrozen), sorted by name
    #     """
    #     cm_me = aliased(ConversationMember)
    #     cm_other = aliased(ConversationMember)
    #
    #     dm_rows = (
    #         self.db.query(
    #             Conversation.id.label("conv_id"),
    #             Conversation.updated_at.label("last_message_at"),
    #             cm_other.user_id.label("other_user_id"),
    #             Profile.id.label("profile_id"),
    #             Profile.name,
    #             Profile.avatar_url,
    #         )
    #         .join(cm_me,   and_(cm_me.conversation_id   == Conversation.id, cm_me.user_id   == user_id))
    #         .join(cm_other, and_(cm_other.conversation_id == Conversation.id, cm_other.user_id != user_id))
    #         .join(Profile, Profile.users_id == cm_other.user_id)
    #         .filter(Conversation.status == ConvStatus.ACTIVE)
    #         .order_by(Conversation.updated_at.desc())
    #         .all()
    #     )
    #
    #     group_rows = (
    #         self.db.query(
    #             Group.id.label("group_id"),
    #             Group.name,
    #             Group.image_url,
    #             Group.member_count,
    #             Group.chat_perm,
    #             GroupMember.role,
    #         )
    #         .join(GroupMember, and_(
    #             GroupMember.group_id == Group.id,
    #             GroupMember.user_id  == user_id,
    #             GroupMember.is_frozen == False,
    #         ))
    #         .order_by(Group.name)
    #         .all()
    #     )
    #
    #     return ShareRecipientsResult(
    #         dm_connections=[
    #             ShareDMItem(
    #                 conversation_id=row.conv_id,
    #                 profile_id=row.profile_id,
    #                 user_id=row.other_user_id,
    #                 name=row.name,
    #                 avatar_url=row.avatar_url,
    #                 last_message_at=row.last_message_at,
    #             )
    #             for row in dm_rows
    #         ],
    #         groups=[
    #             ShareGroupItem(
    #                 group_id=row.group_id,
    #                 name=row.name,
    #                 avatar_url=row.image_url,
    #                 member_count=row.member_count,
    #                 can_send=row.chat_perm == "all_members" or row.role == "admin",
    #             )
    #             for row in group_rows
    #         ],
    #     )

    def get_share_recipients(self, user_id: UUID) -> ShareRecipientsResult:
        """
        DM source: everyone the user follows, left-joined with existing DM conversations.
          - conversation_id is None if no DM exists yet (frontend calls POST /chat/conversations first).
          - Sorted: most recently active DM first, then alphabetically by name.
        Groups: unfrozen memberships, sorted by name.
        """
        from app.modules.connections.models import UserConnection

        _cm_me = aliased(ConversationMember)
        _cm_other = aliased(ConversationMember)

        my_dm_convs = (
            self.db.query(
                _cm_me.conversation_id.label("conv_id"),
                _cm_other.user_id.label("other_user_id"),
                Conversation.updated_at,
            )
            .join(Conversation, and_(
                Conversation.id == _cm_me.conversation_id,
                Conversation.type == "dm",
            ))
            .join(_cm_other, and_(
                _cm_other.conversation_id == _cm_me.conversation_id,
                _cm_other.user_id != user_id,
            ))
            .filter(_cm_me.user_id == user_id)
            .subquery()
        )

        dm_rows = (
            self.db.query(
                UserConnection.following_id.label("other_user_id"),
                Profile.id.label("profile_id"),
                Profile.name,
                Profile.avatar_url,
                my_dm_convs.c.conv_id.label("conv_id"),
                my_dm_convs.c.updated_at.label("last_message_at"),
            )
            .join(Profile, Profile.users_id == UserConnection.following_id)
            .outerjoin(my_dm_convs, my_dm_convs.c.other_user_id == UserConnection.following_id)
            .filter(UserConnection.follower_id == user_id)
            .order_by(my_dm_convs.c.updated_at.desc(), Profile.name.asc())
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

    def get_or_create_dm(self, user_id: UUID, target_user_id: UUID) -> dict:
        """Get existing DM between user and target, or create a new ACTIVE one. Idempotent."""
        from uuid import uuid4 as _uuid4
        from app.modules.chat.domain.entities import ConvStatus

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
                id=_uuid4(), type="dm", status=ConvStatus.ACTIVE,
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
