"""
Compatibility shim — re-exports everything from individual use case modules.

Existing code that imports from this module continues to work unchanged.
New code should import directly from the specific use case module:

  from app.modules.groups.application.use_cases.create_group import create_group
  from app.modules.groups.application.use_cases.manage_members import join_group
  from app.modules.groups.application.use_cases.get_group_suggestions import get_group_suggestions
  from app.modules.groups.application.use_cases.manage_posts import create_group_deal
"""
from __future__ import annotations

# Domain exceptions — re-exported so callers that do
#   `from ...service import GroupNotFoundError` keep working.
# The old service.py defined its own exception classes; we now alias
# them to the canonical domain exceptions.
from app.modules.groups.domain.exceptions import (
    GroupNotFoundError,
    GroupAlreadyMemberError as GroupConflictError,
    GroupPermissionError,
    GroupValidationError,
    GroupStorageError,
)

from app.modules.groups.application.use_cases.record_view import (  # noqa: F401
    MODULE as _MODULE,
    record_group_view,
)

# Internal helpers — re-exported for any code that imported them directly.
from app.modules.groups.application.use_cases.create_group import (
    _get_profile_or_raise,
    _get_group_or_raise,
    _get_membership,
    _require_admin,
    _require_member,
    _build_group_out,
    _store_embedding,
    _parse_group_search_intent,
    _GROUP_IMAGE_BUCKET,
)

# Group CRUD + image upload
from app.modules.groups.application.use_cases.create_group import (
    create_group,
    list_groups,
    get_group,
    update_group,
    update_permissions,
    delete_group,
    get_group_image_upload_url,
)

# Membership + invite links + join-request lifecycle
from app.modules.groups.application.use_cases.manage_members import (
    join_group,
    leave_group,
    get_members,
    add_members,
    remove_member,
    set_member_frozen,
    toggle_mute,
    toggle_favorite,
    get_or_create_invite_link,
    join_by_invite_link,
    get_join_requests,
    resolve_join_request,
    get_my_admin_pending_requests,
)

# Group recommendation engine
from app.modules.groups.application.use_cases.get_group_suggestions import (
    get_group_suggestions,
    ROLE_ID_TO_NAME,
    TOP_K,
)

# Group media + deals
from app.modules.groups.application.use_cases.manage_posts import (
    get_group_media_upload_url,
    list_group_media,
    delete_group_media,
    create_group_deal,
    list_group_deals,
    get_group_deal,
    update_group_deal,
    close_group_deal,
    publish_group_deal,
    ALLOWED_MEDIA_TYPES,
    _deal_to_response,
    _create_post_from_deal,
    _insert_deal_chat_card,
)

__all__ = [
    "record_group_view",
    # exceptions
    "GroupNotFoundError",
    "GroupConflictError",
    "GroupPermissionError",
    "GroupValidationError",
    "GroupStorageError",
    # helpers
    "_get_profile_or_raise",
    "_get_group_or_raise",
    "_get_membership",
    "_require_admin",
    "_require_member",
    "_build_group_out",
    "_store_embedding",
    "_parse_group_search_intent",
    "ALLOWED_MEDIA_TYPES",
    "_GROUP_IMAGE_BUCKET",
    # CRUD
    "create_group",
    "list_groups",
    "get_group",
    "update_group",
    "update_permissions",
    "delete_group",
    "get_group_image_upload_url",
    # membership
    "join_group",
    "leave_group",
    "get_members",
    "add_members",
    "remove_member",
    "set_member_frozen",
    "toggle_mute",
    "toggle_favorite",
    "get_or_create_invite_link",
    "join_by_invite_link",
    "get_join_requests",
    "resolve_join_request",
    "get_my_admin_pending_requests",
    # recommendations
    "get_group_suggestions",
    "ROLE_ID_TO_NAME",
    "TOP_K",
    # media + deals
    "get_group_media_upload_url",
    "list_group_media",
    "delete_group_media",
    "create_group_deal",
    "list_group_deals",
    "get_group_deal",
    "update_group_deal",
    "close_group_deal",
    "publish_group_deal",
    "_deal_to_response",
    "_create_post_from_deal",
    "_insert_deal_chat_card",
]
