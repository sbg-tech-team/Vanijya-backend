from __future__ import annotations

from uuid import UUID

from app.modules.profile.application.schemas import (
    CommodityOut,
    ProfilePublicResponse,
    ProfileResponse,
)
from app.modules.profile.domain.exceptions import ProfileNotFoundError
from app.modules.post.application.use_cases.get_post import batch_feed_cards
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.application.use_cases.create_profile import _to_response


def _render_posts(
    post_repo: IPostRepository,
    posts: list,
    viewer_profile_id: int | None,
    viewer_user_id: UUID | None,
) -> list:
    """Profile pages embed post cards, which the post module owns building."""
    if not viewer_profile_id:
        return []
    return batch_feed_cards(
        post_repo, posts, viewer_profile_id, viewer_users_id=viewer_user_id
    )


def get_my_profile(repo: IProfileRepository, user_id: UUID) -> ProfileResponse:
    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found")
    posts_count = repo.count_posts_for_profile(profile.id)
    return _to_response(profile, posts_count=posts_count)


def delete_profile(repo: IProfileRepository, user_id: UUID) -> None:
    repo.delete_profile(user_id)


def get_profile_by_id(
    repo: IProfileRepository,
    post_repo: IPostRepository,
    profile_id: int,
    viewer_user_id: UUID | None = None,
    viewer_profile_id: int | None = None,
    posts_cursor: int | None = None,
    posts_limit: int = 20,
) -> ProfilePublicResponse:
    # The only two call sites that render the follower/following numbers.
    # Everything else looking a profile up (news feed context, avatar
    # upload, group posts) would otherwise pay two counts it never reads.
    profile = repo.get_profile_by_id(profile_id, with_follow_counts=True)
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    is_following = False
    message_request_status = None
    if viewer_user_id and viewer_user_id != profile.users_id:
        is_following = repo.get_follow_status(viewer_user_id, profile.users_id)
        message_request_status = repo.get_message_request_status(viewer_user_id, profile.users_id)

    posts, posts_next_cursor, page_count = repo.get_profile_posts_feed(
        profile_id=profile_id, cursor=posts_cursor, limit=posts_limit,
    )
    feed_cards = _render_posts(post_repo, posts, viewer_profile_id, viewer_user_id)

    return ProfilePublicResponse(
        id=profile.id,
        user_id=profile.users_id,
        name=profile.name,
        role_id=profile.role_id,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        commodities=[CommodityOut.model_validate(pc.commodity) for pc in profile.commodities],
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        posts_count=page_count,
        business_name=profile.business.business_name,
        city=profile.business.city,
        state=profile.business.state,
        latitude=profile.business.latitude,
        longitude=profile.business.longitude,
        avatar_url=profile.avatar_url,
        is_following=is_following,
        message_request_status=message_request_status,
        posts=feed_cards,
        posts_next_cursor=posts_next_cursor,
    )


def get_profile_by_user_id(
    repo: IProfileRepository,
    post_repo: IPostRepository,
    user_id: UUID,
    viewer_user_id: UUID | None = None,
    viewer_profile_id: int | None = None,
    posts_cursor: int | None = None,
    posts_limit: int = 20,
) -> ProfilePublicResponse:
    profile = repo.get_profile_by_user_id(user_id, with_follow_counts=True)
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    is_following = False
    message_request_status = None
    if viewer_user_id and viewer_user_id != user_id:
        is_following = repo.get_follow_status(viewer_user_id, user_id)
        message_request_status = repo.get_message_request_status(viewer_user_id, user_id)

    posts, posts_next_cursor, page_count = repo.get_profile_posts_feed(
        profile_id=profile.id, cursor=posts_cursor, limit=posts_limit,
    )
    feed_cards = _render_posts(post_repo, posts, viewer_profile_id, viewer_user_id)

    return ProfilePublicResponse(
        id=profile.id,
        user_id=profile.users_id,
        name=profile.name,
        role_id=profile.role_id,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        commodities=[CommodityOut.model_validate(pc.commodity) for pc in profile.commodities],
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        posts_count=page_count,
        business_name=profile.business.business_name,
        city=profile.business.city,
        state=profile.business.state,
        latitude=profile.business.latitude,
        longitude=profile.business.longitude,
        avatar_url=profile.avatar_url,
        is_following=is_following,
        message_request_status=message_request_status,
        posts=feed_cards,
        posts_next_cursor=posts_next_cursor,
    )
