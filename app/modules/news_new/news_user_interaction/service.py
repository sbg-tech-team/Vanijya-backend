# Service + DB queries
#
# process_interaction_batch(db, user_id, events) → {accepted, dropped}
#   - filters stale events (> MAX_EVENT_AGE_HOURS)
#   - validates article_ids
#   - caps dwell value_ms at DWELL_VALUE_CAP_MS
#   - bulk inserts into NewsInteractionEvent with processed_at=NULL
#   - upserts NewsView for open_article events (revisit detection)
#
# toggle_like(db, user_id, article_id) → is_liked bool
# toggle_save(db, user_id, article_id) → is_saved bool
# record_share(db, user_id, article_id, platform)
#
# _record_revisit_event(db, user_id, article_id)  ← called when NewsView unique constraint fires
#
# --- DB queries ---
# insert_events_bulk(db, events)
# get_view(db, user_id, article_id)           → NewsView | None
# upsert_view(db, user_id, article_id)
# get_article_stats(db, article_id)           → NewsArticleStats | None
# increment_stats(db, article_id, field, delta)
# get_trending(db, limit, cursor)             → list[NewsTrending]
# upsert_trending(db, article_id, fields)
