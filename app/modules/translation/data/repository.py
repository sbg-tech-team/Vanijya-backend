from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.chat.data.models import ConversationMember, Message
from app.modules.groups.data.models import GroupMember
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.translation.data.models import (
    ConversationTranslationContext,
    MessageTranslation,
    ReaderConversationTranslationPref,
    ReaderTranslationDefault,
)
from app.modules.translation.domain.entities import (
    ContextMessage,
    ContextSnapshot,
    ReaderConversationPrefs,
    TranslatableMessage,
)
from app.modules.translation.domain.interfaces.context_store import IContextStore
from app.modules.translation.domain.interfaces.repository import ITranslationRepository


class TranslationRepository(ITranslationRepository, IContextStore):
    """Single Postgres-backed class for everything this module reads/writes —
    matches the rest of this codebase's one-repository-per-module convention.
    Message reads go straight to chat's own `messages` table (read-only; chat
    remains the writer), the same way chat's own repository reads directly
    from groups/post/profile models."""

    def __init__(self, db: Session, refresh_every_n_messages: int, refresh_ttl: timedelta):
        self.db = db
        self._k = refresh_every_n_messages
        self._ttl = refresh_ttl

    # ── message history ───────────────────────────────────────────────────────

    def get_message(self, message_id: UUID) -> Optional[TranslatableMessage]:
        row = self.db.get(Message, message_id)
        if row is None or row.is_deleted:
            return None
        return TranslatableMessage(
            id=row.id,
            context_type=row.context_type,
            context_id=row.context_id,
            sender_id=row.sender_id,
            body=row.body,
        )

    def reader_is_member(self, reader_id: UUID, context_type: str, context_id: UUID) -> bool:
        if context_type == "dm":
            model, col = ConversationMember, ConversationMember.conversation_id
        elif context_type == "group":
            model, col = GroupMember, GroupMember.group_id
        else:
            return False
        return (
            self.db.query(model.user_id)
            .filter(col == context_id, model.user_id == reader_id)
            .first()
        ) is not None

    def get_preceding_messages(
        self, context_type: str, context_id: UUID, before_message_id: UUID, limit: int
    ) -> list[ContextMessage]:
        before = self.db.get(Message, before_message_id)
        if before is None:
            return []
        rows = (
            self.db.query(Message)
            .filter(
                Message.context_type == context_type,
                Message.context_id == context_id,
                Message.sent_at < before.sent_at,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.sent_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [ContextMessage(id=r.id, body=r.body, sent_at=r.sent_at) for r in rows]

    def save_translation(self, message_id: UUID, target_lang: str, translated_text: str) -> None:
        """Idempotent: two readers asking for the same language race here, and
        the second must not 409 on the primary key."""
        self.db.execute(
            pg_insert(MessageTranslation)
            .values(message_id=message_id, target_lang=target_lang,
                    translated_text=translated_text)
            .on_conflict_do_update(
                index_elements=["message_id", "target_lang"],
                set_={"translated_text": translated_text},
            )
        )
        self.db.commit()

    def untranslated_for_continuous_readers(
        self, since: datetime, limit: int
    ) -> list[tuple[UUID, UUID]]:
        """(receiver_id, message_id) pairs a continuous reader is still owed.

        The live translation runs in a BackgroundTask, which dies with the
        process: a deploy, an OOM or a crash mid-flight loses it silently and
        nothing ever retries. Persisting translations made the gap queryable —
        a message with no row for its reader's language is exactly a miss.

        Only messages the reader did not send, only DMs, only conversations
        where continuous is on, newest first.
        """
        rows = self.db.execute(
            text("""
                SELECT p.user_id, m.id
                FROM messages m
                JOIN reader_conversation_translation_prefs p
                  ON p.conversation_id = m.context_id
                 AND p.continuous_enabled = true
                 AND p.user_id <> m.sender_id
                LEFT JOIN message_translations t
                  ON t.message_id = m.id
                 AND t.target_lang IS NOT DISTINCT FROM p.target_lang
                WHERE m.context_type = 'dm'
                  AND m.is_deleted = false
                  AND m.body IS NOT NULL
                  AND m.sent_at >= :since
                  AND t.message_id IS NULL
                ORDER BY m.sent_at DESC
                LIMIT :limit
            """),
            {"since": since, "limit": limit},
        ).all()
        return [(r[0], r[1]) for r in rows]

    # ── rolling context (IContextStore) ───────────────────────────────────────

    def get_context(self, context_type: str, context_id: UUID) -> ContextSnapshot:
        row = self.db.get(ConversationTranslationContext, (context_type, context_id))
        if row is None:
            return ContextSnapshot(summary=None, due_for_refresh=True)

        row.messages_since_refresh += 1
        self.db.commit()

        age = datetime.now(timezone.utc) - row.updated_at
        due = row.messages_since_refresh >= self._k or age >= self._ttl
        return ContextSnapshot(summary=row.summary, due_for_refresh=due)

    def save_summary(
        self, context_type: str, context_id: UUID, summary: str, last_message_id: Optional[UUID]
    ) -> None:
        row = self.db.get(ConversationTranslationContext, (context_type, context_id))
        if row is None:
            row = ConversationTranslationContext(context_type=context_type, context_id=context_id)
            self.db.add(row)
        row.summary = summary
        row.last_summarized_message_id = last_message_id
        row.messages_since_refresh = 0
        row.updated_at = datetime.now(timezone.utc)
        self.db.commit()

    # ── reader preferences ────────────────────────────────────────────────────

    def get_conversation_pref(self, user_id: UUID, conversation_id: UUID) -> Optional[ReaderConversationPrefs]:
        row = self.db.get(ReaderConversationTranslationPref, (user_id, conversation_id))
        if row is None:
            return None
        return ReaderConversationPrefs(
            user_id=row.user_id,
            conversation_id=row.conversation_id,
            target_lang=row.target_lang,
            continuous_enabled=row.continuous_enabled,
        )

    def get_default_target_lang(self, user_id: UUID) -> Optional[str]:
        row = self.db.get(ReaderTranslationDefault, user_id)
        return row.target_lang if row else None

    def set_conversation_pref(
        self,
        user_id: UUID,
        conversation_id: UUID,
        target_lang: Optional[str] = None,
        continuous_enabled: Optional[bool] = None,
    ) -> ReaderConversationPrefs:
        row = self.db.get(ReaderConversationTranslationPref, (user_id, conversation_id))
        if row is None:
            row = ReaderConversationTranslationPref(user_id=user_id, conversation_id=conversation_id)
            self.db.add(row)
        if target_lang is not None:
            row.target_lang = target_lang
        if continuous_enabled is not None:
            row.continuous_enabled = continuous_enabled
        self.db.commit()
        return ReaderConversationPrefs(
            user_id=row.user_id,
            conversation_id=row.conversation_id,
            target_lang=row.target_lang,
            continuous_enabled=row.continuous_enabled,
        )

    def set_default_target_lang(self, user_id: UUID, target_lang: str) -> None:
        row = self.db.get(ReaderTranslationDefault, user_id)
        if row is None:
            row = ReaderTranslationDefault(user_id=user_id, target_lang=target_lang)
            self.db.add(row)
        else:
            row.target_lang = target_lang
        self.db.commit()
