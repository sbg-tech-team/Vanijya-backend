"""Load profile for the API.

    # against a local server (default, safe)
    LOAD_TOKEN=... locust -f _migration/locustfile.py --host http://127.0.0.1:8000 \
      --headless -u 50 -r 5 -t 60s

Defaults to whatever --host you pass; there is no production default on purpose.
The production service runs a SINGLE free-plan instance, so pointing real load
at it degrades the app for actual users — treat that as a deliberate, announced
act, not something a script does by accident.

Weights follow how a social feed is actually used: mostly reading, occasionally
writing.
"""
import os
import random

from locust import HttpUser, between, task

TOKEN = os.environ.get("LOAD_TOKEN", "")
POST_IDS = [int(x) for x in os.environ.get("LOAD_POST_IDS", "").split(",") if x.strip()]


class ApiUser(HttpUser):
    # Real clients think between taps; zero wait measures nothing but a tight loop.
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.client.headers.update({"Authorization": f"Bearer {TOKEN}"})

    # ── Reads: the bulk of real traffic ──────────────────────────────────────
    @task(10)
    def recommendation_feed(self):
        self.client.get("/posts/recommendation/feed?limit=10", name="GET /posts/recommendation/feed")

    @task(6)
    def my_posts(self):
        self.client.get("/posts/mine", name="GET /posts/mine")

    @task(5)
    def post_detail(self):
        if POST_IDS:
            self.client.get(f"/posts/{random.choice(POST_IDS)}", name="GET /posts/{id}")

    @task(4)
    def chat_list(self):
        self.client.get("/chat/all", name="GET /chat/all")

    @task(3)
    def news_feed(self):
        self.client.get("/news/feed?page_size=10", name="GET /news/feed")

    # ── Writes: the minority, but they are what contend on the database ──────
    @task(2)
    def toggle_like(self):
        if POST_IDS:
            pid = random.choice(POST_IDS)
            self.client.post(f"/posts/{pid}/like", json={}, name="POST /posts/{id}/like")

    @task(1)
    def health(self):
        self.client.get("/", name="GET /")
