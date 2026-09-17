"""close the drift between the ORM models and the migration chain

Two columns existed in the ORM but were never created by a migration:

  profile.avatar_url               present in production (added by hand), so a
                                   fresh database built from migrations lacked
                                   it and could not even insert a profile.

  news_raw_trending.unique_profiles present in NEITHER. recalc_trending() writes
                                   it, so the trending job would fail the moment
                                   any article crossed the threshold. It has not
                                   fired only because the snapshot is empty.

Both are created if absent, so this is a no-op wherever the column already is.

Revision ID: 2cd2e752e76c
Revises: 446633e0fd8d
"""
from typing import Sequence, Union

from alembic import op

revision: str = "2cd2e752e76c"
down_revision: Union[str, None] = "446633e0fd8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)")
    op.execute(
        "ALTER TABLE news_raw_trending "
        "ADD COLUMN IF NOT EXISTS unique_profiles INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    # avatar_url is not dropped: it holds real production data and predates this
    # migration. Only the column this migration genuinely introduced is removed.
    op.execute("ALTER TABLE news_raw_trending DROP COLUMN IF EXISTS unique_profiles")
