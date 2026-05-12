


"""
Patches noisy startup dependencies so tests don't need a live DB or scheduler.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True, scope="session")
def patch_startup():
    """
    main.py lifespan calls _scheduler.start() and ingest().
    - _scheduler is the module app.core.scheduler, so patching its .start/.stop works.
    - ingest is imported directly into main's namespace, so patch main.ingest.
    """
    with (
        patch("app.core.scheduler.start",  MagicMock()),
        patch("app.core.scheduler.stop",   MagicMock()),
        patch("main.ingest",               MagicMock()),
    ):
        yield
