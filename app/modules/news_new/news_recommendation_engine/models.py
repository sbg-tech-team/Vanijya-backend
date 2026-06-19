# Models:
#   ArticleRecommendationScore — per-user per-article combined score
#     fields: user_id, article_id, role_score, profile_score, taste_score, final_score,
#             computed_at, model_version, is_served
#
#   FeedRankingCache — cached ranked article_id list per user+feed_type
#     fields: user_id, feed_type, ranked_article_ids (JSONB array), computed_at, expires_at
