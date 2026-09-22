# Compatibility shim — all logic now lives in individual use case files.
# Existing imports from this module continue to work unchanged.

from app.modules.profile.application.use_cases.rebuild_embedding import (
    _upsert_user_embedding,
)
from app.modules.profile.application.use_cases.notification_prefs import (  # noqa: F401
    get_notification_prefs,
    update_notification_prefs,
)
from app.modules.profile.application.use_cases.create_profile import (
    _uniq,
    _validate_role,
    _to_response,
    create_user,
    store_access_token,
    get_access_token,
    update_fcm_token,
    get_profile_id_for_user,
    delete_user,
    create_profile,
)
from app.modules.profile.application.use_cases.get_profile import (
    get_my_profile,
    delete_profile,
    get_profile_by_id,
    get_profile_by_user_id,
)
from app.modules.profile.application.use_cases.update_profile import (
    _BUSINESS_FIELDS,
    _EMBEDDING_FIELDS,
    update_profile,
)
from app.modules.profile.application.use_cases.upload_photo import (
    _STORAGE_BUCKET,
    get_avatar_upload_url,
    save_avatar_url,
)

# Re-export domain exceptions under the names used by the original service.py
from app.modules.profile.domain.exceptions import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileValidationError,
    ProfileStorageUnavailableError,
    UserConflictError,
)

__all__ = [
    # helpers
    "_uniq",
    "_validate_role",
    "_to_response",
    "_upsert_user_embedding",
    "_BUSINESS_FIELDS",
    "_EMBEDDING_FIELDS",
    "_STORAGE_BUCKET",
    # user
    "create_user",
    "store_access_token",
    "get_access_token",
    "update_fcm_token",
    "get_notification_prefs",
    "update_notification_prefs",
    "get_profile_id_for_user",
    "delete_user",
    # profile CRUD
    "create_profile",
    "get_my_profile",
    "update_profile",
    "delete_profile",
    "get_profile_by_id",
    "get_profile_by_user_id",
    # avatar
    "get_avatar_upload_url",
    "save_avatar_url",
    # exceptions
    "ProfileConflictError",
    "ProfileNotFoundError",
    "ProfileValidationError",
    "ProfileStorageUnavailableError",
    "UserConflictError",
]
