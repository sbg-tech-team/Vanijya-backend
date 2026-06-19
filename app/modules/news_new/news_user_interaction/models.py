# Models:
#   NewsInteractionEvent  — append-only client event log (impression, dwell, open_article, share_tap, revisit)
#   NewsView              — unique per user+article (unique constraint for revisit detection)
#   NewsLike              — unique(user_id, article_id), toggle
#   NewsSave              — unique(user_id, article_id), toggle
#   NewsShare             — share event log with platform
#   NewsArticleStats      — pre-computed counts (like_count, share_count, view_count, save_count)
#   NewsTrending          — velocity_score, trending_rank, computed by background job
#   UserNewsTaste         — row-per-dimension taste store (category, source, tag)
#   UserNewsTasteProfile  — global taste summary for cold-start and recommendation engine
