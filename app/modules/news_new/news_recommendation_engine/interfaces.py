from typing import Protocol
from uuid import UUID


class RankerInterface(Protocol):
    async def rank(self, article_ids: list[UUID], user_id: UUID) -> list[UUID]: ...


class RecommenderInterface(Protocol):
    async def recommend(self, user_id: UUID, limit: int) -> list[UUID]: ...


class ProfileScorerInterface(Protocol):
    async def score_for_profile(self, article_id: UUID, user_id: UUID) -> float: ...
