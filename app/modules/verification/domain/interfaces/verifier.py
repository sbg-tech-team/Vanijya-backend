from __future__ import annotations

from abc import ABC, abstractmethod


class IDocumentVerifier(ABC):
    """Port for the external KYC/KYB provider (Surepass in production)."""

    @abstractmethod
    def verify(self, document_type: str, document_number: str, **kwargs) -> tuple[str, dict]:
        """Return (api_provider, api_response).

        Raises DocumentRejectedError when the provider answers but the document
        is invalid/inactive, and NotImplementedError for unsupported types.
        """
        ...
