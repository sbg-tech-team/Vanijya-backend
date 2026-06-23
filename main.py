from dotenv import load_dotenv
load_dotenv()

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Ensure the news_new pipeline + scheduler emit at INFO even if a library
# reconfigures the root logger.
logging.getLogger("app.modules.news_new").setLevel(logging.INFO)
logging.getLogger("app.core.scheduler").setLevel(logging.INFO)

from contextlib import asynccontextmanager
import socketio
from fastapi import FastAPI

from app.modules.auth.router import router as auth_router
from app.modules.profile.router import router as profile_router
from app.modules.groups.router import router as groups_router
from app.modules.post.router import router as post_router
from app.modules.post.post_recommendation_module.router import router as post_rec_router
from app.modules.post.post_user_interaction.router import router as post_interaction_router
from app.modules.connections.router import (
    connections_router,
    recommendations_router,
)
from app.modules.news_new import router as news_new_router
from app.modules.feed.router import router as feed_router

from app.modules.chat.presentation.router import router as chat_router
from app.modules.chat.presentation.connection_manager import sio
from app.modules.deeplink.router import router as deeplink_router
from app.modules.safety.router import router as safety_router
from app.modules.verification.router import router as verification_router
from app.core import scheduler as _scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.start()
    yield
    _scheduler.stop()


app = FastAPI(title="Vanijyaa API", lifespan=lifespan)



app.get("/", status_code=200)(lambda: {"message": "Server is up and running!"})

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(groups_router)
app.include_router(post_router)
app.include_router(post_rec_router)
app.include_router(post_interaction_router)
app.include_router(connections_router)
app.include_router(recommendations_router)
app.include_router(news_new_router)
app.include_router(feed_router)
app.include_router(chat_router)
app.include_router(deeplink_router)
app.include_router(safety_router)
app.include_router(verification_router)

app = socketio.ASGIApp(sio, other_asgi_app=app)
