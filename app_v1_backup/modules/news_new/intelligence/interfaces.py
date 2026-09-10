from typing import Protocol
from uuid import UUID


class EnricherInterface(Protocol):
    """
    The combined enrichment backend used today: one call returns classification
    + summary + impact as a dict. GroqEnricher implements this. Swap in any
    backend (Gemini/custom) without touching the service.
    """
    model: str

    def enrich(self, text: str) -> dict: ...


# ── Per-aspect protocols (future: if enrichment is split into separate calls) ──

class ClassifierInterface(Protocol):
    async def classify(self, article_id: UUID) -> dict: ...


class SummarizerInterface(Protocol):
    async def summarize(self, article_id: UUID) -> dict: ...


class ImpactGeneratorInterface(Protocol):
    async def generate_impact(self, article_id: UUID) -> dict: ...


class RoleScorerInterface(Protocol):
    async def score_for_role(self, article_id: UUID, role_id: int) -> float: ...
