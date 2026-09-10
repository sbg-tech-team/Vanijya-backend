"""News contract test — app_old URL compatibility + ported-behavior checks.

Rewritten for the news module's second life: the Clean Architecture skeleton
(`news_module/`, now at app/modules/news/) was adapted to answer
app_v1_backup/modules/news_new's exact URLs and behavior (GNews + Groq,
RawArticle/EnrichedArticle), not the RSS+Gemini rewrite this gate originally
targeted (NewsArticle/NewsSource, compat_router, data/tasks.py). See
_migration/LEDGER.md's later entries and this repo's cutover session for the
full story.

    python3 _migration/test_news.py
"""
import _boot  # noqa: F401
import json, os, sys
from datetime import datetime, timezone
from uuid import UUID

from app.modules.news.presentation.router import router as news_router
from app.modules.news.presentation.schemas import (
    RecordEventsRequest, RecordEventItem, SendArticleRequest)
from app.modules.news.application.use_cases.record_interaction import (
    BATCH_MAX_EVENTS, MAX_EVENT_AGE_HOURS, _DWELL_VALUE_CAP_MS)
from app.modules.news.domain.value_objects import CLIENT_EVENT_TYPES
from app.modules.news.data.repository import NewsRepository
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.data.models import EnrichedArticle, RawArticle
from app.modules.chat.data.models import Message

import subprocess
def count(cmd):
    return int(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip() or 0)

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

# --- every app_old news URL must resolve, on ONE router (no compat split) ----
old = json.load(open("old.json"))
old_news = sorted({f'{e["method"]} {e["full"]}' for e in old["endpoints"]
                   if e["file"].split("/")[2] == "news_new"})
have = {f"{sorted(r.methods)[0]} {r.path}" for r in news_router.routes if hasattr(r, "methods")}
missing = [p for p in old_news if p not in have]
check("no app_old news endpoint missing", missing, [])

expected_paths = {
    "GET /news/feed", "GET /news/trending", "GET /news/feed/saved",
    "GET /news/feed/global", "GET /news/feed/domestic", "GET /news/feed/government",
    "GET /news/articles/{article_id}",
    "POST /news/interactions/batch", "POST /news/interactions/like/{article_id}",
    "POST /news/interactions/save/{article_id}", "POST /news/interactions/share/{article_id}",
    "GET /news/interactions/share-sheet/{article_id}", "POST /news/interactions/send/{article_id}",
    "POST /news/admin/ingest", "POST /news/admin/enrich", "GET /news/admin/stats",
    "POST /news/admin/archive",
}
check("all 17 expected news routes present (16 app_old-matching + 1 additive admin/archive)",
      have >= expected_paths, True)

# --- batch endpoint rules ported from app_v1_backup ---------------------------
check("BATCH_MAX_EVENTS", BATCH_MAX_EVENTS, 200)
check("MAX_EVENT_AGE_HOURS", MAX_EVENT_AGE_HOURS, 2)
check("_DWELL_VALUE_CAP_MS", _DWELL_VALUE_CAP_MS, 600_000)
check("client event types", sorted(CLIENT_EVENT_TYPES),
      ["dwell", "impression", "open_article", "share_tap"])

AID = UUID("11111111-1111-1111-1111-111111111111")
now = datetime.now(timezone.utc)
ok_ev = {"article_id": AID, "event_type": "impression", "occurred_at": now}
check("valid batch accepted", len(RecordEventsRequest(events=[ok_ev]).events), 1)
for bad, why in [([], "empty"), ([ok_ev] * (BATCH_MAX_EVENTS + 1), "too large")]:
    try:
        RecordEventsRequest(events=bad); check(f"batch {why} rejected", True, False)
    except Exception:
        pass
try:
    RecordEventItem(article_id=AID, event_type="dwell", occurred_at=now)
    check("dwell without value_ms rejected", True, False)
except Exception as e:
    check("dwell without value_ms rejected", "value_ms is required" in str(e), True)
try:
    RecordEventItem(article_id=AID, event_type="nope", occurred_at=now)
    check("unknown event_type rejected", True, False)
except Exception as e:
    check("unknown event_type rejected", "Unknown event_type" in str(e), True)

# --- article detail: unenriched articles are served, not 404'd ---------------
det_src = open("../app/modules/news/application/use_cases/get_article_detail.py").read()
check("article detail no longer raises ArticleNotEnrichedError",
      "ArticleNotEnrichedError" not in det_src, True)

# --- feed: real session-taste amplify wired in, not a 0.0 placeholder --------
engine_src = open("../app/modules/news/recommendation/engine.py").read()
check("rank_feed calls get_amplify_weights (Layer 3 wired, not a placeholder)",
      "get_amplify_weights" in engine_src, True)
check("no leftover 'Layer 3 placeholder' stub", "placeholder" not in engine_src.lower(), True)
check("trending merges a recency pool (not velocity-only)",
      "recency" in engine_src.lower() and "RECENCY_POOL_CAP" in engine_src, True)

# --- is_government + location fields are real EnrichedArticle columns --------
check("is_government is a real EnrichedArticle column", hasattr(EnrichedArticle, "is_government"), True)
check("location_city is a real EnrichedArticle column", hasattr(EnrichedArticle, "location_city"), True)
check("location_state is a real EnrichedArticle column", hasattr(EnrichedArticle, "location_state"), True)

# --- send: multi-recipient (DMs + groups), not the single-recipient stub -----
check("Message.article_id present", hasattr(Message, "article_id"), True)
from app.modules.chat.data.repository import ChatRepository
import inspect
check("save_message accepts article_id",
      "article_id" in inspect.signature(ChatRepository.save_message).parameters, True)
try:
    SendArticleRequest(); check("send with no recipients rejected", True, False)
except Exception as e:
    check("send with no recipients rejected", "at least one" in str(e).lower(), True)
check("send accepts a DM recipient",
      len(SendArticleRequest(dm_conversation_ids=[AID]).dm_conversation_ids), 1)
check("send accepts a group recipient",
      len(SendArticleRequest(group_ids=[AID]).group_ids), 1)

# --- layering ------------------------------------------------------------------
check("NewsRepository implements the interface",
      issubclass(NewsRepository, INewsRepository), True)
check("no unimplemented abstract methods", sorted(NewsRepository.__abstractmethods__), [])
check("no db.query in news application layer",
      count("grep -rl 'db\\.query' ../app/modules/news/application | wc -l"), 0)
check("no db.query in news presentation layer",
      count("grep -rl 'db\\.query' ../app/modules/news/presentation | wc -l"), 0)
check("news domain imports no framework",
      count("grep -rlE '^(from|import) (sqlalchemy|fastapi|pydantic)' ../app/modules/news/domain | wc -l"), 0)
check("background jobs live in the application layer",
      os.path.exists("../app/modules/news/application/jobs.py"), True)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - news: all app_old URLs resolve on one router, batch/detail/send/amplify ported from app_v1_backup")
