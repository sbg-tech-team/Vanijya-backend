"""Follower counts must agree with the follow rows, and role casing must not
depend on which endpoint you ask.

Both were live bugs on the Followers screen: the profile header said 3
followers while /followers returned 2, and the same role field came back
"trader" in the list and "Trader" in the header.

The count was an integer column on `profile` kept in step by hand in
add_follow / remove_follow — correct only while every write goes through those
two methods. Seeding and load-test cleanup wrote user_connections directly, so
15 of 91 production profiles disagreed with their rows, one by 762,373.

Run: SYNC_DATABASE_URL=postgresql://localhost/<local_db> DB_SSLMODE=disable \
     PYTHONPATH=. python tests/test_follow_counts.py
"""
import os
import sys
import uuid
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_url = os.environ.get("SYNC_DATABASE_URL", "")
if not any(h in _url for h in ("localhost", "127.0.0.1")):
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402 — registers every model on the metadata
from sqlalchemy import text  # noqa: E402

from app.core.database.session import SessionLocal  # noqa: E402
from app.modules.connections.application.formatters import fmt_profile  # noqa: E402
from app.modules.connections.data.models import UserConnection  # noqa: E402
from app.modules.connections.data.repository import ConnectionsRepository  # noqa: E402
from app.modules.profile.data.models import Business, Profile, User  # noqa: E402
from app.modules.profile.data.repository import ProfileRepository  # noqa: E402

db = SessionLocal()
failures = []
made_users, made_profiles = [], []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")


def make_profile(name):
    uid = uuid.uuid4()
    db.add(User(id=uid, country_code="+91",
                phone_number=f"{uuid.uuid4().int % 10**10:010d}"))
    db.flush()
    p = Profile(users_id=uid, role_id=1, name=name,
                quantity_min=Decimal(1), quantity_max=Decimal(10))
    db.add(p)
    db.flush()
    db.add(Business(profile_id=p.id, business_name=f"{name} Co",
                    city="Pune", state="MH", latitude=18.52, longitude=73.85))
    db.flush()
    made_users.append(uid)
    made_profiles.append(p.id)
    return p


try:
    target = make_profile("Counted Target")
    a, b, c = (make_profile(f"Follower {i}") for i in range(3))
    db.commit()

    prof_repo = ProfileRepository(db)
    conn_repo = ConnectionsRepository(db)

    def stored():
        # with_follow_counts is opt-in: a profile lookup happens on nearly
        # every news and group request, and those never read these numbers.
        return prof_repo.get_profile_by_id(
            target.id, with_follow_counts=True).followers_count

    check("no followers yet", stored(), 0)

    for f in (a, b):
        conn_repo.add_follow(f.users_id, target.users_id)
    check("two follows counted", stored(), 2)

    # The drift that caused the bug: a row written without going through
    # add_follow. The count must still be right.
    db.add(UserConnection(follower_id=c.users_id, following_id=target.users_id))
    db.commit()
    check("row inserted directly is still counted", stored(), 3)
    check("count matches the rows the list endpoint returns",
          stored(),
          db.query(UserConnection).filter(
              UserConnection.following_id == target.users_id).count())

    # ...and a row deleted behind the API's back
    db.query(UserConnection).filter(
        UserConnection.follower_id == c.users_id,
        UserConnection.following_id == target.users_id).delete()
    db.commit()
    check("row deleted directly is no longer counted", stored(), 2)

    conn_repo.remove_follow(a.users_id, target.users_id)
    check("unfollow counted", stored(), 1)

    # following_count is the other direction
    check("following_count counts outgoing",
          prof_repo.get_profile_by_id(b.id, with_follow_counts=True).following_count, 1)

    # Not asking for them costs no query and returns 0 — deliberate, so the
    # hot lookups do not pay for numbers they never render.
    check("counts are not computed unless asked",
          prof_repo.get_profile_by_id(target.id).followers_count, 0)

    # ── role casing ─────────────────────────────────────────────────────────
    row = db.query(Profile).filter(Profile.id == target.id).first()
    formatted = fmt_profile(row)
    check("list role uses the stored casing", formatted["role"], "Trader")
    check("list role is not lowercased", formatted["role"] == "trader", False)
    check("matches what the roles table holds",
          formatted["role"],
          db.execute(text("select name from roles where id = 1")).scalar())
finally:
    db.query(UserConnection).filter(
        UserConnection.follower_id.in_(made_users)).delete(synchronize_session=False)
    db.query(UserConnection).filter(
        UserConnection.following_id.in_(made_users)).delete(synchronize_session=False)
    db.query(Business).filter(
        Business.profile_id.in_(made_profiles)).delete(synchronize_session=False)
    db.query(Profile).filter(
        Profile.id.in_(made_profiles)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(made_users)).delete(synchronize_session=False)
    db.commit()
    db.close()

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - follow counts derived from rows, role casing consistent")
