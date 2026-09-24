"""restore profile.followers_count / following_count

Revision ID: b8e1f5c02a47
Revises: f3a9c40e77b1
Create Date: 2026-09-24

Reverses f3a9c40e77b1 at the request of the team: the application code is
going back to reading stored counters rather than counting the follow rows.

Written as a forward migration rather than an alembic downgrade because
production is already past f3a9c40e77b1 — removing that revision from the
chain would leave the database pointing at a revision alembic can no longer
resolve.

The columns are backfilled from user_connections, NOT restored as zeroes.
Their previous values were wrong — 15 of 91 profiles disagreed with their
rows, one by 762,373 — so putting those back would be restoring the bug along
with the mechanism. From this point they are only as correct as add_follow /
remove_follow keep them, which is the trade being accepted.

The idx_user_connections_following index is kept. It is what makes
"who follows me" (GET /followers itself) an index lookup instead of a
sequential scan, and nothing about it depends on how the counts are stored.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8e1f5c02a47"
down_revision = "f3a9c40e77b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profile", sa.Column("followers_count", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.add_column("profile", sa.Column("following_count", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.execute("""
        UPDATE profile p SET
            followers_count = (SELECT count(*) FROM user_connections uc
                               WHERE uc.following_id = p.users_id),
            following_count = (SELECT count(*) FROM user_connections uc
                               WHERE uc.follower_id = p.users_id)
    """)


def downgrade() -> None:
    op.drop_column("profile", "followers_count")
    op.drop_column("profile", "following_count")
