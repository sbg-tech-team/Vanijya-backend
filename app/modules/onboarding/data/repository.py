"""SQLAlchemy implementation of IOnboardingRepository.

Only file in the onboarding module that touches the database. Queries are
ported from app_old/modules/auth (service.py and router.py — app_old ran the
user/profile lookups directly inside the router).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.onboarding.data.models import UserSession
from app.modules.onboarding.domain.entities import DevProfileRef, SessionRef, UserRef
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository
from app.modules.profile.data.models import Profile, User


class OnboardingRepository(IOnboardingRepository):

    def __init__(self, db: Session):
        self.db = db

    # -- users ----------------------------------------------------------------

    def find_user_by_phone(self, country_code: str, phone_number: str) -> UserRef | None:
        user = (
            self.db.query(User)
            .filter(User.country_code == country_code, User.phone_number == phone_number)
            .first()
        )
        if user is None:
            return None
        return UserRef(
            user_id=user.id,
            profile_id=user.profile.id if user.profile is not None else None,
        )

    def get_profile_id_for_user(self, user_id: UUID) -> int | None:
        row = self.db.query(Profile.id).filter(Profile.users_id == user_id).first()
        return row[0] if row else None

    def find_profile_by_name(self, name: str) -> DevProfileRef | None:
        profile = self.db.query(Profile).filter(Profile.name.ilike(name)).first()
        if profile is None:
            return None
        return DevProfileRef(profile_id=profile.id, user_id=profile.users_id, name=profile.name)

    # -- sessions -------------------------------------------------------------

    def add_session(
        self,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        device_info: str | None,
        ip_address: str | None,
    ) -> None:
        self.db.add(
            UserSession(
                id=session_id,
                user_id=user_id,
                refresh_token_hash=refresh_token_hash,
                expires_at=expires_at,
                is_active=True,
                device_info=device_info,
                ip_address=ip_address,
            )
        )
        self.db.commit()

    def get_active_session_by_refresh_hash(self, token_hash: str) -> SessionRef | None:
        session = (
            self.db.query(UserSession)
            .filter(
                UserSession.refresh_token_hash == token_hash,
                UserSession.is_active.is_(True),
            )
            .first()
        )
        if session is None:
            return None
        return SessionRef(
            session_id=session.id, user_id=session.user_id, expires_at=session.expires_at
        )

    def rotate_refresh_token(
        self, session_id: UUID, new_hash: str, last_used_at: datetime
    ) -> None:
        session = self.db.query(UserSession).filter(UserSession.id == session_id).first()
        if session:
            session.refresh_token_hash = new_hash
            session.last_used_at = last_used_at
            self.db.commit()

    def deactivate_session(self, session_id: UUID) -> None:
        session = self.db.query(UserSession).filter(UserSession.id == session_id).first()
        if session:
            session.is_active = False
            self.db.commit()

    def deactivate_all_sessions(self, user_id: UUID) -> None:
        self.db.query(UserSession).filter(
            UserSession.user_id == user_id,
            UserSession.is_active.is_(True),
        ).update({"is_active": False})
        self.db.commit()
