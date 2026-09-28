from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.news.data.models import EnrichedArticle, RawArticle
from app.modules.post.data.models import Post, PostComment, PostDealDetails
from app.modules.translation.domain.content import (
    ENTITY_COMMENT,
    ENTITY_NEWS,
    ENTITY_POST,
    ContentRef,
    ContentSource,
    FieldValue,
    StoredTranslation,
)
from app.modules.translation.domain.interfaces.content_repository import IContentTranslationRepository

# Table per entity type for the write. A fixed map, never interpolated from
# input — the only strings that reach the SQL below come from here.
_TABLES = {
    ENTITY_POST: "posts",
    ENTITY_COMMENT: "post_comments",
    ENTITY_NEWS: "news_raw_articles",
}

# One statement, one column. Postgres re-evaluates the SET expression against
# the latest row version if a concurrent UPDATE (a like, a comment count, the
# other language being saved) got there first, so nothing is lost either way.
_MERGE_SQL = """
    UPDATE {table}
       SET translations = COALESCE(translations, '{{}}'::jsonb)
           || jsonb_build_object(
                CAST(:lang AS text),
                COALESCE(translations -> CAST(:lang AS text), '{{}}'::jsonb) || CAST(:fields AS jsonb)
              )
     WHERE id = :id
"""


class ContentTranslationRepository(IContentTranslationRepository):
    """Reads posts, comments and news straight from their owners' tables, the
    same way TranslationRepository reads chat's messages: read-only for the
    content, and the sole writer of the `translations` column on each.

    Every read selects `translations -> lang` only — never the whole column —
    so an item translated into ten languages costs the same to read as one.
    """

    def __init__(self, db: Session):
        self.db = db

    # ── reads ─────────────────────────────────────────────────────────────────

    def load(
        self, refs: list[ContentRef], target_lang: str, viewer_profile_id: int
    ) -> dict[str, tuple[ContentSource, StoredTranslation]]:
        # viewer_profile_id: visibility today is "the item exists" — the same
        # rule GET /posts/{id} and the news detail apply. It is threaded
        # through so a future visibility rule (blocks, target_roles) lands
        # here without changing the port.
        by_type: dict[str, dict[str, ContentRef]] = {}
        for ref in refs:
            by_type.setdefault(ref.entity_type, {})[ref.entity_id] = ref

        out: dict[str, tuple[ContentSource, StoredTranslation]] = {}
        if ENTITY_POST in by_type:
            out.update(self._load_posts(by_type[ENTITY_POST], target_lang))
        if ENTITY_COMMENT in by_type:
            out.update(self._load_comments(by_type[ENTITY_COMMENT], target_lang))
        if ENTITY_NEWS in by_type:
            out.update(self._load_news(by_type[ENTITY_NEWS], target_lang))
        return out

    def _load_posts(self, refs: dict[str, ContentRef], lang: str):
        ids = _int_ids(refs)
        if not ids:
            return {}
        rows = self.db.execute(
            select(
                Post.id, Post.title, Post.caption, Post.translations[lang],
                PostDealDetails.grain_type, PostDealDetails.grain_size,
                PostDealDetails.commodity_quantity, PostDealDetails.quantity_unit,
                PostDealDetails.commodity_price, PostDealDetails.price_type,
            )
            .outerjoin(PostDealDetails, PostDealDetails.post_id == Post.id)
            .where(Post.id.in_(list(ids)))
        ).all()
        out = {}
        for r in rows:
            ref = ids[r[0]]
            context = None
            if r.grain_type:
                context = (f"Deal post: {r.grain_type} ({r.grain_size}), "
                           f"{r.commodity_quantity} {r.quantity_unit} at "
                           f"{r.commodity_price} ({r.price_type})")
            source = ContentSource(ref=ref, fields=_non_empty(title=r.title, caption=r.caption),
                                   context=context)
            out[ref.key] = (source, _stored(r[3]))
        return out

    def _load_comments(self, refs: dict[str, ContentRef], lang: str):
        ids = _int_ids(refs)
        if not ids:
            return {}
        rows = self.db.execute(
            select(PostComment.id, PostComment.content, PostComment.translations[lang], Post.title)
            .join(Post, Post.id == PostComment.post_id)
            .where(PostComment.id.in_(list(ids)))
        ).all()
        out = {}
        for comment_id, content, stored, post_title in rows:
            ref = ids[comment_id]
            source = ContentSource(ref=ref, fields=_non_empty(content=content),
                                   context=f"Comment on a post titled: {post_title}")
            out[ref.key] = (source, _stored(stored))
        return out

    def _load_news(self, refs: dict[str, ContentRef], lang: str):
        ids: dict[UUID, ContentRef] = {}
        for entity_id, ref in refs.items():
            try:
                ids[UUID(entity_id)] = ref
            except ValueError:
                continue  # not a uuid: cannot exist, reported not_found
        if not ids:
            return {}
        rows = self.db.execute(
            select(
                RawArticle.id, RawArticle.title, RawArticle.description,
                RawArticle.translations[lang], RawArticle.source_name,
                EnrichedArticle.summary_bullets, EnrichedArticle.impact_factor,
                EnrichedArticle.impact_explanation,
            )
            .outerjoin(EnrichedArticle, EnrichedArticle.raw_article_id == RawArticle.id)
            .where(RawArticle.id.in_(list(ids)))
        ).all()
        out = {}
        for r in rows:
            ref = ids[r[0]]
            bullets = [b for b in (r.summary_bullets or []) if isinstance(b, str) and b.strip()]
            source = ContentSource(
                ref=ref,
                fields=_non_empty(
                    title=r.title, description=r.description,
                    summary_bullets=bullets or None,
                    impact_factor=r.impact_factor, impact_explanation=r.impact_explanation,
                ),
                context=f"News article from {r.source_name}" if r.source_name else None,
            )
            out[ref.key] = (source, _stored(r[3]))
        return out

    # ── write ─────────────────────────────────────────────────────────────────

    def save_fields(
        self,
        ref: ContentRef,
        target_lang: str,
        fields: dict[str, tuple[str, FieldValue]],
    ) -> None:
        table = _TABLES[ref.entity_type]
        entity_id: object = ref.entity_id if ref.entity_type == ENTITY_NEWS else int(ref.entity_id)
        payload = {name: {"h": h, "v": v} for name, (h, v) in fields.items()}
        self.db.execute(
            text(_MERGE_SQL.format(table=table)),
            {"lang": target_lang, "fields": json.dumps(payload, ensure_ascii=False), "id": entity_id},
        )
        self.db.commit()


def _int_ids(refs: dict[str, ContentRef]) -> dict[int, ContentRef]:
    """Parsed id -> its ref. Ids arrive canonical (content.canonical_id), so
    each row maps back to exactly one ref."""
    ids: dict[int, ContentRef] = {}
    for entity_id, ref in refs.items():
        try:
            parsed = int(entity_id)
        except ValueError:
            continue  # not an int id: cannot exist, reported not_found
        # Outside int4 Postgres raises instead of matching nothing — a 500
        # for a made-up id.
        if 0 < parsed < 2**31:
            ids[parsed] = ref
    return ids


def _non_empty(**fields: Optional[FieldValue]) -> dict[str, FieldValue]:
    return {k: v for k, v in fields.items() if v and (not isinstance(v, str) or v.strip())}


def _stored(raw: Optional[dict]) -> StoredTranslation:
    """{field: {"h", "v"}} -> StoredTranslation. Anything malformed is skipped,
    which just means that field gets translated again."""
    stored = StoredTranslation()
    if not isinstance(raw, dict):
        return stored
    for name, entry in raw.items():
        if isinstance(entry, dict) and "h" in entry and "v" in entry:
            stored.fields[name] = (entry["h"], entry["v"])
    return stored
