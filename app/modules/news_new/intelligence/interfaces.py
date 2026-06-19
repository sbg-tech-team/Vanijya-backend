from typing import Protocol
from uuid import UUID


class ClassifierInterface(Protocol):
    async def classify(self, article_id: UUID) -> dict: ...


class SummarizerInterface(Protocol):
    async def summarize(self, article_id: UUID) -> dict: ...


class ImpactGeneratorInterface(Protocol):
    async def generate_impact(self, article_id: UUID) -> dict: ...


class RoleScorerInterface(Protocol):
    async def score_for_role(self, article_id: UUID, role_id: int) -> float: ...
