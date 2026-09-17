from dotenv import load_dotenv
load_dotenv()

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Ensure the news pipeline + scheduler emit at INFO even if a library
# reconfigures the root logger.
logging.getLogger("app.modules.news").setLevel(logging.INFO)
logging.getLogger("app.core.scheduler").setLevel(logging.INFO)

from app.core.monitoring import init_sentry

# Before the app is built, so import-time and startup failures are reported too.
init_sentry()

from contextlib import asynccontextmanager
import socketio
from fastapi import FastAPI

from app.routers import register_routers
from app.core.realtime import sio, start_evict_listener, stop_evict_listener
# Imported for its @sio.event side effects — registers the chat socket handlers.
import app.modules.chat.presentation.connection_manager  # noqa: F401
from app.core import scheduler as _scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Each worker listens for room evictions from the others. No-op without Redis.
    await start_evict_listener()
    _scheduler.start()
    yield
    _scheduler.stop()
    await stop_evict_listener()


app = FastAPI(title="Vanijyaa API", lifespan=lifespan)


app.get("/", status_code=200)(lambda: {"message": "Server is up and running!"})

register_routers(app)

app = socketio.ASGIApp(sio, other_asgi_app=app)
