from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modules.profile.data.models import (
    NotificationPreferences,
    Business,
    Commodity,
    Interest,
    Profile,
    Profile_Commodity,
    Profile_Interest,
    Role,
    User,
    UserEmbedding,
)
from app.modules.profile.domain.entities import (
    NotificationPrefs,
    BusinessEntity,
    CommodityEntity,
    InterestEntity,
    ProfileCommodityEntity,
    ProfileEntity,
    ProfileInterestEntity,
    UserEntity,
)
from app.modules.profile.domain.exceptions import ProfileNotFoundError
from app.modules.profile.domain.interfaces.repository import IProfileRepository

from app.modules.connections.data.models import MessageRequest, UserConnection
from app.modules.post.data.models import Post


# ---------------------------------------------------------------------------
# ORM → domain entity mappers
# ---------------------------------------------------------------------------

def _to_user_entity(user: User) -> UserEntity:
    return UserEntity(
        id=user.id,
        country_code=user.country_code,
        phone_number=user.phone_number,
        is_active=user.is_active,
        created_at=user.created_at,
        fcm_token=user.fcm_token,
        access_token=user.access_token,
    )


def _to_profile_entity(profile: Profile) -> ProfileEntity:
    business = None
    if profile.business:
        business = BusinessEntity(
            id=profile.business.id,
            profile_id=profile.business.profile_id,
            latitude=profile.business.latitude,
            longitude=profile.business.longitude,
            business_name=profile.business.business_name,
            city=profile.business.city,
            state=profile.business.state,
        )

    commodities = []
    for pc in profile.commodities:
        commodity_entity = None
        if pc.commodity:
            commodity_entity = CommodityEntity(id=pc.commodity.id, name=pc.commodity.name)
        commodities.append(ProfileCommodityEntity(
            id=pc.id,
            profile_id=pc.profile_id,
            commodity_id=pc.commodity_id,
            commodity=commodity_entity,
        ))

    interests = []
    for pi in profile.interests:
        interest_entity = None
        if pi.interest:
            interest_entity = InterestEntity(id=pi.interest.id, name=pi.interest.name)
        interests.append(ProfileInterestEntity(
            id=pi.id,
            profile_id=pi.profile_id,
            interest_id=pi.interest_id,
            interest=interest_entity,
        ))

    user_entity = _to_user_entity(profile.user) if profile.user else None

    return ProfileEntity(
        id=profile.id,
        users_id=profile.users_id,
        role_id=profile.role_id,
        name=profile.name,
        quantity_min=profile.quantity_min,
        quantity_max=profile.quantity_max,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        avatar_url=profile.avatar_url,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        business=business,
        commodities=commodities,
        interests=interests,
        user=user_entity,
    )


# ---------------------------------------------------------------------------
# Repository implementation
# ---------------------------------------------------------------------------

class ProfileRepository(IProfileRepository):

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---- User ---------------------------------------------------------------

    def get_user(self, user_id: UUID) -> UserEntity | None:
        row = self._db.query(User).filter(User.id == user_id).first()
        return _to_user_entity(row) if row else None

    def phone_number_exists(self, country_code: str, phone_number: str) -> bool:
        return self._db.query(User.id).filter(
            User.country_code == country_code,
            User.phone_number == phone_number,
        ).first() is not None

    def create_user(self, user_id: UUID, phone_number: str, country_code: str) -> UserEntity:
        try:
            user = User(id=user_id, country_code=country_code, phone_number=phone_number)
            self._db.add(user)
            self._db.commit()
            self._db.refresh(user)
            return _to_user_entity(user)
        except Exception:
            self._db.rollback()
            raise

    def delete_user(self, user_id: UUID) -> None:
        user = self._db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ProfileNotFoundError("User not found")
        try:
            self._db.delete(user)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def get_access_token(self, user_id: UUID) -> str | None:
        row = self._db.query(User.access_token).filter(User.id == user_id).first()
        return row[0] if row else None

    def store_access_token(self, user_id: UUID, token: str) -> None:
        user = self._db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ProfileNotFoundError("User not found")
        user.access_token = token
        self._db.commit()

    def update_fcm_token(self, user_id: UUID, fcm_token: str) -> None:
        user = self._db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ProfileNotFoundError("User not found")
        user.fcm_token = fcm_token

        # Also record it as a device. users.fcm_token holds one token, so on its
        # own a user with a phone and a tablet would only ever ring on whichever
        # registered last — calling needs every device. The column is still
        # written for anything else that reads it.
        # Upsert on the token: a handset handed to another account must ring the
        # new owner, not the previous one.
        from app.modules.calling.data.models import UserDevice

        now = datetime.now(timezone.utc)
        self._db.execute(
            pg_insert(UserDevice)
            .values(id=uuid4(), user_id=user_id, fcm_token=fcm_token, last_seen_at=now, created_at=now)
            .on_conflict_do_update(
                index_elements=["fcm_token"],
                set_={"user_id": user_id, "last_seen_at": now},
            )
        )
        self._db.commit()

    # ---- Profile — lookups --------------------------------------------------

    def get_profile_for_user(self, user_id: UUID) -> ProfileEntity | None:
        profile = (
            self._db.query(Profile)
            .options(
                joinedload(Profile.user),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
                joinedload(Profile.interests).joinedload(Profile_Interest.interest),
                joinedload(Profile.business),
            )
            .filter(Profile.users_id == user_id)
            .first()
        )
        return _to_profile_entity(profile) if profile else None

    def get_profile_by_id(self, profile_id: int) -> ProfileEntity | None:
        profile = (
            self._db.query(Profile)
            .options(
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.id == profile_id)
            .first()
        )
        return _to_profile_entity(profile) if profile else None

    def get_profile_by_user_id(self, user_id: UUID) -> ProfileEntity | None:
        profile = (
            self._db.query(Profile)
            .options(
                joinedload(Profile.business),
                joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            )
            .filter(Profile.users_id == user_id)
            .first()
        )
        return _to_profile_entity(profile) if profile else None

    def get_profile_id_for_user(self, user_id: UUID) -> int | None:
        row = self._db.query(Profile.id).filter(Profile.users_id == user_id).first()
        return row[0] if row else None

    def user_has_profile(self, user_id: UUID) -> bool:
        return self._db.query(Profile.id).filter(Profile.users_id == user_id).first() is not None

    # ---- Profile — mutations ------------------------------------------------

    def create_profile(
        self,
        user_id: UUID,
        role_id: int,
        name: str,
        qty_min: Decimal,
        qty_max: Decimal,
        business_name: str | None,
        city: str | None,
        state: str | None,
        latitude: float,
        longitude: float,
        commodity_ids: list[int],
        interest_ids: list[int],
    ) -> None:
        try:
            profile = Profile(
                users_id=user_id,
                role_id=role_id,
                name=name,
                quantity_min=qty_min,
                quantity_max=qty_max,
            )
            self._db.add(profile)
            self._db.flush()

            self._db.add(Business(
                profile_id=profile.id,
                business_name=business_name,
                city=city,
                state=state,
                latitude=latitude,
                longitude=longitude,
            ))
            if commodity_ids:
                self._db.add_all([
                    Profile_Commodity(profile_id=profile.id, commodity_id=c)
                    for c in commodity_ids
                ])
            if interest_ids:
                self._db.add_all([
                    Profile_Interest(profile_id=profile.id, interest_id=i)
                    for i in interest_ids
                ])
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def update_profile(
        self,
        user_id: UUID,
        scalar_fields: dict,
        business_fields: dict,
        commodity_to_add: set[int],
        commodity_to_remove: set[int],
        interest_to_add: set[int],
        interest_to_remove: set[int],
    ) -> None:
        profile = (
            self._db.query(Profile)
            .options(joinedload(Profile.business))
            .filter(Profile.users_id == user_id)
            .first()
        )
        if not profile:
            raise ProfileNotFoundError("Profile not found")

        for field, value in scalar_fields.items():
            setattr(profile, field, value)

        if business_fields and profile.business:
            for field, value in business_fields.items():
                setattr(profile.business, field, value)

        if commodity_to_remove:
            self._db.query(Profile_Commodity).filter(
                Profile_Commodity.profile_id == profile.id,
                Profile_Commodity.commodity_id.in_(commodity_to_remove),
            ).delete(synchronize_session=False)
        for c_id in commodity_to_add:
            self._db.add(Profile_Commodity(profile_id=profile.id, commodity_id=c_id))

        if interest_to_remove:
            self._db.query(Profile_Interest).filter(
                Profile_Interest.profile_id == profile.id,
                Profile_Interest.interest_id.in_(interest_to_remove),
            ).delete(synchronize_session=False)
        for i_id in interest_to_add:
            self._db.add(Profile_Interest(profile_id=profile.id, interest_id=i_id))

        self._db.commit()

    def delete_profile(self, user_id: UUID) -> None:
        profile = self._db.query(Profile).filter(Profile.users_id == user_id).first()
        if not profile:
            raise ProfileNotFoundError("Profile not found")
        try:
            self._db.delete(profile)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def update_avatar_url(self, profile_id: int, avatar_url: str) -> None:
        profile = self._db.query(Profile).filter(Profile.id == profile_id).first()
        if not profile:
            raise ProfileNotFoundError("Profile not found")
        profile.avatar_url = avatar_url
        self._db.commit()

    # ---- Lookup-table validation --------------------------------------------

    def role_exists(self, role_id: int) -> bool:
        return self._db.query(Role.id).filter(Role.id == role_id).first() is not None

    def find_missing_commodity_ids(self, ids: list[int]) -> list[int]:
        found = {row[0] for row in self._db.query(Commodity.id).filter(Commodity.id.in_(ids)).all()}
        return [i for i in ids if i not in found]

    def find_missing_interest_ids(self, ids: list[int]) -> list[int]:
        found = {row[0] for row in self._db.query(Interest.id).filter(Interest.id.in_(ids)).all()}
        return [i for i in ids if i not in found]

    # ---- Embeddings ---------------------------------------------------------

    def upsert_embedding(
        self,
        user_id: UUID,
        is_vector: list[float],
        post_feed_vector: list[float],
    ) -> None:
        existing = self._db.query(UserEmbedding).filter(UserEmbedding.user_id == user_id).first()
        if existing:
            existing.is_vector = is_vector
            existing.post_feed_vector = post_feed_vector
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self._db.add(UserEmbedding(
                user_id=user_id,
                is_vector=is_vector,
                post_feed_vector=post_feed_vector,
            ))
        self._db.commit()

    # ---- Cross-module data --------------------------------------------------

    def count_posts_for_profile(self, profile_id: int) -> int:
        return self._db.query(func.count(Post.id)).filter(Post.profile_id == profile_id).scalar() or 0

    def get_follow_status(self, follower_user_id: UUID, following_user_id: UUID) -> bool:
        return self._db.query(UserConnection).filter(
            UserConnection.follower_id == follower_user_id,
            UserConnection.following_id == following_user_id,
        ).first() is not None

    def get_message_request_status(self, user_a_id: UUID, user_b_id: UUID) -> str | None:
        row = self._db.query(MessageRequest).filter(
            (
                (MessageRequest.sender_id == user_a_id) &
                (MessageRequest.receiver_id == user_b_id)
            ) | (
                (MessageRequest.sender_id == user_b_id) &
                (MessageRequest.receiver_id == user_a_id)
            )
        ).first()
        return row.status if row else None

    def get_profile_posts_feed(
        self,
        profile_id: int,
        cursor: int | None,
        limit: int,
    ) -> tuple[list, int | None, int]:
        post_query = (
            self._db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(Post.profile_id == profile_id)
        )
        if cursor is not None:
            post_query = post_query.filter(Post.id < cursor)
        posts = post_query.order_by(Post.id.desc()).limit(limit).all()
        next_cursor = posts[-1].id if len(posts) == limit else None
        return posts, next_cursor, len(posts)


    # ── Notification preferences ─────────────────────────────────────────────

    def get_notification_prefs(self, user_id: UUID) -> NotificationPrefs:
        row = self._db.get(NotificationPreferences, user_id)
        if row is None:
            return NotificationPrefs()  # never opened Settings: everything on
        return NotificationPrefs(
            push_enabled=row.push_enabled,
            market_alerts_enabled=row.market_alerts_enabled,
            group_enabled=row.group_enabled,
        )

    def set_notification_prefs(
        self,
        user_id: UUID,
        push_enabled: bool | None = None,
        market_alerts_enabled: bool | None = None,
        group_enabled: bool | None = None,
    ) -> NotificationPrefs:
        """Partial update: None means "leave this one alone", so a client can
        send only the switch the user actually touched."""
        row = self._db.get(NotificationPreferences, user_id)
        if row is None:
            row = NotificationPreferences(user_id=user_id)
            self._db.add(row)
        if push_enabled is not None:
            row.push_enabled = push_enabled
        if market_alerts_enabled is not None:
            row.market_alerts_enabled = market_alerts_enabled
        if group_enabled is not None:
            row.group_enabled = group_enabled
        self._db.commit()
        return NotificationPrefs(
            push_enabled=row.push_enabled,
            market_alerts_enabled=row.market_alerts_enabled,
            group_enabled=row.group_enabled,
        )
