"""Notification switches must be enforced by the server, not the client.

The Settings toggles wrote to SharedPreferences and nothing read them, so
turning one off changed nothing. The client-side alternative on the table was
deleting the FCM token, which also deregisters the device for calls — a
"market alerts off" switch that silently stops the phone ringing. So the check
lives in CallingRepository.push_targets, the one method both push call sites
route through.

Run: SYNC_DATABASE_URL=postgresql://localhost/<local_db> DB_SSLMODE=disable \
     PYTHONPATH=. python tests/test_notification_prefs.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_url = os.environ.get("SYNC_DATABASE_URL", "")
if not any(h in _url for h in ("localhost", "127.0.0.1")):
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402 — registers every model on the metadata
from app.core.database.session import SessionLocal  # noqa: E402
from app.modules.calling.data.repository import CallingRepository  # noqa: E402
from app.modules.profile.data.models import NotificationPreferences, User  # noqa: E402
from app.modules.profile.data.repository import ProfileRepository  # noqa: E402

db = SessionLocal()
failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")


now = datetime.now(timezone.utc)
uid = uuid.uuid4()

try:
    db.add(User(id=uid, country_code="+91",
                phone_number=f"{uuid.uuid4().int % 10**10:010d}"))
    db.commit()

    calls = CallingRepository(db)
    prof = ProfileRepository(db)
    calls.register_device(uid, f"tok-{uid}", "android", now)
    db.commit()

    def n(category="push"):
        return len(calls.push_targets([uid], category))

    # 1. no row at all — the existing behaviour for everyone who never opened
    #    Settings. Must not be treated as "off".
    check("no row: default is all on", prof.get_notification_prefs(uid).push_enabled, True)
    check("no row: push delivered", n(), 1)

    # 2. master off silences everything, calls included
    prof.set_notification_prefs(uid, push_enabled=False)
    check("master off: push blocked", n(), 0)
    check("master off: group blocked too", n("group"), 0)

    # 3. master back on, group off — group is silenced, calls are not
    prof.set_notification_prefs(uid, push_enabled=True, group_enabled=False)
    check("group off: group blocked", n("group"), 0)
    check("group off: 1:1 call still rings", n(), 1)
    check("group off: market_alerts unaffected", n("market_alerts"), 1)

    # 4. partial update leaves untouched switches alone — the client sends only
    #    the toggle the user moved
    prof.set_notification_prefs(uid, market_alerts_enabled=False)
    p = prof.get_notification_prefs(uid)
    check("partial: group still off", p.group_enabled, False)
    check("partial: push still on", p.push_enabled, True)
    check("partial: market_alerts now off", p.market_alerts_enabled, False)
    check("market_alerts off: blocked", n("market_alerts"), 0)
    check("market_alerts off: calls still ring", n(), 1)
finally:
    db.query(NotificationPreferences).filter_by(user_id=uid).delete()
    from app.modules.calling.data.models import UserDevice
    db.query(UserDevice).filter_by(user_id=uid).delete()
    db.query(User).filter_by(id=uid).delete()
    db.commit()
    db.close()

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - notification preferences enforced server-side at the send site")
