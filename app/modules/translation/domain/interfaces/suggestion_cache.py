from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ISuggestionCache(ABC):
    """Shared, durable-for-a-while cache of name spellings. Best-effort: an
    implementation that cannot reach its store returns None / does nothing."""

    @abstractmethod
    def get(self, key: str) -> Optional[list[str]]:
        ...

    @abstractmethod
    def set(self, key: str, value: list[str], ttl_seconds: int) -> None:
        ...
