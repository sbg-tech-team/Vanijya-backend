"""The viewer's app language for the current request.

The app sends `X-App-Language` (e.g. "hi") on every request. RequestLanguage
middleware reads it once and keeps it for the rest of that request, so code
building a response — in any module, at any depth — can show people's names
in the viewer's language without the header being threaded through every
function signature.

A ContextVar is per request: concurrent requests never see each other's
value, and FastAPI carries it into the threadpool that runs sync endpoints.

Outside a request (scheduled jobs, pushes to another user) it is None —
code there must pass the recipient's language explicitly.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_viewer_language: ContextVar[Optional[str]] = ContextVar("viewer_language", default=None)

_HEADER = b"x-app-language"


def get_viewer_language() -> Optional[str]:
    return _viewer_language.get()


def _parse(raw: Optional[str]) -> Optional[str]:
    """'hi', 'HI', 'hi-IN', 'hi_IN' -> 'hi'. Two to three letters or None —
    an unknown code is harmless: no name is stored under it, so the name as
    typed is shown."""
    if not raw:
        return None
    code = raw.strip().replace("_", "-").split("-")[0].lower()
    return code if 2 <= len(code) <= 3 and code.isalpha() else None


class RequestLanguageMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware), so the value is set in the same
    context the endpoint runs in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = None
        for name, value in scope.get("headers") or []:
            if name == _HEADER:
                raw = value.decode("latin-1")
                break
        token = _viewer_language.set(_parse(raw))
        try:
            await self.app(scope, receive, send)
        finally:
            _viewer_language.reset(token)


@contextmanager
def no_viewer_language():
    """Build something that will be PUSHED to other people (a chat message on
    their socket, a share delivered to their inbox) inside this block: the
    request's language belongs to the sender, so names inside it are kept as
    their owners typed them instead of in the sender's language."""
    token = _viewer_language.set(None)
    try:
        yield
    finally:
        _viewer_language.reset(token)


@contextmanager
def viewer_language(lang: Optional[str]):
    """Build something for ONE specific other person in their language — e.g.
    the incoming-call screen sent to a callee — using their saved app
    language rather than the requester's."""
    token = _viewer_language.set(lang)
    try:
        yield
    finally:
        _viewer_language.reset(token)
