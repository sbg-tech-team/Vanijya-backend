# Compatibility shim — imports from individual use case files.
# Existing code that imports from this module continues to work unchanged.

from app.modules.post.application.use_cases.create_post import (
    get_post_upload_url,
    create_post,
)
from app.modules.post.application.use_cases.update_post import (
    update_post,
)
from app.modules.post.application.use_cases.delete_post import (
    delete_post,
)
from app.modules.post.application.use_cases.get_post import (
    get_post,
    get_feed,
    get_my_posts,
    get_following_feed,
    get_saved_posts,
    _record_view,
    _batch_post_responses,
    batch_feed_cards,
    _batch_my_post_cards,
    _score_following_posts,
)
from app.modules.post.application.use_cases.interact_post import (
    toggle_like,
    add_comment,
    get_comments,
    delete_comment,
    record_share,
    send_post,
    toggle_save,
    toggle_deal_closed,
)
from app.modules.post.application.use_cases.mark_seen import (
    mark_seen,
)

# Re-export domain exceptions under their legacy names so any code that did
# "from ... service import PostNotFoundError" keeps working.
from app.modules.post.domain.exceptions import (
    PostNotFoundError,
    PostForbiddenError,
    CommentNotFoundError,
    CommentForbiddenError,
    CommentsDisabledError,
    PostImageUploadError,
    PostStorageUnavailableError,
)

__all__ = [
    # image upload
    "get_post_upload_url",
    # CRUD
    "create_post",
    "get_post",
    "update_post",
    "delete_post",
    # feeds
    "get_feed",
    "get_my_posts",
    "get_following_feed",
    "get_saved_posts",
    # interactions
    "toggle_like",
    "add_comment",
    "get_comments",
    "delete_comment",
    "record_share",
    "send_post",
    "toggle_save",
    "toggle_deal_closed",
    # seen
    "mark_seen",
    # exceptions (legacy re-exports)
    "PostNotFoundError",
    "PostForbiddenError",
    "CommentNotFoundError",
    "CommentForbiddenError",
    "CommentsDisabledError",
    "PostImageUploadError",
    "PostStorageUnavailableError",
    # internal helpers (kept for any code that imported them directly)
    "_record_view",
    "_batch_post_responses",
    "batch_feed_cards",
    "_batch_my_post_cards",
    "_score_following_posts",
]
