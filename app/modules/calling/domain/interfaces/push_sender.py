from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.calling.domain.entities import PushTarget


class IPushSender(ABC):
    """Data-only push delivery.

    Implementations MUST NOT raise: a push failure can never break a call.
    Callers treat push as best-effort and rely on the socket event as the fast
    path, so `send_data` returns a delivered count instead of throwing.
    """

    @abstractmethod
    def send_data(self, targets: list[PushTarget], data: dict[str, str]) -> int:
        """Deliver one data-only message to every target. Returns how many were
        accepted by the transport. Never raises."""
        ...
