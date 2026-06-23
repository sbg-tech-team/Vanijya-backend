"""add news_new tables

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-06-23

Creates all tables for the news_new module:
  news_raw_articles, news_enriched_articles,
  news_interaction_events, news_views, news_likes, news_saves, news_shares,
  news_article_stats, news_raw_trending,
  user_news_taste, user_news_taste_profiles,
  news_recommendation_scores, news_feed_ranking_cache
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── news_raw_articles ─────────────────────────────────────────────────────
    op.create_table(
        "news_raw_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("article_url", sa.String(1000), nullable=False),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=False),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("source_name", sa.String(200), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_country", sa.String(80), nullable=True),
        sa.Column("authors", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("api_summary", sa.Text, nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB, nullable=True),
        sa.Column("intelligence_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("platform_arrived_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_news_raw_articles_status", "news_raw_articles", ["intelligence_status"])
    op.create_index("ix_news_raw_articles_published_at", "news_raw_articles", ["published_at"])
    op.create_index("ix_news_raw_articles_arrived_at", "news_raw_articles", ["platform_arrived_at"])

    # ── news_enriched_articles ────────────────────────────────────────────────
    op.create_table(
        "news_enriched_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "raw_article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("primary_factor", sa.String(40), nullable=False),
        sa.Column("factor_scores", postgresql.JSONB, nullable=True),
        sa.Column("geo_category", sa.String(20), nullable=False),
        sa.Column("summary_bullets", postgresql.JSONB, nullable=True),
        sa.Column("summary_long", sa.Text, nullable=True),
        sa.Column("impact_direction", sa.String(20), nullable=False),
        sa.Column("impact_score", sa.Float, nullable=False),
        sa.Column("impact_factor", sa.String(120), nullable=True),
        sa.Column("impact_explanation", sa.Text, nullable=True),
        sa.Column("role_trader", sa.Float, nullable=False),
        sa.Column("role_broker", sa.Float, nullable=False),
        sa.Column("role_exporter", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(80), nullable=True),
        sa.Column("generated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── news_interaction_events ───────────────────────────────────────────────
    op.create_table(
        "news_interaction_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("value_ms", sa.Integer, nullable=True),
        sa.Column("occurred_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_nie_profile_article", "news_interaction_events", ["profile_id", "article_id"])
    op.create_index("ix_nie_event_type_created", "news_interaction_events", ["event_type", "created_at"])
    op.create_index("ix_nie_created_at", "news_interaction_events", ["created_at"])
    op.create_index("ix_nie_event_type_processed", "news_interaction_events", ["event_type", "processed_at"])

    # ── news_views ────────────────────────────────────────────────────────────
    op.create_table(
        "news_views",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_viewed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("last_viewed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("view_count", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("profile_id", "article_id", name="uq_news_view_profile_article"),
    )
    op.create_index("ix_nv_profile_id", "news_views", ["profile_id"])

    # ── news_likes ────────────────────────────────────────────────────────────
    op.create_table(
        "news_likes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "article_id", name="uq_news_like_profile_article"),
    )
    op.create_index("ix_nl_profile_id", "news_likes", ["profile_id"])

    # ── news_saves ────────────────────────────────────────────────────────────
    op.create_table(
        "news_saves",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "article_id", name="uq_news_save_profile_article"),
    )
    op.create_index("ix_ns_profile_id", "news_saves", ["profile_id"])

    # ── news_shares ───────────────────────────────────────────────────────────
    op.create_table(
        "news_shares",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_nsh_profile_id", "news_shares", ["profile_id"])

    # ── news_article_stats ────────────────────────────────────────────────────
    op.create_table(
        "news_article_stats",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("view_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("like_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("save_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("share_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── news_raw_trending ─────────────────────────────────────────────────────
    op.create_table(
        "news_raw_trending",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("velocity_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("trending_rank", sa.Integer, nullable=True),
        sa.Column("computed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_nrt_velocity_score", "news_raw_trending", ["velocity_score"])

    # ── user_news_taste ───────────────────────────────────────────────────────
    op.create_table(
        "user_news_taste",
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dimension_type", sa.String(20), primary_key=True),
        sa.Column("dimension_key", sa.String(80), primary_key=True),
        sa.Column("positive_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("negative_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("event_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_unt_profile_type", "user_news_taste", ["profile_id", "dimension_type"])

    # ── user_news_taste_profiles ──────────────────────────────────────────────
    op.create_table(
        "user_news_taste_profiles",
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dominant_factor", sa.String(40), nullable=True),
        sa.Column("factor_weights", postgresql.JSONB, nullable=True),
        sa.Column("total_events", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bootstrapped", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── news_recommendation_scores ────────────────────────────────────────────
    op.create_table(
        "news_recommendation_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("profile_score", sa.Float, nullable=True),
        sa.Column("taste_score", sa.Float, nullable=True),
        sa.Column("final_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("computed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("model_version", sa.String(80), nullable=True),
        sa.Column("is_served", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("profile_id", "article_id", name="uq_news_rec_score_profile_article"),
    )
    op.create_index("ix_nrs_profile_final", "news_recommendation_scores", ["profile_id", "final_score"])

    # ── news_feed_ranking_cache ───────────────────────────────────────────────
    op.create_table(
        "news_feed_ranking_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feed_type", sa.String(30), nullable=False, server_default="default"),
        sa.Column("ranked_article_ids", postgresql.JSONB, nullable=True),
        sa.Column("computed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("profile_id", "feed_type", name="uq_news_feed_cache_profile_type"),
    )
    op.create_index("ix_nfc_expires_at", "news_feed_ranking_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_table("news_feed_ranking_cache")
    op.drop_table("news_recommendation_scores")
    op.drop_table("user_news_taste_profiles")
    op.drop_table("user_news_taste")
    op.drop_table("news_raw_trending")
    op.drop_table("news_article_stats")
    op.drop_table("news_shares")
    op.drop_table("news_saves")
    op.drop_table("news_likes")
    op.drop_table("news_views")
    op.drop_table("news_interaction_events")
    op.drop_table("news_enriched_articles")
    op.drop_table("news_raw_articles")
