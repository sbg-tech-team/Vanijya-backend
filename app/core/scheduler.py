import logging
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database.session import SessionLocal
from app.core.redis_client import get_redis
from app.modules.news.application import jobs as news_jobs
from app.modules.post.recommendation import jobs as post_rec_jobs
from app.modules.post.recommendation.session_taste import jobs as post_interaction_jobs

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

_log = logging.getLogger(__name__)


def _keep_alive():
    try:
        httpx.get("https://vanijyaa-backend.onrender.com/", timeout=10)
    except Exception as exc:
        _log.warning("Keep-alive ping failed: %s", exc)


def _run_news_pipeline():
    db = SessionLocal()
    try:
        news_jobs.run_news_pipeline(db)
    finally:
        db.close()


def _run_news_trending():
    db = SessionLocal()
    try:
        news_jobs.run_trending_job(db)
    finally:
        db.close()


def _run_news_archive():
    db = SessionLocal()
    try:
        news_jobs.run_archive_job(db)
    finally:
        db.close()


def _run_expiry_job():
    db = SessionLocal()
    try:
        post_rec_jobs.run_expiry_job(db)
    finally:
        db.close()


def _run_popular_sync():
    db = SessionLocal()
    try:
        post_rec_jobs.run_popular_posts_sync(db)
    finally:
        db.close()


def _run_taste_update():
    db = SessionLocal()
    try:
        post_interaction_jobs.run_taste_update_job(db)
    finally:
        db.close()


def _run_ignore_detection():
    db = SessionLocal()
    try:
        post_interaction_jobs.run_ignore_detection_job(db)
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
    scheduler.add_job(_run_news_pipeline, "interval", minutes=30, id="news_new.pipeline",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_run_news_trending, "interval", minutes=5,  id="news_new.trending",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_run_news_archive,  "cron",     hour=2,     id="news_new.archive")

    scheduler.add_job(_run_expiry_job,    "interval", hours=1,    id="posts.expiry")
    scheduler.add_job(_run_popular_sync,  "interval", minutes=15, id="posts.popular")
    scheduler.add_job(_run_taste_update,    "interval", minutes=15, id="posts.taste_update")
    scheduler.add_job(_run_ignore_detection,"cron", hour=3,        id="posts.ignore_detect")
    scheduler.add_job(
        _run_global_taste_promotion,
        "cron", hour=3, minute=15,
        id="recommendation.global_taste_promotion",
    )

    scheduler.add_job(_keep_alive,      "interval", minutes=10,  id="server.keepalive")

    scheduler.start()


def stop():
    scheduler.shutdown()
