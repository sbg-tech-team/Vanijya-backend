"""groups_image_url_and_media_table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-27

Changes
-------
groups table:
  - drop   icon_url column
  - add    image_url column  (stored in group-image Supabase bucket)

group_media table (new):
  - stores image / video files uploaded to a group
  - backed by the group-media Supabase bucket
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # groups — swap icon_url → image_url
    # ------------------------------------------------------------------
    op.drop_column("groups", "icon_url")
    op.add_column(
        "groups",
        sa.Column("image_url", sa.String(length=500), nullable=True),
    )

    # ------------------------------------------------------------------
    # group_media — new table
    # ------------------------------------------------------------------
    op.create_table(
        "group_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("media_url", sa.String(length=500), nullable=False),
        # image | video
        sa.Column(
            "media_type",
            sa.String(length=20),
            nullable=False,
            server_default="image",
        ),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index — fast lookup of all media for a group ordered by time
    op.create_index(
        "idx_group_media_group_id",
        "group_media",
        ["group_id", "uploaded_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_group_media_group_id", table_name="group_media")
    op.drop_table("group_media")

    op.drop_column("groups", "image_url")
    op.add_column(
        "groups",
        sa.Column("icon_url", sa.String(length=500), nullable=True),
    )
