"""drop the drifted follow counters, index the followers lookup

Revision ID: f3a9c40e77b1
Revises: e7d4a19c8b52
Create Date: 2026-09-24

profile.followers_count / following_count were integers kept in step by hand in
add_follow / remove_follow. That holds only while every write goes through
those two methods; seeding and load-test cleanup wrote user_connections
directly, so they drifted — 15 of 91 profiles disagreed with the rows, one by
762,373. A profile header said 3 followers while /followers returned 2.

They are now counted from user_connections on read, so the columns are dropped
rather than reconciled: reconciling leaves the same trap for the next script
that touches the table.

The new index is what makes that count cheap, and was missing anyway —
user_connections had an index on follower_id but none on following_id, so
every "who follows me" query, including GET /followers itself, was a
sequential scan.
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a9c40e77b1"
down_revision = "e7d4a19c8b52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_user_connections_following", "user_connections", ["following_id"],
        if_not_exists=True,
    )
    op.drop_column("profile", "followers_count")
    op.drop_column("profile", "following_count")


def downgrade() -> None:
    # Restored as zeroes: the values that were there were wrong, and the follow
    # rows are the only truth worth putting back.
    op.add_column("profile", sa.Column("followers_count", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.add_column("profile", sa.Column("following_count", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.drop_index("idx_user_connections_following", table_name="user_connections")
