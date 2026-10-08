from __future__ import annotations

from abc import ABC, abstractmethod


class IRejectionMemo(ABC):
    """Remembers, for a while, that a message's translation into a language
    was rejected by the checks — so continuous mode and its recovery job do
    not keep paying for a translation that keeps coming back bad.
    Best-effort: an implementation that cannot reach its store should report
    "not seen" (a retry costs a little; never translating costs the feature)."""

    @abstractmethod
    def seen(self, key: str) -> bool:
        ...

    @abstractmethod
    def remember(self, key: str, ttl_seconds: int) -> None:
        ...
