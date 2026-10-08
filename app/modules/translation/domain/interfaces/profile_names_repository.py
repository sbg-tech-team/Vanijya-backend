from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProfileName:
    profile_id: int
    name: str
    name_i18n: Optional[dict]


class IProfileNamesRepository(ABC):
    """Reads people's names and writes generated spellings into
    profile.name_i18n. The profile module owns the row; this module only
    ever writes that one column, and only if nothing changed since it read."""

    @abstractmethod
    def profiles_missing_names(self, targets: tuple[str, ...], limit: int) -> list[ProfileName]:
        """Profiles whose name_i18n lacks a target language not already
        marked failed — candidates only; the caller decides precisely."""
        ...

    @abstractmethod
    def get(self, profile_id: int) -> Optional[ProfileName]:
        ...

    @abstractmethod
    def save_if_unchanged(self, before: ProfileName, name_i18n: dict) -> bool:
        """Write name_i18n only if the profile's name and name_i18n are still
        what `before` read — never over an edit the owner made meanwhile.
        True if written."""
        ...
