"""Chat contract test — 15 routes restored, boot blocker gone, no dead duplicate socket manager.
    python3.12 _migration/test_chat.py
"""
import _boot  # noqa: F401
import inspect, os, subprocess, sys

from app.modules.chat.data.repository import ChatRepository
from app.modules.chat.domain.interfaces.repository import IChatRepository
from app.modules.chat.domain.value_objects import ConversationStatus
from app.modules.chat.presentation.router import router

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

# --- all 15 app_old routes present, including the 2 that had been deleted -----
check("route set", sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes), sorted([
    "POST /chat/conversations", "GET /chat/all", "GET /chat/groups",
    "GET /chat/conversations", "GET /chat/presence",
    "GET /chat/conversations/{conv_id}/messages", "POST /chat/conversations/{conv_id}/messages",
    "POST /chat/conversations/{conv_id}/read", "POST /chat/conversations/{conv_id}/deals",
    "POST /chat/media/upload-url", "DELETE /chat/messages/{message_id}",
    "GET /chat/share/recipients", "GET /chat/groups/{group_id}/messages",
    "POST /chat/groups/{group_id}/messages", "POST /chat/groups/{group_id}/deals"]))

# --- /chat/groups must be matched before /chat/groups/{id}/... ----------------
paths = [r.path for r in router.routes]
check("/chat/groups declared before /chat/groups/{group_id}/messages",
      paths.index("/chat/groups") < paths.index("/chat/groups/{group_id}/messages"), True)

# --- the restored DM opener ----------------------------------------------------
check("get_or_create_dm restored on the repository", hasattr(ChatRepository, "get_or_create_dm"), True)
check("get_or_create_dm signature",
      str(inspect.signature(ChatRepository.get_or_create_dm)).replace("'", ""),
      "(self, user_id: UUID, target_user_id: UUID) -> dict")

# --- boot blocker: ConvStatus is gone, ConversationStatus is the real name ----
out = subprocess.run("grep -rn ConvStatus ../app --include='*.py'",
                     shell=True, capture_output=True, text=True).stdout.strip()
check("no ConvStatus references anywhere", out, "")
check("ConversationStatus has ACTIVE/BLOCKED",
      (hasattr(ConversationStatus, "ACTIVE"), hasattr(ConversationStatus, "BLOCKED")), (True, True))

# --- the byte-identical duplicate socket manager is gone ----------------------
check("dead socket/ package removed", os.path.exists("../app/modules/chat/presentation/socket"), False)
check("connection_manager still present",
      os.path.exists("../app/modules/chat/presentation/connection_manager.py"), True)

# --- repository is behind the interface ---------------------------------------
check("ChatRepository implements IChatRepository", issubclass(ChatRepository, IChatRepository), True)
check("no unimplemented abstract methods", sorted(ChatRepository.__abstractmethods__), [])
check("IChatRepository is non-trivial", len(IChatRepository.__abstractmethods__) >= 15, True)

# --- attachments really are loaded (GAP_ANALYSIS CH-4 claimed they never are) --
src = open("../app/modules/chat/data/repository.py").read()
check("ChatAttachment is queried", "query(ChatAttachment)" in src, True)

# --- layering -------------------------------------------------------------------
def count(cmd): return int(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip() or 0)
check("no db.query in chat application layer",
      count("grep -rl 'db\\.query' ../app/modules/chat/application | wc -l"), 0)
check("no 0-byte stubs left in chat",
      count("find ../app/modules/chat -name '*.py' -size 0 -not -name '__init__.py' | wc -l"), 0)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - chat contract matches app_old (15 routes incl. 2 restored, ConvStatus fixed, dupe manager gone, IChatRepository)")
