import logging
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database.session import SessionLocal
from app.modules.news.tasks import recalc_trending, update_taste, archive_old
from app.modules.news_new.ingestion.jobs import run_news_pipeline
from app.modules.post.post_recommendation_module import jobs as post_rec_jobs
from app.modules.post.post_user_interaction import jobs as post_interaction_jobs

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


def start():
    scheduler.add_job(run_news_pipeline, "interval", minutes=30, id="news_new.pipeline",
                      max_instances=1, coalesce=True)
    scheduler.add_job(recalc_trending,  "interval", minutes=5,   id="news.trending")
    scheduler.add_job(update_taste,     "interval", hours=1,     id="news.taste")
    scheduler.add_job(archive_old,      "cron",     hour=2,      id="news.archive")

    scheduler.add_job(_run_expiry_job,    "interval", hours=1,    id="posts.expiry")
    scheduler.add_job(_run_popular_sync,  "interval", minutes=15, id="posts.popular")
    scheduler.add_job(_run_taste_update,    "interval", minutes=15, id="posts.taste_update")
    scheduler.add_job(_run_ignore_detection,"cron", hour=3,        id="posts.ignore_detect")

    scheduler.add_job(_keep_alive,      "interval", minutes=10,  id="server.keepalive")

    scheduler.start()


def stop():
    scheduler.shutdown()
