from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.translation.domain.interfaces.profile_names_repository import (
    IProfileNamesRepository,
    ProfileName,
)


class ProfileNamesRepository(IProfileNamesRepository):
    """Reads profile.name / name_i18n and writes name_i18n only — the profile
    module owns the row, the same way ContentTranslationRepository writes
    only the `translations` column on posts."""

    def __init__(self, db: Session):
        self.db = db

    def profiles_missing_names(self, targets: tuple[str, ...], limit: int) -> list[ProfileName]:
        # A target is missing if the key is absent and not marked failed.
        # COALESCE: a profile with no "failed" list must count as "not failed",
        # not as NULL (which would silently drop it from the result).
        params: dict = {"limit": limit}
        clauses = []
        for i, lang in enumerate(targets):
            params[f"l{i}"] = lang
            clauses.append(
                f"(NOT jsonb_exists(name_i18n, :l{i}) AND "
                f"NOT jsonb_exists(COALESCE(name_i18n->'failed', '[]'::jsonb), :l{i}))"
            )
        rows = self.db.execute(
            text(f"""
                SELECT id, name, name_i18n FROM profile
                 WHERE name_i18n IS NULL OR {" OR ".join(clauses)}
                 ORDER BY id DESC          -- newest first: real users before old test data
                 LIMIT :limit
            """),
            params,
        ).all()
        return [ProfileName(r[0], r[1], r[2]) for r in rows]

    def get(self, profile_id: int) -> Optional[ProfileName]:
        row = self.db.execute(
            text("SELECT id, name, name_i18n FROM profile WHERE id = :id"), {"id": profile_id}
        ).first()
        return ProfileName(row[0], row[1], row[2]) if row else None

    def save_if_unchanged(self, before: ProfileName, name_i18n: dict) -> bool:
        # Optimistic: only if name and name_i18n are still what was read, so
        # an owner's edit in between is never overwritten. jsonb equality
        # ignores key order and whitespace.
        result = self.db.execute(
            text("""
                UPDATE profile SET name_i18n = CAST(:new AS jsonb)
                 WHERE id = :id AND name = :name
                   AND name_i18n IS NOT DISTINCT FROM CAST(:old AS jsonb)
            """),
            {
                "new": json.dumps(name_i18n, ensure_ascii=False),
                "old": None if before.name_i18n is None else json.dumps(before.name_i18n, ensure_ascii=False),
                "id": before.profile_id,
                "name": before.name,
            },
        )
        self.db.commit()
        return result.rowcount > 0
