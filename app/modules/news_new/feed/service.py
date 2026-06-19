# Service + DB queries
#
# get_trending_feed(db, user_id, cursor, limit) → FeedPage
# get_saved_feed(db, user_id, cursor, limit)    → FeedPage
# get_filtered_feed(db, user_id, feed_filter, cursor, limit) → FeedPage
#   feed_filter: "global" | "government" | "domestic"
#   — placeholder until ingestion populates category data
# get_article_detail(db, article_id, user_id)   → NewsCardDetail
#
# assemble_card(article, stats, is_liked, is_saved)        → NewsCard
# assemble_card_detail(article, stats, is_liked, is_saved) → NewsCardDetail
#
# compute_time_on_platform(platform_arrived_at: datetime) → str
#   < 24h   → "Xh"          (e.g. "3h", "14h")
#   1 day   → "Yesterday"
#   > 1 day → "X days ago"
#
# --- DB queries ---
# get_trending_feed(db, cursor, limit)         → list[NewsArticle + stats]
# get_saved_feed(db, user_id, cursor, limit)   → list[NewsArticle + stats]
# get_filtered_feed(db, feed_filter, cursor, limit) → list[NewsArticle + stats]
# get_article_detail(db, article_id, user_id)  → NewsArticle + stats + is_liked + is_saved
