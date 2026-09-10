from __future__ import annotations

from abc import ABC, abstractmethod


class IFirebaseVerifier(ABC):
    """Port for Firebase phone-OTP ID token verification."""

    @abstractmethod
    def verify_id_token(self, firebase_id_token: str) -> dict:
        """Return the decoded claims. Raise InvalidFirebaseTokenError if unusable."""
        ...
