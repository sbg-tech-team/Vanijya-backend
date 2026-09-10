"""SQLAlchemy implementation of IGroupsRepository.

The only file in the groups module that touches the database. Query bodies,
ordering, eager-load options and the JSONB `contains` semantics are moved
verbatim from the use-case files.

Transaction control stays with the caller: groups' use cases wrap multi-step
writes in try/except + rollback, so this repository exposes `commit`,
`flush`, `refresh`, `rollback`, `add` and `delete` rather than committing
inside every method.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import case, or_, text
from sqlalchemy.orm import Session, joinedload

from app.modules.groups.data.models import (
    Group, GroupActivityCache, GroupDeal, GroupEmbedding, GroupJoinRequest,
    GroupMedia, GroupMember,
)
from app.modules.groups.domain.interfaces.repository import IGroupsRepository
from app.modules.profile.data.models import Profile, Profile_Commodity


class GroupsRepository(IGroupsRepository):

    def __init__(self, db: Session):
        self.db = db

    # -- unit of work ----------------------------------------------------------

    @property
    def session(self) -> Session:
        """Escape hatch for cross-module helpers that still take a Session."""
        return self.db

    def add(self, obj) -> None: self.db.add(obj)
    def delete(self, obj) -> None: self.db.delete(obj)
    def flush(self) -> None: self.db.flush()
    def commit(self) -> None: self.db.commit()
    def rollback(self) -> None: self.db.rollback()
    def refresh(self, obj) -> None: self.db.refresh(obj)

    # -- profiles --------------------------------------------------------------

    def get_profile_by_user(self, user_id: UUID) -> Optional[Profile]:
        return (
            self.db.query(Profile)
            .options(
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.users_id == user_id)
            .first()
        )

    def get_profile_by_id(self, profile_id: int) -> Optional[Profile]:
        return self.db.query(Profile).filter(Profile.id == profile_id).first()

    def get_profiles_with_role(self, user_ids: list[UUID]) -> dict:
        rows = (
            self.db.query(Profile)
            .options(joinedload(Profile.role))
            .filter(Profile.users_id.in_(user_ids))
            .all()
        )
        return {p.users_id: p for p in rows}

    # -- groups ----------------------------------------------------------------

    def get_group(self, group_id: UUID) -> Optional[Group]:
        return self.db.query(Group).filter(Group.id == group_id).first()

    def get_group_by_invite_token(self, token: str) -> Optional[Group]:
        return self.db.query(Group).filter(Group.invite_link_token == token).first()

    def get_groups_by_ids(self, group_ids: list[UUID]) -> dict:
        return {g.id: g for g in self.db.query(Group).filter(Group.id.in_(group_ids)).all()}

    def search_groups(
        self, *, commodity: str | None, accessibility: str | None, name_q: str | None,
        region_market: str | None, target_role: str | None, page: int, per_page: int,
    ) -> tuple[list[Group], int]:
        query = self.db.query(Group)
        if commodity:
            query = query.filter(Group.commodity.contains([commodity]))
        if accessibility:
            query = query.filter(Group.accessibility == accessibility)
        if name_q:
            # search group name AND region_market so bare city names hit both
            query = query.filter(
                or_(
                    Group.name.ilike(f"%{name_q}%"),
                    Group.region_market.ilike(f"%{name_q}%"),
                )
            )
        if region_market:
            query = query.filter(Group.region_market.ilike(f"%{region_market}%"))
        if target_role:
            # JSONB contains is case-sensitive; also match the role word in the name
            query = query.filter(
                or_(
                    Group.target_roles.contains([target_role]),
                    Group.name.ilike(f"%{target_role}%"),
                )
            )
        total = query.count()
        rows = (
            query.order_by(Group.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return rows, total

    # -- membership ------------------------------------------------------------

    def get_membership(self, group_id: UUID, user_id: UUID) -> Optional[GroupMember]:
        return (
            self.db.query(GroupMember)
            .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .first()
        )

    def get_other_admin(self, group_id: UUID, user_id: UUID) -> Optional[GroupMember]:
        return (
            self.db.query(GroupMember)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id != user_id,
                GroupMember.role == "admin",
            )
            .first()
        )

    def count_members(self, group_id: UUID) -> int:
        return self.db.query(GroupMember).filter(GroupMember.group_id == group_id).count()

    def list_members(self, group_id: UUID, page: int, limit: int) -> list[GroupMember]:
        return (
            self.db.query(GroupMember)
            .filter(GroupMember.group_id == group_id)
            .order_by(
                case((GroupMember.role == "admin", 0), else_=1),
                GroupMember.joined_at.asc(),
            )
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

    def admin_group_ids(self, user_id: UUID) -> set:
        return {
            row[0]
            for row in self.db.query(GroupMember.group_id)
            .filter(GroupMember.user_id == user_id, GroupMember.role == "admin")
            .all()
        }

    def member_group_ids(self, user_id: UUID) -> set:
        return {
            row[0]
            for row in self.db.query(GroupMember.group_id)
            .filter(GroupMember.user_id == user_id)
            .all()
        }

    # -- join requests ---------------------------------------------------------

    def get_pending_join_request(self, group_id: UUID, user_id: UUID) -> Optional[GroupJoinRequest]:
        return (
            self.db.query(GroupJoinRequest)
            .filter(
                GroupJoinRequest.group_id == group_id,
                GroupJoinRequest.user_id == user_id,
                GroupJoinRequest.status == "pending",
            )
            .first()
        )

    def get_join_request(self, group_id: UUID, request_id: int) -> Optional[GroupJoinRequest]:
        return (
            self.db.query(GroupJoinRequest)
            .filter(
                GroupJoinRequest.id == request_id,
                GroupJoinRequest.group_id == group_id,
            )
            .first()
        )

    def list_join_requests(
        self, group_id: UUID, status: str | None, page: int, limit: int
    ) -> tuple[list[GroupJoinRequest], int]:
        query = self.db.query(GroupJoinRequest).filter(GroupJoinRequest.group_id == group_id)
        if status:
            query = query.filter(GroupJoinRequest.status == status)
        total = query.count()
        rows = (
            query.order_by(GroupJoinRequest.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return rows, total

    def list_join_requests_for_groups(
        self, group_ids: list, status: str | None = "pending"
    ) -> list[GroupJoinRequest]:
        query = self.db.query(GroupJoinRequest).filter(
            GroupJoinRequest.group_id.in_(group_ids)
        )
        if status:
            query = query.filter(GroupJoinRequest.status == status)
        return query.order_by(GroupJoinRequest.created_at.desc()).all()

    def list_my_join_requests(self, user_id: UUID) -> list[GroupJoinRequest]:
        return (
            self.db.query(GroupJoinRequest)
            .filter(GroupJoinRequest.user_id == user_id)
            .order_by(GroupJoinRequest.created_at.desc())
            .all()
        )

    # -- media -----------------------------------------------------------------

    def count_media(self, group_id: UUID) -> int:
        return self.db.query(GroupMedia).filter(GroupMedia.group_id == group_id).count()

    def list_media(self, group_id: UUID, page: int, limit: int) -> list[GroupMedia]:
        return (
            self.db.query(GroupMedia)
            .filter(GroupMedia.group_id == group_id)
            .order_by(GroupMedia.uploaded_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

    def get_media(self, group_id: UUID, media_id) -> Optional[GroupMedia]:
        return (
            self.db.query(GroupMedia)
            .filter(GroupMedia.id == media_id, GroupMedia.group_id == group_id)
            .first()
        )

    # -- deals -----------------------------------------------------------------

    def count_deals(self, group_id: UUID) -> int:
        return self.db.query(GroupDeal).filter(GroupDeal.group_id == group_id).count()

    def list_deals(self, group_id: UUID, page: int, limit: int) -> list[GroupDeal]:
        return (
            self.db.query(GroupDeal)
            .filter(GroupDeal.group_id == group_id)
            .order_by(GroupDeal.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

    def get_deal(self, group_id: UUID, deal_id: UUID) -> Optional[GroupDeal]:
        return (
            self.db.query(GroupDeal)
            .filter(GroupDeal.id == deal_id, GroupDeal.group_id == group_id)
            .first()
        )

    # -- embeddings / recommendations -----------------------------------------

    def upsert_embedding(self, group_id: UUID, vec) -> None:
        existing = (
            self.db.query(GroupEmbedding)
            .filter(GroupEmbedding.group_id == group_id)
            .first()
        )
        if existing:
            existing.embedding = vec
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self.db.add(GroupEmbedding(group_id=group_id, embedding=vec))

    def get_activity_cache(self, group_ids: list[UUID]) -> dict:
        return {
            a.group_id: a
            for a in self.db.query(GroupActivityCache)
            .filter(GroupActivityCache.group_id.in_(group_ids))
            .all()
        }

    def list_admin_pending_requests(
        self, admin_group_ids: list, page: int, limit: int
    ) -> tuple[list, int]:
        """(GroupJoinRequest, Group.name) rows for every group the user admins."""
        query = (
            self.db.query(GroupJoinRequest, Group.name)
            .join(Group, Group.id == GroupJoinRequest.group_id)
            .filter(
                GroupJoinRequest.group_id.in_(admin_group_ids),
                GroupJoinRequest.status == "pending",
            )
        )
        total = query.count()
        rows = (
            query.order_by(GroupJoinRequest.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return rows, total

    def raw_sql(self, sql: str, params: dict) -> list[dict]:
        """Rows as dicts. Used by the hand-written pgvector ANN query."""
        return [dict(m) for m in self.db.execute(text(sql), params).mappings().all()]
