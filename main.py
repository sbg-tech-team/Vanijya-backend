from dotenv import load_dotenv
load_dotenv()

import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

from app.modules.auth.router import router as auth_router
from app.modules.profile.router import router as profile_router
from app.modules.groups.router import router as groups_router
from app.modules.post.router import router as post_router
from app.modules.post.post_recommendation_module.router import router as post_rec_router
from app.modules.connections.router import (
    connections_router,
    recommendations_router,
)
from app.modules.news.router import router as news_router
from app.modules.feed.router import router as feed_router
from app.modules.chat.presentation.router import router as chat_router
from app.modules.chat.presentation.ws_router import ws_router as chat_ws_router
from app.modules.deeplink.router import router as deeplink_router
from app.modules.safety.router import router as safety_router
from app.modules.verification.router import router as verification_router
from app.modules.news.tasks import ingest
from app.core import scheduler as _scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.start()

    try:
        ingest()
    except Exception as exc:
        logging.getLogger(__name__).warning("Startup ingest failed (non-fatal): %s", exc)

    yield

    _scheduler.stop()


app = FastAPI(title="Vanijyaa API", lifespan=lifespan)

_logger = logging.getLogger("api")

_SLOW_MS = 1500


@app.middleware("http")
async def log_response_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000

    status = response.status_code
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"

    tag = ""
    if ms > _SLOW_MS:
        tag = "  SLOW"
    elif status >= 500:
        tag = "  ERROR"

    msg = f"{status}  {ms:>6.0f}ms  {request.method:<5} {path}{tag}"

    if ms > _SLOW_MS or status >= 500:
        _logger.warning(msg)
    else:
        _logger.info(msg)

    return response


app.get("/", status_code=200)(lambda: {"message": "Server is up and running!"})

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(groups_router)
app.include_router(post_router)
app.include_router(post_rec_router)
app.include_router(connections_router)
app.include_router(recommendations_router)
app.include_router(news_router)
app.include_router(feed_router)
app.include_router(chat_router)
app.include_router(chat_ws_router)
app.include_router(deeplink_router)
app.include_router(safety_router)
app.include_router(verification_router)
