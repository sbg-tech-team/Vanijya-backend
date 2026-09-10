


"""
Patches noisy startup dependencies so tests don't need a live DB or scheduler.
"""
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
