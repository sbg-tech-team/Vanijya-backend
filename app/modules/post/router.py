from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.post.schemas import PostCreate, PostUpdate, CommentCreate, FollowingFeedResponse, CommentFeedResponse, FeedPostCard
from app.modules.post import service
from app.shared.utils.response import ok

router = APIRouter(prefix="/posts", tags=["Posts"])


# ----------------------------------------------------------------------------
# Image upload
# ----------------------------------------------------------------------------

@router.post("/upload-image")
async def get_post_upload_url_api(
    profile_id: int = Depends(get_current_profile_id),
    content_type: str = Query(..., description="image/jpeg | image/png | image/webp"),
):
    """
    Step 1 of 3 — get a signed upload URL.
    Step 2: PUT the image bytes directly to upload_url (Content-Type must match).
    Step 3: POST /posts/ with the returned image_url in the body.
    """
    try:
        result = await service.get_post_upload_url(profile_id, content_type)
        return ok(result, "Upload URL generated")
    except service.PostImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------------------------------------------------------------------------
# Post CRUD
# ----------------------------------------------------------------------------

@router.post("/", status_code=201)
async def create_post_api(
    payload: PostCreate,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = await service.create_post(db, profile_id, payload)
        return ok(result, "Post created successfully")
    except service.PostImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.PostStorageUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


# @router.get("/")
# def get_feed_api(
#     profile_id: int = Depends(get_current_profile_id),
#     limit: int = 20,
#     offset: int = 0,
#     db: Session = Depends(get_db),
# ):
#     result = service.get_feed(db, profile_id, limit, offset)
#     return ok(result, "Feed fetched successfully")


@router.get("/mine")
def get_my_posts_api(
    profile_id: int = Depends(get_current_profile_id),
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    result = service.get_my_posts(db, profile_id, limit, offset)
    return ok(result, "Posts fetched successfully")


@router.get("/following", response_model=FollowingFeedResponse)
def get_following_feed_api(
    profile_id: int = Depends(get_current_profile_id),
    limit: int = 20,
    cursor: int | None = None,
    db: Session = Depends(get_db),
):
    return service.get_following_feed(db, profile_id, limit, cursor)


@router.get("/saved", response_model=list[FeedPostCard])
def get_saved_posts_api(
    profile_id: int = Depends(get_current_profile_id),
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    result = service.get_saved_posts(db, profile_id, limit, offset)
    return ok(result, "Saved posts fetched successfully")


@router.get("/{post_id}")
def get_post_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.get_post(db, post_id, profile_id)
        return ok(result, "Post fetched successfully")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{post_id}")
def update_post_api(
    post_id: int,
    payload: PostUpdate,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.update_post(db, post_id, profile_id, payload)
        return ok(result, "Post updated successfully")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.PostForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{post_id}", status_code=204)
async def delete_post_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        await service.delete_post(db, post_id, profile_id)
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.PostForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ----------------------------------------------------------------------------
# Likes
# ----------------------------------------------------------------------------

@router.post("/{post_id}/like")
def toggle_like_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.toggle_like(db, post_id, profile_id)
        return ok(result, "Like toggled")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------------

@router.get("/{post_id}/comments", response_model=CommentFeedResponse)
def get_comments_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    limit: int = 20,
    cursor: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        return service.get_comments(db, post_id, limit, cursor)
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{post_id}/comments", status_code=201)
def add_comment_api(
    post_id: int,
    payload: CommentCreate,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.add_comment(db, post_id, profile_id, payload)
        return ok(result, "Comment added successfully")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.CommentsDisabledError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{post_id}/comments/{comment_id}", status_code=204)
def delete_comment_api(
    post_id: int,
    comment_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        service.delete_comment(db, post_id, comment_id, profile_id)
    except service.CommentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.CommentForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ----------------------------------------------------------------------------
# Shares
# ----------------------------------------------------------------------------

@router.post("/{post_id}/share")
def record_share_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.record_share(db, post_id, profile_id)
        return ok(result, "Share recorded")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------------------------------------------------------------------
# Saves
# ----------------------------------------------------------------------------

@router.post("/{post_id}/save")
def toggle_save_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.toggle_save(db, post_id, profile_id)
        return ok(result, "Save toggled")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------------------------------------------------------------------
# Deal close / reopen
# ----------------------------------------------------------------------------

@router.post("/{post_id}/close")
def toggle_deal_closed_api(
    post_id: int,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    try:
        result = service.toggle_deal_closed(db, post_id, profile_id)
        return ok(result, "Deal status toggled")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.PostForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
