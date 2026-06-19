# Service + DB queries
#
# ingest_article(db, raw: dict) → NewsArticle
# ingest_batch(db, raws: list[dict]) → list[NewsArticle]
#
# upsert_article(db, data) → NewsArticle      — insert or skip on duplicate external_id
# get_article_by_external_id(db, external_id) → NewsArticle | None
# get_pending_articles(db, limit) → list[NewsArticle]  — intelligence_status = "pending"
