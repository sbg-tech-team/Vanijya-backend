"""Re-stamp expired post embeddings so the recommendation feed has candidates.

Every post in this database predates the recommender's 30-day window (newest
2026-07-14), so the expiry job correctly deactivated all 2632 embeddings and
the feed returns nothing. Nothing is broken; there is simply no fresh content.

This makes the existing posts servable again for testing, by treating their
embeddings as if they had just been indexed:

    is_active  -> true
    created_at -> now      (the expiry job partitions on THIS, not the post's
                            date, so leaving it would demote and re-expire
                            every row on the next scheduled run)
    expires_at -> now + CATEGORY_EXPIRY_DAYS[category]

`partition` is left alone — each row's existing tier was assigned legitimately
and stays valid.

It does NOT touch posts.created_at. Post dates are user-visible and rewriting
them would be lying about when people posted. The consequence is that
fresh_post_candidates and rebuild_popular_posts, which filter on the post's own
date, stay empty — the ANN path (hot/warm/cold) is what fills the feed here.

    PYTHONPATH=. python _migration/reactivate_post_embeddings.py           # dry run
    PYTHONPATH=. python _migration/reactivate_post_embeddings.py --apply

To undo: set is_active = false for the post_ids this printed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.database.session import SessionLocal
from app.modules.post.recommendation.constants import CATEGORY_EXPIRY_DAYS

DEFAULT_EXPIRY_DAYS = 14  # categories not in the map


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        rows = db.execute(text(
            "SELECT category, partition, count(*) FROM post_embeddings "
            "WHERE is_active = false GROUP BY category, partition ORDER BY 1, 2"
        )).all()
        if not rows:
            print("nothing to do: no inactive embeddings")
            return 0

        total = sum(r[2] for r in rows)
        print(f"{'apply' if args.apply else 'DRY RUN'} — {total} inactive embeddings\n")
        print(f"  {'category':<16} {'partition':<10} {'rows':>6}  new expires_at")
        for category, partition, n in rows:
            days = CATEGORY_EXPIRY_DAYS.get(category, DEFAULT_EXPIRY_DAYS)
            print(f"  {category or '-':<16} {partition or '-':<10} {n:>6}  "
                  f"+{days}d -> {(now + timedelta(days=days)).date()}")

        if not args.apply:
            print("\nnothing written. re-run with --apply")
            return 0

        updated = 0
        for category, _partition, _n in {(r[0], None, None) for r in rows}:
            days = CATEGORY_EXPIRY_DAYS.get(category, DEFAULT_EXPIRY_DAYS)
            res = db.execute(
                text("""
                    UPDATE post_embeddings
                    SET is_active = true, created_at = :now, expires_at = :exp
                    WHERE is_active = false
                      AND category IS NOT DISTINCT FROM :category
                """),
                {"now": now, "exp": now + timedelta(days=days), "category": category},
            )
            updated += res.rowcount
        db.commit()

        active = db.execute(text(
            "SELECT count(*) FROM post_embeddings WHERE is_active = true")).scalar()
        print(f"\nreactivated {updated}; post_embeddings now active: {active}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
