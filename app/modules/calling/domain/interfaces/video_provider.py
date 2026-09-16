from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.calling.domain.entities import StreamCredentials


class IVideoProvider(ABC):
    """Media-layer provider. Stream is the only implementation today.

    The provider issues join credentials and terminates sessions. Call state,
    permission and history all live in our database — keeping this surface small
    is what makes the vendor replaceable.
    """

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """False when credentials are absent. Callers surface 503 rather than
        letting a missing env var raise deep in the stack."""
        ...

    @abstractmethod
    def new_call_id(self, call_id: UUID) -> tuple[str, str]:
        """Return (call_type, call_id) as the provider addresses this call."""
        ...

    @abstractmethod
    def issue_token(
        self,
        user_id: UUID,
        stream_call_type: str,
        stream_call_id: str,
    ) -> StreamCredentials:
        """Mint a short-lived token scoped to one user and one call."""
        ...

    @abstractmethod
    def provision_call(
        self,
        stream_call_type: str,
        stream_call_id: str,
        created_by_id: UUID,
        max_duration_seconds: int,
    ) -> bool:
        """Create the call provider-side with a hard duration cap.

        The cap is the one guardrail that still works when OUR backend is down:
        the provider removes all participants and ends the session on its own
        once the limit is hit, so a forgotten call cannot bill indefinitely.

        Returns True on success. Must not raise — a provisioning failure
        degrades to "client creates the call on join", which still works but
        loses the provider-side cap, so callers log it loudly.
        """
        ...

    @abstractmethod
    def end_call_remote(self, stream_call_type: str, stream_call_id: str) -> bool:
        """Terminate the session provider-side for everyone.

        Ending a call in our database does NOT stop the provider billing: the
        media session runs until the last participant disconnects. Any path that
        terminalises a call must call this, or a client stuck in a pocket keeps
        the meter running.

        Returns True if the provider accepted the termination. Must not raise.
        """
        ...
