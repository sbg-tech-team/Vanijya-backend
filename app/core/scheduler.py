import logging
import os

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database.session import SessionLocal
from app.core.redis_client import get_redis
from app.modules.calling.presentation import dependencies as calling_di
from app.modules.news.presentation import dependencies as news_di
from app.modules.post.data.repository import PostRepository
from app.modules.post.data.taste_repository import TasteRepository
from app.modules.post.recommendation import jobs as post_rec_jobs
from app.modules.post.recommendation.session_taste import jobs as post_interaction_jobs

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

_log = logging.getLogger(__name__)


# The old hardcoded host (vanijyaa-backend.onrender.com) does not exist, so this
# ping failed every 10 minutes. Render injects RENDER_EXTERNAL_URL itself.
_KEEP_ALIVE_URL = os.environ.get(
    "RENDER_EXTERNAL_URL", "https://vanijya-backend-7fuf.onrender.com"
).rstrip("/") + "/"


def _keep_alive():
    try:
        httpx.get(_KEEP_ALIVE_URL, timeout=10)
    except Exception as exc:
        _log.warning("Keep-alive ping failed: %s", exc)





def _run_expiry_job():
    db = SessionLocal()
    try:
        post_rec_jobs.run_expiry_job(PostRepository(db))
    finally:
        db.close()


def _run_popular_sync():
    db = SessionLocal()
    try:
        post_rec_jobs.run_popular_posts_sync(PostRepository(db))
    finally:
        db.close()


def _run_taste_update():
    db = SessionLocal()
    try:
        post_interaction_jobs.run_taste_update_job(TasteRepository(db))
    finally:
        db.close()


def _run_ignore_detection():
    db = SessionLocal()
    try:
        post_interaction_jobs.run_ignore_detection_job(TasteRepository(db))
    finally:
        db.close()








def _run_global_taste_promotion():
    """
    Nightly Global Session → Persistent Global Taste promotion.

    For each profile with an active global session:
      1. Evaluate three quality gates per commodity key.
      2. Bulk-write qualifying deltas to user_global_taste (PostgreSQL).
      3. Commit the database.
      4. Delete the global session hash from Redis.

    db.commit() MUST precede clear() — enforced by this function.
    Scheduled at 3:15am IST, after posts.ignore_detect (3:00am).
    """
    from app.recommendation.global_session.service import (
        list_active_profile_ids,
        clear as clear_global_session,
    )
    from app.recommendation.global_taste.service import promote_from_global_session

    rc = get_redis()
    db = SessionLocal()
    try:
        profile_ids = list_active_profile_ids(rc)
        for profile_id in profile_ids:
            try:
                candidates = promote_from_global_session(db, rc, profile_id)
                db.commit()
                if candidates:
                    clear_global_session(rc, profile_id)
            except Exception as exc:
                db.rollback()
                _log.error(
                    "Global taste promotion failed for profile %s: %s",
                    profile_id, exc,
                )
    finally:
        db.close()


def start():
    # max_instances/coalesce carried over from app_old: without them a slow run
    # can overlap the next tick and double-ingest / double-count trending.
    scheduler.add_job(news_di.run_news_pipeline_job, "interval", minutes=30, id="news_new.pipeline",
                      max_instances=1, coalesce=True)
    scheduler.add_job(news_di.run_news_trending_job, "interval", minutes=5,  id="news_new.trending",
                      max_instances=1, coalesce=True)
    scheduler.add_job(news_di.run_news_archive_job,  "cron",     hour=2,     id="news_new.archive")

    scheduler.add_job(_run_expiry_job,    "interval", hours=1,    id="posts.expiry")
    scheduler.add_job(_run_popular_sync,  "interval", minutes=15, id="posts.popular")
    scheduler.add_job(_run_taste_update,    "interval", minutes=15, id="posts.taste_update")
    scheduler.add_job(_run_ignore_detection,"cron", hour=3,        id="posts.ignore_detect")
    scheduler.add_job(
        _run_global_taste_promotion,
        "cron", hour=3, minute=15,
        id="recommendation.global_taste_promotion",
    )

    # Calling cost guardrails, weakest assumption last. Stream bills
    # participants x wall-clock minutes, so every way a call can fail to end is
    # a way to run up a bill. Each job also terminates the session ON Stream —
    # ending a call only in our database does not stop the meter.
    scheduler.add_job(calling_di.run_ring_timeout_job,  "interval", seconds=30, id="calls.ring_timeout",
                      max_instances=1, coalesce=True)
    scheduler.add_job(calling_di.run_heartbeat_job, "interval", seconds=30, id="calls.heartbeat",
                      max_instances=1, coalesce=True)
    scheduler.add_job(calling_di.run_solo_participant_job,  "interval", minutes=1, id="calls.solo_timeout",
                      max_instances=1, coalesce=True)
    scheduler.add_job(calling_di.run_max_duration_job,  "interval", minutes=1, id="calls.max_duration",
                      max_instances=1, coalesce=True)
    scheduler.add_job(calling_di.run_provider_retry_job, "interval", minutes=5, id="calls.provider_retry",
                      max_instances=1, coalesce=True)
    scheduler.add_job(calling_di.run_stale_reaper_job,  "interval", minutes=2, id="calls.stale_reaper",
                      max_instances=1, coalesce=True)

    scheduler.add_job(_keep_alive,      "interval", minutes=10,  id="server.keepalive")

    scheduler.start()


def stop():
    scheduler.shutdown()
