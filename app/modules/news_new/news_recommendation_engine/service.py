# Service stubs + DB queries — no recommendation logic yet
#
# rank_feed(db, user_id, feed_type, article_ids) → list[UUID] (ordered)
#   Combines role_score + profile_score + taste_score into final_score
#   Writes ArticleRecommendationScore rows
#   Caches result in FeedRankingCache
#
# compute_score(db, user_id, article_id) → ArticleRecommendationScore
#   Pulls role_score from intelligence.ArticleRoleScore
#   Derives profile_score from user's business profile
#   Derives taste_score from news_user_interaction.UserNewsTaste
#   Computes final_score (weights TBD)
#
# --- DB queries ---
# upsert_recommendation_score(db, user_id, article_id, scores)
# get_recommendation_scores(db, user_id, article_ids) → list[ArticleRecommendationScore]
# get_feed_ranking_cache(db, user_id, feed_type)      → FeedRankingCache | None
# upsert_feed_ranking_cache(db, user_id, feed_type, ranked_article_ids, expires_at)
# invalidate_feed_ranking_cache(db, user_id, feed_type)
