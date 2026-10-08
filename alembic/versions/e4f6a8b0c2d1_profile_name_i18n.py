"""profile.name_i18n — a person's name per language

Revision ID: e4f6a8b0c2d1
Revises: d8e3f1a2b4c5
Create Date: 2026-10-08

{"hi": "तथागत", "en": "Tathagata", "auto": ["en"]}: `name` stays what the
person typed; this holds it under its own language plus other languages,
typed/picked by the person or generated ("auto"). Nullable with no default —
existing rows are filled in by the name-generation job, no table rewrite.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e4f6a8b0c2d1"
down_revision = "d8e3f1a2b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profile",
        sa.Column("name_i18n", postgresql.JSONB(), nullable=True),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("profile", "name_i18n", if_exists=True)
