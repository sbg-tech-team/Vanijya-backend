"""Import-time bootstrap so app_new can be imported without a DB, Firebase or Supabase.

Stubs only third-party SDKs that app_new initialises at import time; all app code
under test is the real thing.  Import this FIRST in every migration test.
"""
import os, sys, types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkgroot"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("SYNC_DATABASE_URL", "postgresql://u:p@localhost/db")
os.environ.setdefault("DATABASE_STORAGE_URL", "https://stub.supabase.co")
os.environ.setdefault("DATABASE_SERVICE_KEY", "stub-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-in-production")

_cred = types.SimpleNamespace(Certificate=lambda *a, **k: object())
_auth = types.SimpleNamespace(verify_id_token=lambda *a, **k: {})
_fb = types.ModuleType("firebase_admin")
_fb.App, _fb.credentials, _fb.auth = object, _cred, _auth
_fb.get_app = lambda *a, **k: object()
_fb.initialize_app = lambda *a, **k: object()

# python-socketio: real project dep, absent locally. AsyncServer is only
# constructed at import time; nothing in the contract tests emits.
_sio = types.ModuleType("socketio")
class _AsyncServer:
    def __init__(self, *a, **k): pass
    def event(self, f=None, **k): return f if f else (lambda g: g)
    def on(self, *a, **k): return lambda f: f
    async def emit(self, *a, **k): pass
    async def enter_room(self, *a, **k): pass
    async def leave_room(self, *a, **k): pass
    def rooms(self, *a, **k): return []
    class manager:  # noqa: N801
        rooms = {}
_sio.AsyncServer = _AsyncServer
_sio.ASGIApp = lambda *a, **k: None
_sio.AsyncRedisManager = lambda *a, **k: None

# apscheduler: real project dep, absent locally.
_aps = types.ModuleType("apscheduler")
_aps_sched = types.ModuleType("apscheduler.schedulers")
_aps_bg = types.ModuleType("apscheduler.schedulers.background")
class _BackgroundScheduler:
    def __init__(self, *a, **k): self.jobs = []
    def add_job(self, fn, trigger=None, **k): self.jobs.append((getattr(fn, "__name__", str(fn)), k.get("id")))
    def start(self, *a, **k): pass
    def shutdown(self, *a, **k): pass
_aps_bg.BackgroundScheduler = _BackgroundScheduler

# google-genai (Gemini): real project dep, absent locally.
import importlib.machinery
_google = sys.modules.get("google") or types.ModuleType("google")
if not hasattr(_google, "__path__"): _google.__path__ = []
_genai = types.ModuleType("google.genai")
class _Client:
    def __init__(self, *a, **k): self.models = types.SimpleNamespace(generate_content=lambda *a, **k: None)
_genai.Client = _Client
_genai.types = types.SimpleNamespace(GenerateContentConfig=lambda *a, **k: None)
_google.genai = _genai

_sb = types.ModuleType("supabase")
_sb.create_client = lambda *a, **k: object()
_sb.Client = object

for name, mod in [("google", _google), ("google.genai", _genai), ("firebase_admin", _fb), ("firebase_admin.credentials", _cred),
                  ("firebase_admin.auth", _auth), ("supabase", _sb), ("socketio", _sio), ("apscheduler", _aps),
                  ("apscheduler.schedulers", _aps_sched),
                  ("apscheduler.schedulers.background", _aps_bg),
                  ("google", _google), ("google.genai", _genai)]:
    sys.modules.setdefault(name, mod)


def import_all_modules():
    """Import every module package fresh. Returns {name: None | exception}."""
    names = ["profile", "onboarding", "post", "chat", "connections", "groups",
             "news", "home_feed", "deeplink", "verification", "safety"]
    out = {}
    for m in names:
        for k in [k for k in list(sys.modules) if k.startswith("app.")]:
            del sys.modules[k]
        try:
            __import__("app.modules." + m); out[m] = None
        except Exception as e:
            out[m] = e
    return out
