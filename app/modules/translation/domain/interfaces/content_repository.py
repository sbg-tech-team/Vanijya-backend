from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.translation.domain.content import (
    ContentRef,
    ContentSource,
    FieldValue,
    StoredTranslation,
)


class IContentTranslationRepository(ABC):
    """Reads translatable content and the translations stored on it.

    Translations live in a `translations` JSONB column on the content row
    itself (posts, post_comments, news_raw_articles), so deleting the item
    deletes its translations. This module is the only writer of that column;
    the owning modules never touch it and never load it.
    """

    @abstractmethod
    def load(
        self, refs: list[ContentRef], target_lang: str, viewer_profile_id: int
    ) -> dict[str, tuple[ContentSource, StoredTranslation]]:
        """Keyed by ContentRef.key. An item the viewer may not see — deleted,
        or its author's account gone — is absent, exactly as if it did not
        exist. At most one round trip per content type."""
        ...

    @abstractmethod
    def save_fields(
        self,
        ref: ContentRef,
        target_lang: str,
        fields: dict[str, tuple[str, FieldValue]],
    ) -> None:
        """Merge (source hash, text) per field into the item's stored
        translation for this language. Fields and languages not named here
        are kept. Must be a single atomic write of that one column — never a
        read-modify-write that could undo a concurrent counter update."""
        ...
