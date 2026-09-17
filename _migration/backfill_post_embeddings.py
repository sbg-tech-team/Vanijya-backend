"""Backfill post_embeddings for posts that were never indexed.

Every index_post() call site passed `repo=` while the function took `db`, so
every call raised TypeError inside a bare `except Exception: pass`. No post
created in that window got an embedding, which means none of them can be
retrieved by the recommendation feed's ANN search. Fixing the code does not
index them retroactively — this does.

    # see what it would do (default)
    PYTHONPATH=. .venv/bin/python _migration/backfill_post_embeddings.py

    # actually write
    PYTHONPATH=. .venv/bin/python _migration/backfill_post_embeddings.py --apply

Safe to re-run: it only touches posts with no embedding row, commits per batch,
and picks up where it left off if interrupted.

Timestamps matter. run_expiry_job() partitions on PostEmbedding.created_at, so
each row is written with the POST's creation time and the partition that age
implies — not the wall clock. Writing everything as "hot" would push months of
old posts to the top of every feed.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.database.session import SessionLocal            # noqa: E402
from app.modules.post.data.models import Post                 # noqa: E402
from app.modules.post.data.repository import PostRepository   # noqa: E402
from app.modules.post.recommendation.constants import (       # noqa: E402
    CATEGORY_EXPIRY_DAYS,
    CATEGORY_NAMES,
    COMMODITY_ID_TO_IDX,
)
from app.modules.post.recommendation.engine import resolve_partition  # noqa: E402
from app.modules.post.data.recommendation_models import PostEmbedding      # noqa: E402
from app.modules.post.recommendation.vectors import build_post_vector # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill")

BATCH = 500


def _aware(dt: datetime) -> datetime:
    """posts.created_at is a naive DateTime column; treat it as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N posts")
    args = ap.parse_args()

    db = SessionLocal()
    repo = PostRepository(db)
    now = datetime.now(timezone.utc)

    stats = {"scanned": 0, "indexed": 0, "expired": 0, "no_partition": 0,
             "unknown_category": 0, "no_location": 0}
    by_partition: dict[str, int] = {}
    last_id = 0

    try:
        while True:
            posts = (
                db.query(Post)
                .outerjoin(PostEmbedding, PostEmbedding.post_id == Post.id)
                .filter(PostEmbedding.post_id.is_(None), Post.id > last_id)
                .order_by(Post.id)
                .limit(BATCH)
                .all()
            )
            if not posts:
                break

            for post in posts:
                last_id = post.id
                stats["scanned"] += 1

                category = CATEGORY_NAMES.get(post.category_id)
                if not category:
                    stats["unknown_category"] += 1
                    continue

                created = _aware(post.created_at)
                expires_at = created + timedelta(days=CATEGORY_EXPIRY_DAYS[category])
                if expires_at <= now:
                    stats["expired"] += 1        # already dead; indexing it is pointless
                    continue

                partition = resolve_partition(category, (now - created).total_seconds() / 3600)
                if partition is None:
                    stats["no_partition"] += 1
                    continue

                lat, lon = post.latitude, post.longitude
                if lat is None or lon is None:
                    profile = repo.get_profile(post.profile_id)
                    if not profile or not profile.business:
                        stats["no_location"] += 1
                        continue
                    lat = float(profile.business.latitude or 0.0)
                    lon = float(profile.business.longitude or 0.0)

                deal = post.deal_details
                vector = build_post_vector(
                    commodity_id=post.commodity_id,
                    target_role_ids=post.target_roles,
                    lat=float(lat),
                    lon=float(lon),
                    is_deal=(category == "deal_req"),
                    commodity_quantity=float(deal.commodity_quantity) if deal else None,
                )

                if args.apply:
                    repo.upsert_post_embedding(
                        post_id=post.id,
                        vector=vector,
                        category=category,
                        commodity_idx=COMMODITY_ID_TO_IDX.get(post.commodity_id, 0),
                        expires_at=expires_at,
                        now=created,          # the POST's creation time, not wall clock
                        partition=partition,
                    )
                stats["indexed"] += 1
                by_partition[partition] = by_partition.get(partition, 0) + 1

                if args.limit and stats["indexed"] >= args.limit:
                    break

            if args.apply:
                db.commit()
            log.info("  ... scanned %d, indexed %d (through post id %d)",
                     stats["scanned"], stats["indexed"], last_id)

            if args.limit and stats["indexed"] >= args.limit:
                break

        if args.apply:
            db.commit()
    except Exception:
        db.rollback()
        log.exception("backfill aborted after post id %d — re-run to resume", last_id)
        return 1
    finally:
        db.close()

    log.info("")
    log.info("%s", "APPLIED" if args.apply else "DRY RUN — nothing written (pass --apply)")
    log.info("  posts without an embedding : %d", stats["scanned"])
    log.info("  indexed                    : %d  %s", stats["indexed"], by_partition or "")
    log.info("  skipped, already expired   : %d", stats["expired"])
    log.info("  skipped, no live partition : %d", stats["no_partition"])
    log.info("  skipped, unknown category  : %d", stats["unknown_category"])
    log.info("  skipped, no location       : %d", stats["no_location"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
