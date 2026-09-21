"""GET /chat/conversations/{id}/messages must return stored translations.

The whole point of persisting translations is that scroll-back, a thread reopen
and a reconnect all show translated text. That only works if the read path
actually joins the table, which no unit test can prove — this one runs against a
real database.

Run: SYNC_DATABASE_URL=postgresql://localhost/<local_db> DB_SSLMODE=disable \
     PYTHONPATH=. python tests/test_translation_readback.py
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
from app.modules.chat.application.use_cases.get_messages import GetMessagesUseCase  # noqa: E402
from app.modules.chat.data.models import Conversation, ConversationMember, Message  # noqa: E402
from app.modules.chat.data.repository import ChatRepository  # noqa: E402
from app.modules.translation.data.models import (  # noqa: E402
    MessageTranslation,
    ReaderConversationTranslationPref,
)
from app.modules.profile.data.models import User  # noqa: E402

db = SessionLocal()
failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")


now = datetime.now(timezone.utc)
reader, sender = uuid.uuid4(), uuid.uuid4()
conv_id, msg_id = uuid.uuid4(), uuid.uuid4()

try:
    for uid in (reader, sender):
        db.add(User(id=uid, country_code="+91", phone_number=f"{uuid.uuid4().int % 10**10:010d}"))
    db.flush()  # conversations.initiator_id FKs to users
    db.add(Conversation(id=conv_id, initiator_id=sender, status="accepted"))
    db.flush()
    for uid in (reader, sender):
        db.add(ConversationMember(conversation_id=conv_id, user_id=uid))
    db.add(Message(id=msg_id, context_type="dm", context_id=conv_id, sender_id=sender,
                   message_type="text", body="namaste", sent_at=now))
    db.add(MessageTranslation(message_id=msg_id, target_lang="en", translated_text="hello"))
    db.commit()

    uc = GetMessagesUseCase(ChatRepository(db))

    # 1. continuous off -> no translation leaks into the payload
    out = uc.execute(reader, conv_id)
    check("continuous off: translated_text is null", out[0].translated_text, None)
    check("continuous off: target_lang is null", out[0].target_lang, None)

    # 2. continuous on -> the stored translation comes back
    db.add(ReaderConversationTranslationPref(
        user_id=reader, conversation_id=conv_id, target_lang="en", continuous_enabled=True))
    db.commit()
    db.expire_all()
    out = uc.execute(reader, conv_id)
    check("continuous on: translated_text served", out[0].translated_text, "hello")
    check("continuous on: target_lang served", out[0].target_lang, "en")
    check("original body untouched", out[0].body, "namaste")

    # 3. the other participant has it off -> unaffected by the reader's setting
    out = uc.execute(sender, conv_id)
    check("per-reader, not per-message", out[0].translated_text, None)

    # 4. reader wants a language we have not translated into -> null, not a crash
    db.query(ReaderConversationTranslationPref).filter_by(
        user_id=reader, conversation_id=conv_id).update({"target_lang": "ta"})
    db.commit()
    db.expire_all()
    out = uc.execute(reader, conv_id)
    check("missing language: falls back to null", out[0].translated_text, None)
finally:
    db.query(MessageTranslation).filter_by(message_id=msg_id).delete()
    db.query(ReaderConversationTranslationPref).filter_by(conversation_id=conv_id).delete()
    db.query(Message).filter_by(id=msg_id).delete()
    db.query(ConversationMember).filter_by(conversation_id=conv_id).delete()
    db.query(Conversation).filter_by(id=conv_id).delete()
    db.query(User).filter(User.id.in_([reader, sender])).delete(synchronize_session=False)
    db.commit()
    db.close()

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - stored translations reach GET /messages, scoped to the reader")
