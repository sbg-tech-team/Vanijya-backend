"""Content translation — posts, comments, news — on the reader's command.

Pure Python, no I/O.

A translation is made at most once per (item, language) and stored on the item
itself, so every later reader of that language gets it from the database for
free. Cost scales with the items people actually translate, not with readers.

Each translated field carries a hash of the source text it was made from. A
field whose source changed since (a post edited, a news summary re-enriched)
stops matching and is re-translated on the next request — the modules that own
the content need no invalidation hook.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional, Union
from uuid import UUID

FieldValue = Union[str, list[str]]

ENTITY_POST = "post"
ENTITY_COMMENT = "comment"
ENTITY_NEWS = "news"

# What may be translated, per type. A client asking for anything else is
# ignored for that field — never passed to the engine.
TRANSLATABLE_FIELDS: dict[str, tuple[str, ...]] = {
    ENTITY_POST: ("title", "caption"),
    ENTITY_COMMENT: ("content",),
    ENTITY_NEWS: ("title", "description", "summary_bullets", "impact_factor", "impact_explanation"),
}

STATUS_READY = "ready"
STATUS_IN_PROGRESS = "in_progress"
STATUS_NOT_FOUND = "not_found"
STATUS_FAILED = "failed"


def canonical_id(entity_type: str, raw: str) -> str:
    """One spelling per item: "007" and "7" are the same post, an uppercase
    uuid is the same article. Without this the two spellings take separate
    locks and pay for the same translation twice. An id that does not parse
    is returned as-is — the repository reports it not_found."""
    raw = raw.strip()
    if entity_type in (ENTITY_POST, ENTITY_COMMENT):
        try:
            return str(int(raw))
        except ValueError:
            return raw
    if entity_type == ENTITY_NEWS:
        try:
            return str(UUID(raw))
        except ValueError:
            return raw
    return raw


def field_hash(value: FieldValue) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ContentRef:
    """What the client asks for. `fields` narrows the request (a news card
    needs only title + bullets); None means every translatable field."""
    entity_type: str
    entity_id: str
    fields: Optional[tuple[str, ...]] = None

    @property
    def key(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"

    def wanted_fields(self) -> tuple[str, ...]:
        allowed = TRANSLATABLE_FIELDS.get(self.entity_type, ())
        if self.fields is None:
            return allowed
        return tuple(f for f in allowed if f in self.fields)


@dataclass
class StoredTranslation:
    """What an item holds for one language: field -> (source hash, text)."""
    fields: dict[str, tuple[str, FieldValue]] = field(default_factory=dict)

    def fresh_value(self, name: str, source_value: FieldValue) -> Optional[FieldValue]:
        entry = self.fields.get(name)
        if entry is None or entry[0] != field_hash(source_value):
            return None
        return entry[1]


@dataclass(frozen=True)
class ContentSource:
    """An item as it reads right now, in its original language.

    `fields` holds only non-empty fields. `context` is never translated — it
    lets the engine disambiguate (a deal's commodity and price, the post a
    comment sits under) and is not part of any hash.
    """
    ref: ContentRef
    fields: dict[str, FieldValue]
    context: Optional[str] = None


@dataclass
class ItemResult:
    ref: ContentRef
    status: str
    fields: Optional[dict[str, FieldValue]] = None
    cached: bool = False


def split_fresh(
    source: ContentSource, stored: Optional[StoredTranslation]
) -> tuple[dict[str, FieldValue], dict[str, FieldValue]]:
    """(already translated from the current source, still to translate) for
    the fields the client asked for."""
    ready: dict[str, FieldValue] = {}
    todo: dict[str, FieldValue] = {}
    for name in source.ref.wanted_fields():
        value = source.fields.get(name)
        if value is None:
            continue  # empty on the source — nothing to translate
        hit = stored.fresh_value(name, value) if stored else None
        if hit is None:
            todo[name] = value
        else:
            ready[name] = hit
    return ready, todo


class TranslationShapeError(ValueError):
    """The engine returned something that is not the fields it was given."""


def validate_shape(sent: dict[str, FieldValue], got: object) -> dict[str, FieldValue]:
    """The engine must hand back exactly the keys it was sent, each the same
    kind (a string stays a string, a list keeps its length). A merged or
    dropped news bullet would be stored and then served to every later reader,
    so anything else is rejected rather than saved."""
    if not isinstance(got, dict) or set(got) != set(sent):
        raise TranslationShapeError(f"expected keys {sorted(sent)}, got {str(got)[:200]}")
    out: dict[str, FieldValue] = {}
    for name, value in sent.items():
        result = got[name]
        if isinstance(value, list):
            if (not isinstance(result, list) or len(result) != len(value)
                    or not all(isinstance(x, str) and x.strip() for x in result)):
                raise TranslationShapeError(f"field {name!r}: list shape changed")
        elif not isinstance(result, str) or not result.strip():
            raise TranslationShapeError(f"field {name!r}: expected non-empty text")
        out[name] = result
    return out
