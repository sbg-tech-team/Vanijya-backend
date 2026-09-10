# Compatibility shim — re-exports everything from individual use case files so
# that existing code importing from service.py continues to work unchanged.
#
# Storage / media helpers (get_chat_media_upload_url, delete_chat_media,
# ALLOWED_CHAT_MEDIA_TYPES, ChatMediaUploadError, ChatStorageUnavailableError)
# live in this file because they are infrastructure concerns, not use-case classes.
# All use-case classes are delegated to their own modules below.

import os
import uuid
from uuid import UUID

from app.shared.utils.storage import (
    StorageError,
    delete_object,
    generate_signed_upload_url,
    public_url,
)
from app.modules.chat.domain.exceptions import (
    ChatMediaUploadError,
    ChatStorageUnavailableError,
)

# Re-export all use case classes so callers that do
#   from app.modules.chat.application.use_cases.service import SomeUseCase
# keep working without modification.
from app.modules.chat.application.use_cases.create_conversation import (  # noqa: F401
    CreatePersonalDealUseCase,
)
from app.modules.chat.application.use_cases.send_message import (  # noqa: F401
    SendMessageUseCase,
    SendGroupMessageUseCase,
)
from app.modules.chat.application.use_cases.get_messages import (  # noqa: F401
    GetConversationsUseCase,
    GetMessagesUseCase,
    GetGroupMessagesUseCase,
    GetAllChatsUseCase,
    GetShareRecipientsUseCase,
)
from app.modules.chat.application.use_cases.list_group_chats import (  # noqa: F401
    GetGroupConversationsUseCase,
)
from app.modules.chat.application.use_cases.mark_delivered import (  # noqa: F401
    MarkReadUseCase,
    DeleteMessageUseCase,
)

_CHAT_STORAGE_BUCKET = os.environ.get("CHAT_STORAGE_BUCKET", "chat")

# Chat supports more than images — storage.ext_for only knows images, so chat
# carries its own allowlist + extension map.
ALLOWED_CHAT_MEDIA_TYPES = frozenset({
    "image/jpeg", "image/png", "image/webp",
    "video/mp4", "video/quicktime", "video/webm",
    "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg",
    "application/pdf",
})

_CHAT_MEDIA_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/webm": ".weba",
    "audio/ogg": ".ogg",
    "application/pdf": ".pdf",
}


async def get_chat_media_upload_url(user_id: UUID, content_type: str) -> dict:
    """
    Step 1 of 3 — issue a signed upload URL for chat media.
    Step 2: client PUTs the bytes directly to upload_url (Content-Type must match).
    Step 3: client sends the message with the returned media_url in media_urls.
    Scoped per-user; path = {user_id}/{uuid}.{ext}.
    """
    if content_type not in ALLOWED_CHAT_MEDIA_TYPES:
        raise ChatMediaUploadError(
            f"Unsupported type '{content_type}'. Allowed: "
            "image/jpeg, image/png, image/webp, video/mp4, video/quicktime, "
            "video/webm, audio/mpeg, audio/mp4, audio/webm, audio/ogg, application/pdf."
        )

    path = f"{user_id}/{uuid.uuid4()}{_CHAT_MEDIA_EXT[content_type]}"

    try:
        result = await generate_signed_upload_url(_CHAT_STORAGE_BUCKET, path)
    except StorageError as e:
        raise ChatStorageUnavailableError(str(e))

    return {
        **result,
        "media_url": public_url(_CHAT_STORAGE_BUCKET, path),
        "content_type": content_type,
    }


async def delete_chat_media(storage_paths: list[str]) -> None:
    """Best-effort cleanup of orphaned chat media after a message is deleted.
    Runs in a background task — never let a storage failure surface to the client."""
    for path in storage_paths:
        try:
            await delete_object(_CHAT_STORAGE_BUCKET, path)
        except StorageError:
            continue
