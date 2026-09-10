from sqlalchemy.orm import Session

from app.modules.post.data.models import Post
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.domain.exceptions import PostNotFoundError, PostForbiddenError
from app.modules.profile.data.models import Profile
from app.modules.post.recommendation import service as rec_service
from app.shared.utils.storage import StorageError, delete_object, path_from_url

import os

_POST_STORAGE_BUCKET = os.environ.get("POST_STORAGE_BUCKET", "posts")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _active_profile_ids(repo: IPostRepository) -> list[int]:
    return repo.active_profile_ids()


def _get_post_or_raise(repo: IPostRepository, post_id: int) -> Post:
    post = repo.get_active_post(post_id)
    if not post:
        raise PostNotFoundError(f"Post {post_id} not found")
    return post


# ----------------------------------------------------------------------------
# Delete post
# ----------------------------------------------------------------------------

async def delete_post(repo: IPostRepository, post_id: int, profile_id: int) -> None:
    post = _get_post_or_raise(repo, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only delete your own posts")

    image_urls = post.image_urls or []

    try:
        rec_service.remove_post_index(repo.session, post_id)
    except Exception:
        pass

    repo.delete(post)
    repo.commit()

    for url in image_urls:
        try:
            old_path = path_from_url(_POST_STORAGE_BUCKET, url)
            await delete_object(_POST_STORAGE_BUCKET, old_path)
        except StorageError:
            pass
