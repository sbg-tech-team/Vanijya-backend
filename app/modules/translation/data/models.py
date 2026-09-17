import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base


class ConversationTranslationContext(Base):
    """One shared rolling summary per conversation (dm or group) — same for
    every participant, since it describes message content, not a reader's
    language. Keyed like chat's own messages table (context_type + context_id)
    since context_id may point at either a conversation or a group."""

    __tablename__ = "conversation_translation_context"

    context_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    context_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_summarized_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    # Counts translate requests since the last refresh (not raw chat volume —
    # there's no hook into chat's send path for that, and translation activity
    # is what actually needs a fresh summary).
    messages_since_refresh: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReaderConversationTranslationPref(Base):
    """Per-reader, per-conversation target language + continuous on/off.
    Continuous only ever gets set True for context_type == 'dm' — enforced in
    ToggleContinuousTranslationUseCase, not here."""

    __tablename__ = "reader_conversation_translation_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    target_lang: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    continuous_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReaderTranslationDefault(Base):
    """Reader's app-wide default target language — the fallback below any
    per-conversation override."""

    __tablename__ = "reader_translation_defaults"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_lang: Mapped[str] = mapped_column(String(10), nullable=False)
