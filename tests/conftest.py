


"""
Patches noisy startup dependencies so tests don't need a live DB or scheduler.
"""
import pathlib
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True, scope="session")
def patch_startup():
    """
    main.py's lifespan calls _scheduler.start()/.stop() (app.core.scheduler) —
    patching those two is enough; main.py no longer imports any news task
    directly (it registers routers via app.routers.register_routers and lets
    app.core.scheduler own all background job wiring, including news).
    """
    with (
        patch("app.core.scheduler.start",  MagicMock()),
        patch("app.core.scheduler.stop",   MagicMock()),
    ):
        yield


# ponytail: most files in tests/ are standalone scripts that do their work at
# import time (and sys.exit if SYNC_DATABASE_URL isn't local), which kills
# pytest collection for the whole directory. CI runs those with
# `python tests/<file>.py`; collect only the pytest-style ones here.
collect_ignore = [
    p.name
    for p in pathlib.Path(__file__).parent.glob("test_*.py")
    if 'if __name__ == "__main__"' in p.read_text()
    or "def test_" not in p.read_text()
]
