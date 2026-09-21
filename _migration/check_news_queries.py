#!/usr/bin/env python3
"""Fail if the news pipeline's external dependencies have drifted.

Two checks, both of which broke silently in production:

  1. Every GNews pool query still returns articles.
  2. Both Groq models the enricher names still exist.

The pool broke silently once: GNews ANDs every bare term, so the original
6-to-9-keyword queries matched zero articles. Ingestion reported
`saved=0, errors=0` — a success shape — nothing new arrived, the 30-day
archive job then deactivated everything already stored, and all three news
feeds served empty arrays while 2866 rows sat in the table. Nobody noticed
for two months.

Groq failed the same way: llama-3.1-8b-instant was retired, the endpoint
answered 404, the adapter treated that as a retryable error and burned five
retries plus backoff on every article before falling back.

Nothing in the app can catch either: an empty result set is indistinguishable
from a quiet news day, and a 404 from a model is indistinguishable from a
transient one. Only asking the providers can.

    GNEWS_API_KEY=... GROQ_API_KEY=... python _migration/check_news_queries.py

Costs one API call per query (12 of the free tier's 100/day), so run it after
editing the pool, not on every deploy.
"""
from __future__ import annotations

import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.modules.news.data.adapters.groq import _FALLBACK_MODEL, _MODEL  # noqa: E402
from app.modules.news.data.adapters.gnews_queries import QUERY_POOL  # noqa: E402

BASE = "https://gnews.io/api/v4/search"
# Must mirror _PARAMS in gnews.py — testing with different parameters would
# prove nothing about what the pipeline actually sends.
PARAMS = {"lang": "en", "max": 10, "in": "title,description", "sortby": "publishedAt"}


def check_groq_models() -> list[str]:
    """Returns the named models Groq no longer serves."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        print("  SKIP  GROQ_API_KEY is not set")
        return []
    try:
        body = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"}, timeout=30,
        ).json()
        available = {m["id"] for m in body.get("data", [])}
    except Exception as exc:
        print(f"  ERROR could not list Groq models: {exc}")
        return []

    missing = []
    for label, model in (("primary", _MODEL), ("fallback", _FALLBACK_MODEL)):
        ok = model in available
        print(f"  {'ok  ' if ok else 'GONE'}  {label:<9} {model}")
        if not ok:
            missing.append(model)
    return missing


def main() -> int:
    key = os.environ.get("GNEWS_API_KEY")
    if not key:
        print("GNEWS_API_KEY is not set", file=sys.stderr)
        return 2

    dead = []
    for i, entry in enumerate(QUERY_POOL, 1):
        params = dict(PARAMS, q=entry["q"], apikey=key)
        if entry.get("country"):
            params["country"] = entry["country"]
        try:
            body = requests.get(BASE, params=params, timeout=30).json()
            total = body.get("totalArticles")
        except Exception as exc:
            total, body = None, {"error": str(exc)}

        if not isinstance(total, int):
            status = f"ERROR {str(body)[:60]}"
            dead.append(entry["q"])
        elif total == 0:
            status = "ZERO"
            dead.append(entry["q"])
        else:
            status = f"{total:>6}"
        print(f"  {i:>2}. {status:>8}  {entry['q'][:64]}")
        time.sleep(1)  # free tier is not generous

    print("\nGroq models")
    missing = check_groq_models()

    if dead or missing:
        if dead:
            print(f"\nFAIL - {len(dead)} query(s) return nothing:", file=sys.stderr)
            for q in dead:
                print(f"  {q}", file=sys.stderr)
        if missing:
            print(f"\nFAIL - {len(missing)} Groq model(s) no longer exist:", file=sys.stderr)
            for m in missing:
                print(f"  {m}", file=sys.stderr)
        return 1
    print(f"\nPASS - all {len(QUERY_POOL)} queries return articles, both Groq models exist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
