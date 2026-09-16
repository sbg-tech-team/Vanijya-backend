from __future__ import annotations

import logging

import asyncio
import os

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
from app.modules.profile.domain.exceptions import (
    ProfileNotFoundError,
    ProfileStorageUnavailableError,
    ProfileValidationError,
)
from app.modules.profile.domain.interfaces.repository import IProfileRepository

log = logging.getLogger(__name__)

_STORAGE_BUCKET = os.environ.get("DATABASE_STORAGE_BUCKET", "avatars")


async def get_avatar_upload_url(repo: IProfileRepository, profile_id: int, content_type: str) -> dict:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ProfileValidationError(
            f"Unsupported type '{content_type}'. Allowed: image/jpeg, image/png, image/webp."
        )

    profile = repo.get_profile_by_id(profile_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    path = f"{profile_id}{ext_for(content_type)}"

    # Clear any existing file at this path so Supabase won't reject with "Duplicate"
    try:
        await delete_object(_STORAGE_BUCKET, path)
    except StorageError:
        log.warning("could not delete avatar object %s", path)

    try:
        result = await generate_signed_upload_url(_STORAGE_BUCKET, path)
    except StorageError as e:
        raise ProfileValidationError(str(e))

    return {
        **result,
        "avatar_url": public_url(_STORAGE_BUCKET, path),
        "content_type": content_type,
    }


async def save_avatar_url(repo: IProfileRepository, profile_id: int, avatar_url: str) -> dict:
    try:
        path = path_from_url(_STORAGE_BUCKET, avatar_url)
    except StorageError:
        raise ProfileValidationError("avatar_url does not belong to the avatars storage bucket")

    stem = path.rsplit(".", 1)[0]
    if stem != str(profile_id):
        raise ProfileValidationError("Avatar does not belong to this profile")

    profile = repo.get_profile_by_id(profile_id)
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

    # If the extension changed (e.g. PNG → JPG), delete the orphaned old file.
    if profile.avatar_url and profile.avatar_url != avatar_url:
        try:
            old_path = path_from_url(_STORAGE_BUCKET, profile.avatar_url)
            new_path = path_from_url(_STORAGE_BUCKET, avatar_url)
            if old_path != new_path:
                await delete_object(_STORAGE_BUCKET, old_path)
        except StorageError:
            # Orphaned object — the profile points at the new one either way.
            log.warning("could not delete replaced avatar %s", profile.avatar_url)

    repo.update_avatar_url(profile_id, avatar_url)
    return {"avatar_url": avatar_url}
