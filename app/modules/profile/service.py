import asyncio
import os
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.shared.utils.storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
    delete_object,
    ext_for,
    generate_signed_upload_url,
    object_exists,
    path_from_url,
    public_url,
)

_STORAGE_BUCKET = os.environ.get("DATABASE_STORAGE_BUCKET", "avatars")

from app.modules.connections.models import UserConnection, MessageRequest

from app.modules.profile.models import (
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
from app.modules.post.models import Post
from app.modules.profile.schemas import (
    CommodityOut,
    InterestOut,
    ProfileCreate,
    ProfilePublicResponse,
    ProfileResponse,
    ProfileUpdate,
    UserCreate,
    UserResponse,
)
from app.modules.connections.encoding.vector import build_candidate_vector

# Maps profile.role_id → lowercase string used by the vector encoder
_ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}

# Fields in ProfileUpdate that affect the IS vector
_EMBEDDING_FIELDS = {"commodities", "latitude", "longitude", "quantity_min", "quantity_max"}


class ProfileConflictError(Exception):
    pass

class ProfileNotFoundError(Exception):
    pass

class ProfileValidationError(Exception):
    pass

class ProfileStorageUnavailableError(Exception):
    pass

class UserConflictError(Exception):
    pass


def _uniq(ids: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(ids))


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

def create_user(db: Session, user_id: UUID, payload: UserCreate) -> UserResponse:
    existing = db.query(User).filter(User.id == user_id).first()
    if existing:
        return UserResponse(
            id=existing.id,
            phone_number=existing.phone_number,
            country_code=existing.country_code,
            created_at=existing.created_at,
        )

    if db.query(User.id).filter(
        User.country_code == payload.country_code,
        User.phone_number == payload.phone_number,
    ).first():
        raise UserConflictError("Phone number already registered")

    try:
        user = User(
            id=user_id,
            country_code=payload.country_code,
            phone_number=payload.phone_number,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserResponse(
            id=user.id,
            phone_number=user.phone_number,
            country_code=user.country_code,
            created_at=user.created_at,
        )
    except Exception:
        db.rollback()
        raise


def store_access_token(db: Session, user_id: UUID, token: str) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ProfileNotFoundError("User not found")
    user.access_token = token
    db.commit()


def get_access_token(db: Session, user_id: UUID) -> str | None:
    row = db.query(User.access_token).filter(User.id == user_id).first()
    return row[0] if row else None


def update_fcm_token(db: Session, user_id: UUID, fcm_token: str) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ProfileNotFoundError("User not found")
    user.fcm_token = fcm_token
    db.commit()


def get_profile_id_for_user(db: Session, user_id: UUID) -> int:
    row = db.query(Profile.id).filter(Profile.users_id == user_id).first()
    if not row:
        raise ProfileNotFoundError("Profile not found for this user")
    return row[0]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_role(db: Session, role_id: int) -> None:
    if not db.query(Role.id).filter(Role.id == role_id).first():
        raise ProfileValidationError(
            f"Invalid role_id: {role_id}. Use 1=Trader, 2=Broker, 3=Exporter."
        )


def _validate_ids(db: Session, model, ids: list[int], field_name: str) -> list[int]:
    ids = _uniq(ids)
    if not ids:
        return []
    found = {row[0] for row in db.query(model.id).filter(model.id.in_(ids)).all()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ProfileValidationError(f"Invalid {field_name}: {missing}")
    return ids


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_profile_for_user(db: Session, user_id: UUID) -> Profile | None:
    return (
        db.query(Profile)
        .options(
            joinedload(Profile.user),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
            joinedload(Profile.interests).joinedload(Profile_Interest.interest),
            joinedload(Profile.business),
        )
        .filter(Profile.users_id == user_id)
        .first()
    )


def _to_response(profile: Profile, posts_count: int = 0) -> ProfileResponse:
    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        role_id=profile.role_id,
        phone_number=profile.user.phone_number,
        country_code=profile.user.country_code,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        posts_count=posts_count,
        commodities=[CommodityOut.model_validate(pc.commodity) for pc in profile.commodities],
        interests=[InterestOut.model_validate(pi.interest) for pi in profile.interests],
        business_name=profile.business.business_name,
        city=profile.business.city,
        state=profile.business.state,
        latitude=profile.business.latitude,
        longitude=profile.business.longitude,
        avatar_url=profile.avatar_url,
    )


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _upsert_user_embedding(db: Session, user_id: UUID) -> None:
    """
    Rebuild the 11-dim IS vector for a user profile and upsert into user_embeddings.
    Called after profile create and after updates that touch embedding-relevant fields.
    Does NOT commit — caller owns the transaction.
    """
    profile = _load_profile_for_user(db, user_id)
    if not profile:
        return

    commodity_names = [pc.commodity.name.lower() for pc in profile.commodities]
    role_str = _ROLE_ID_TO_NAME.get(profile.role_id, "trader")

    vec = build_candidate_vector(
        commodity_list=commodity_names,
        role=role_str,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    existing = db.query(UserEmbedding).filter(UserEmbedding.user_id == user_id).first()
    if existing:
        existing.is_vector = vec
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(UserEmbedding(user_id=user_id, is_vector=vec))


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def create_profile(db: Session, user_id: UUID, payload: ProfileCreate) -> ProfileResponse:
    if not db.query(User.id).filter(User.id == user_id).first():
        raise ProfileNotFoundError("User not found — create user first via POST /profile/user")

    if db.query(Profile.id).filter(Profile.users_id == user_id).first():
        raise ProfileConflictError("Profile already exists for this user")

    if payload.quantity_min > payload.quantity_max:
        raise ProfileValidationError("quantity_min cannot be greater than quantity_max")

    _validate_role(db, payload.role_id)
    commodity_ids = _validate_ids(db, Commodity, payload.commodities, "commodity_ids")
    interest_ids = _validate_ids(db, Interest, payload.interests, "interest_ids")

    try:
        profile = Profile(
            users_id=user_id,
            role_id=payload.role_id,
            name=payload.name.strip(),
            quantity_min=payload.quantity_min,
            quantity_max=payload.quantity_max,
        )
        db.add(profile)
        db.flush()

        db.add(Business(
            profile_id=profile.id,
            business_name=payload.business_name.strip() if payload.business_name else None,
            city=payload.city.strip() if payload.city else None,
            state=payload.state.strip() if payload.state else None,
            latitude=payload.latitude,
            longitude=payload.longitude,
        ))

        if commodity_ids:
            db.add_all([
                Profile_Commodity(profile_id=profile.id, commodity_id=c_id)
                for c_id in commodity_ids
            ])
        if interest_ids:
            db.add_all([
                Profile_Interest(profile_id=profile.id, interest_id=i_id)
                for i_id in interest_ids
            ])

        db.commit()

        # Build and persist the 11-dim IS vector (single extra commit)
        _upsert_user_embedding(db, user_id)
        db.commit()

        loaded_profile = _load_profile_for_user(db, user_id)
        if not loaded_profile:
            raise ProfileNotFoundError("Profile not found")
        return _to_response(loaded_profile, posts_count=0)
    except Exception:
        db.rollback()
        raise


def get_my_profile(db: Session, user_id: UUID) -> ProfileResponse:
    profile = _load_profile_for_user(db, user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found")
    posts_count = (
        db.query(func.count(Post.id)).filter(Post.profile_id == profile.id).scalar() or 0
    )
    return _to_response(profile, posts_count=posts_count)


_BUSINESS_FIELDS = {"business_name", "city", "state", "latitude", "longitude"}


def update_profile(db: Session, user_id: UUID, payload: ProfileUpdate) -> ProfileResponse:
    profile = (
        db.query(Profile)
        .options(joinedload(Profile.business))
        .filter(Profile.users_id == user_id)
        .first()
    )
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    data = payload.model_dump(exclude_unset=True)

    qmin = data.get("quantity_min", profile.quantity_min)
    qmax = data.get("quantity_max", profile.quantity_max)
    if qmin and qmax and qmin > qmax:
        raise ProfileValidationError("quantity_min cannot exceed quantity_max")

    for field, value in data.items():
        if field not in _BUSINESS_FIELDS and field not in ("commodities", "interests"):
            setattr(profile, field, value)

    business_data = {k: v for k, v in data.items() if k in _BUSINESS_FIELDS}
    if business_data:
        for field, value in business_data.items():
            setattr(profile.business, field, value)

    if "commodities" in data:
        current = {pc.commodity_id for pc in profile.commodities}
        requested = set(data["commodities"])
        to_remove = current - requested
        to_add = requested - current
        if to_remove:
            db.query(Profile_Commodity).filter(
                Profile_Commodity.profile_id == profile.id,
                Profile_Commodity.commodity_id.in_(to_remove),
            ).delete(synchronize_session=False)
        for c_id in to_add:
            db.add(Profile_Commodity(profile_id=profile.id, commodity_id=c_id))

    if "interests" in data:
        current = {pi.interest_id for pi in profile.interests}
        requested = set(data["interests"])
        to_remove = current - requested
        to_add = requested - current
        if to_remove:
            db.query(Profile_Interest).filter(
                Profile_Interest.profile_id == profile.id,
                Profile_Interest.interest_id.in_(to_remove),
            ).delete(synchronize_session=False)
        for i_id in to_add:
            db.add(Profile_Interest(profile_id=profile.id, interest_id=i_id))

    db.commit()

    # Rebuild vector if any embedding-relevant field was updated
    if _EMBEDDING_FIELDS & set(data.keys()):
        _upsert_user_embedding(db, user_id)
        db.commit()

    profile_resp = _load_profile_for_user(db, user_id)
    assert profile_resp is not None
    posts_count = (
        db.query(func.count(Post.id)).filter(Post.profile_id == profile_resp.id).scalar() or 0
    )
    return _to_response(profile_resp, posts_count=posts_count)


def delete_profile(db: Session, user_id: UUID) -> None:
    profile = db.query(Profile).filter(Profile.users_id == user_id).first()
    if not profile:
        raise ProfileNotFoundError("Profile not found")
    try:
        db.delete(profile)
        db.commit()
    except Exception:
        db.rollback()
        raise


def delete_user(db: Session, user_id: UUID) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ProfileNotFoundError("User not found")
    try:
        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_profile_by_id(
    db: Session, profile_id: int, viewer_user_id: UUID | None = None
) -> ProfilePublicResponse:
    profile = (
        db.query(Profile)
        .options(
            joinedload(Profile.business),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.id == profile_id)
        .first()
    )
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    posts_count = (
        db.query(func.count(Post.id)).filter(Post.profile_id == profile_id).scalar() or 0
    )

    is_following = False
    message_request_status = None
    if viewer_user_id and viewer_user_id != profile.users_id:
        is_following = db.query(UserConnection).filter(
            UserConnection.follower_id == viewer_user_id,
            UserConnection.following_id == profile.users_id,
        ).first() is not None

        msg_req = db.query(MessageRequest).filter(
            (
                (MessageRequest.sender_id == viewer_user_id) &
                (MessageRequest.receiver_id == profile.users_id)
            ) | (
                (MessageRequest.sender_id == profile.users_id) &
                (MessageRequest.receiver_id == viewer_user_id)
            )
        ).first()
        if msg_req:
            message_request_status = msg_req.status

    return ProfilePublicResponse(
        id=profile.id,
        name=profile.name,
        role_id=profile.role_id,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        commodities=[CommodityOut.model_validate(pc.commodity) for pc in profile.commodities],
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        posts_count=posts_count,
        business_name=profile.business.business_name,
        city=profile.business.city,
        state=profile.business.state,
        latitude=profile.business.latitude,
        longitude=profile.business.longitude,
        avatar_url=profile.avatar_url,
        is_following=is_following,
        message_request_status=message_request_status,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Avatar upload
# ---------------------------------------------------------------------------

async def get_avatar_upload_url(db: Session, profile_id: int, content_type: str) -> dict:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ProfileValidationError(
            f"Unsupported type '{content_type}'. Allowed: image/jpeg, image/png, image/webp."
        )

    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    path = f"{profile_id}{ext_for(content_type)}"

    # Clear any existing file at this path so Supabase won't reject with "Duplicate"
    try:
        await delete_object(_STORAGE_BUCKET, path)
    except StorageError:
        pass

    try:
        result = await generate_signed_upload_url(_STORAGE_BUCKET, path)
    except StorageError as e:
        raise ProfileValidationError(str(e))

    return {
        **result,
        "avatar_url": public_url(_STORAGE_BUCKET, path),
        "content_type": content_type,
    }


async def save_avatar_url(db: Session, profile_id: int, avatar_url: str) -> dict:
    # Validate URL and ownership before any DB hit
    try:
        path = path_from_url(_STORAGE_BUCKET, avatar_url)
    except StorageError:
        raise ProfileValidationError("avatar_url does not belong to the avatars storage bucket")

    stem = path.rsplit(".", 1)[0]
    if stem != str(profile_id):
        raise ProfileValidationError("Avatar does not belong to this profile")

    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    # Verify with retry; distinguish infra failure from missing file
    result = None
    for delay in (0.15, 0.35):
        result = await object_exists(_STORAGE_BUCKET, path)
        if result is True or result is None:
            break
        await asyncio.sleep(delay)
    else:
        result = await object_exists(_STORAGE_BUCKET, path)

    if result is None:
        raise ProfileStorageUnavailableError("Storage verification temporarily unavailable")
    if result is not True:
        raise ProfileValidationError(
            "Avatar image not found in storage — complete the upload before saving"
        )

    # If the extension changed (e.g. PNG → JPG), delete the old orphaned file.
    if profile.avatar_url and profile.avatar_url != avatar_url:
        try:
            old_path = path_from_url(_STORAGE_BUCKET, profile.avatar_url)
            new_path = path_from_url(_STORAGE_BUCKET, avatar_url)
            if old_path != new_path:
                await delete_object(_STORAGE_BUCKET, old_path)
        except StorageError:
            pass

    profile.avatar_url = avatar_url
    db.commit()
    return {"avatar_url": avatar_url}
