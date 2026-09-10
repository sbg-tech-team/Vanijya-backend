import logging
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database.session import SessionLocal
from app.core.redis_client import get_redis
from app.modules.news_new.ingestion.jobs import archive_old_articles, run_news_pipeline
from app.modules.news_new.news_user_interaction.jobs import recalc_trending as _recalc_trending
from app.modules.post.post_recommendation_module import jobs as post_rec_jobs
from app.modules.post.post_user_interaction import jobs as post_interaction_jobs
from app.modules.taste.global_session import (
    clear_global_session,
    list_active_global_session_profile_ids,
)
from app.modules.taste.global_taste import promote_from_global_session

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

_log = logging.getLogger(__name__)


def _keep_alive():
    try:
        httpx.get("https://vanijyaa-backend.onrender.com/", timeout=10)
    except Exception as exc:
        _log.warning("Keep-alive ping failed: %s", exc)


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
    db = SessionLocal()
    rc = get_redis()
    try:
        profile_ids = list_active_global_session_profile_ids(rc)
    except Exception:
        _log.exception("Global taste promotion: failed to enumerate active profiles")
        db.close()
        return

    for pid in profile_ids:
        try:
            candidates = promote_from_global_session(db, rc, pid)
            db.commit()
            if candidates:
                clear_global_session(rc, pid)
        except Exception:
            db.rollback()
            _log.exception("Global taste promotion failed for profile_id=%s", pid)
    db.close()


def start():
    scheduler.add_job(run_news_pipeline,    "interval", minutes=30, id="news_new.pipeline",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_recalc_trending,     "interval", minutes=5,  id="news_new.trending",
                      max_instances=1, coalesce=True)
    scheduler.add_job(archive_old_articles, "cron",     hour=2,     id="news_new.archive")
    scheduler.add_job(_run_expiry_job,    "interval", hours=1,    id="posts.expiry")
    scheduler.add_job(_run_popular_sync,  "interval", minutes=15, id="posts.popular")
    scheduler.add_job(_run_taste_update,    "interval", hours=12, id="posts.taste_update")
    scheduler.add_job(_run_ignore_detection,"cron", hour=3,        id="posts.ignore_detect")
    scheduler.add_job(_run_global_taste_promotion, "cron", hour=3, minute=15,
                      id="taste.global_promotion")

    scheduler.add_job(_keep_alive,      "interval", minutes=10,  id="server.keepalive")

    scheduler.start()


def stop():
    scheduler.shutdown()
