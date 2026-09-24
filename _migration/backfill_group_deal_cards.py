"""Restore deal_id on group deal cards written before the column was populated.

Group messages with message_type='deal' render their deal card from
messages.deal_id. Cards written between 2026-05-02 and 2026-06-01 stored the
id only inside media_metadata['group_deal_id'] and left the column NULL, so
those 198 cards come back with deal: null and render blank in the app. Every
card written since 2026-06-09 sets the column correctly, so this is history,
not an ongoing fault.

The id is present and exact — no matching or guessing — and every one of them
resolves to a live group_deals row.

    PYTHONPATH=. python _migration/backfill_group_deal_cards.py           # dry run
    PYTHONPATH=. python _migration/backfill_group_deal_cards.py --apply
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.core.database.session import SessionLocal

_SELECT = """
    SELECT count(*) FILTER (WHERE m.media_metadata ? 'group_deal_id')            AS has_id,
           count(*) FILTER (WHERE m.media_metadata ? 'group_deal_id'
                              AND EXISTS (SELECT 1 FROM group_deals d
                                          WHERE d.id = (m.media_metadata->>'group_deal_id')::uuid)) AS resolvable,
           count(*)                                                              AS total
    FROM messages m
    WHERE m.context_type = 'group' AND m.message_type = 'deal' AND m.deal_id IS NULL
"""

# Only rows whose id resolves to a real deal, so a stale reference is left
# alone rather than written as a dangling foreign key.
_UPDATE = """
    UPDATE messages m
    SET deal_id = (m.media_metadata->>'group_deal_id')::uuid
    WHERE m.context_type = 'group'
      AND m.message_type = 'deal'
      AND m.deal_id IS NULL
      AND m.media_metadata ? 'group_deal_id'
      AND EXISTS (SELECT 1 FROM group_deals d
                  WHERE d.id = (m.media_metadata->>'group_deal_id')::uuid)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        has_id, resolvable, total = db.execute(text(_SELECT)).one()
        print(f"{'apply' if args.apply else 'DRY RUN'}")
        print(f"  group deal cards with no deal_id : {total}")
        print(f"    carrying group_deal_id         : {has_id}")
        print(f"    resolving to a live deal       : {resolvable}")
        if total - has_id:
            print(f"    unrecoverable (no id stored)   : {total - has_id}")

        if not args.apply:
            print("\nnothing written. re-run with --apply")
            return 0

        updated = db.execute(text(_UPDATE)).rowcount
        db.commit()
        remaining = db.execute(text(_SELECT)).one()[2]
        print(f"\nbackfilled {updated}; still null: {remaining}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
