from __future__ import annotations

from abc import ABC, abstractmethod


class ITranslationLock(ABC):
    """Stops two readers who tap Translate on the same cold item at the same
    moment from both paying for it. Best-effort: if the backing store is down
    an implementation should grant the lock — a duplicate call costs a little,
    a blocked reader costs the feature."""

    @abstractmethod
    def acquire(self, key: str, ttl_seconds: int) -> bool:
        ...

    @abstractmethod
    def release(self, key: str) -> None:
        ...
