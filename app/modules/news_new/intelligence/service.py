# Service stubs + DB queries — no AI logic yet
#
# classify(db, article_id)         → assigns NewsCategory, writes ArticleClassification
# summarize(db, article_id)        → generates summary, writes ArticleSummary + NewsArticle.summary
# generate_impact(db, article_id)  → generates impact, writes ArticleImpact + NewsArticle.impact
# score_for_role(db, article_id, role_id) → writes ArticleRoleScore
#
# get_classification(db, article_id)   → ArticleClassification | None
# get_summary(db, article_id)          → ArticleSummary | None
# get_impact(db, article_id)           → ArticleImpact | None
# get_role_score(db, article_id, role_id) → ArticleRoleScore | None
# upsert_classification(db, article_id, data)
# upsert_summary(db, article_id, data)
# upsert_impact(db, article_id, data)
# upsert_role_score(db, article_id, role_id, score)
