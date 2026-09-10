from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env", override=True)

import asyncio
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

SIGNED_URL_TTL_SECONDS = 300


class StorageError(Exception):
    pass


_client: Client = create_client(
    os.environ["DATABASE_STORAGE_URL"],
    os.environ["DATABASE_SERVICE_KEY"],
)


async def generate_signed_upload_url(bucket: str, path: str) -> dict:
    try:
        result = await asyncio.to_thread(
            _client.storage.from_(bucket).create_signed_upload_url, path
        )
    except Exception as e:
        raise StorageError(f"Supabase failed to issue upload URL: {e}")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=SIGNED_URL_TTL_SECONDS)
    ).isoformat()

    return {"upload_url": result["signed_url"], "expires_at": expires_at}


def public_url(bucket: str, path: str) -> str:
    return _client.storage.from_(bucket).get_public_url(path).rstrip("?")


def ext_for(content_type: str) -> str:
    return _CONTENT_TYPE_EXT.get(content_type, ".jpg")


def path_from_url(bucket: str, url: str) -> str:
    """Extract the storage object path from a Supabase public bucket URL."""
    marker = f"/storage/v1/object/public/{bucket}/"
    idx = url.find(marker)
    if idx == -1:
        raise StorageError(f"URL does not belong to bucket '{bucket}'")
    # supabase-py appends a trailing '?' to public URLs — strip it
    return url[idx + len(marker):].rstrip("?")


async def object_exists(bucket: str, path: str) -> bool | None:
    """
    True  = file exists
    False = file not found (404)
    None  = infra/network error — caller should return 503
    """
    url = public_url(bucket, path)

    def _head() -> bool | None:
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            return False if e.code < 500 else None
        except (urllib.error.URLError, Exception):
            return None

    return await asyncio.to_thread(_head)


async def delete_object(bucket: str, path: str) -> None:
    """Remove a single object from the bucket."""
    try:
        await asyncio.to_thread(
            _client.storage.from_(bucket).remove, [path]
        )
    except Exception as e:
        raise StorageError(f"Supabase failed to delete object: {e}")
