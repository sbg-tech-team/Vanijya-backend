"""Minimal but realistic fixture data for the live-DB tests."""
import uuid
from datetime import datetime, timedelta, timezone

from app.modules.profile.data.models import (
    Business, Commodity, Profile, Profile_Commodity, Role, User)
from app.modules.news.data.models import NewsArticle, NewsSource
from app.modules.post.data.models import Post
from app.modules.safety.data.models import UserBlock

NOW = datetime.now(timezone.utc)


def seed(db):
    ids = {}
    role = Role(id=1, name="trader"); db.add(role)
    com = Commodity(id=1, name="wheat"); db.add(com)
    db.flush()

    for key, name in [("me", "Alice"), ("other", "Bob")]:
        uid = uuid.uuid4()
        db.add(User(id=uid, country_code="+91", phone_number=f"90000000{len(ids)}"))
        db.flush()
        p = Profile(users_id=uid, name=name, role_id=1, quantity_min=0, quantity_max=100,
                    avatar_url=f"http://img/{name}.png")
        db.add(p); db.flush()
        db.add(Business(profile_id=p.id, business_name=f"{name} Traders",
                        city="Pune", state="MH", latitude=18.5, longitude=73.8))
        db.add(Profile_Commodity(profile_id=p.id, commodity_id=1))
        ids[key] = {"user_id": uid, "profile_id": p.id}
    db.flush()

    src = NewsSource(name="Reuters", domain="reuters.com",
                     rss_url="http://reuters.com/rss", category="wire",
                     credibility_weight=1.2)
    db.add(src); db.flush()
    art = NewsArticle(
        id=uuid.uuid4(), source_id=src.id, title="Wheat prices climb",
        summary="Prices rose sharply on export demand.", url="http://n/1",
        image_url="http://img/n1.png", published_at=NOW - timedelta(hours=3),
        cluster_id=1, severity=7.5, commodities=["wheat"], regions=["MH"],
        scope="national", direction_tags=["up"], is_classified=True,
        created_at=NOW - timedelta(hours=3),
    )
    glob = NewsArticle(
        id=uuid.uuid4(), source_id=src.id, title="Global shipping snarl",
        summary="Container rates spike.", url="http://n/2",
        published_at=NOW - timedelta(days=2), cluster_id=3, severity=5.0,
        scope="global", is_classified=True, created_at=NOW - timedelta(days=2),
    )
    db.add_all([art, glob]); db.flush()
    ids["article_id"] = art.id
    ids["global_article_id"] = glob.id

    from app.modules.post.data.models import PostCategory
    cat = PostCategory(id=1, name="sell"); db.add(cat); db.flush()
    post = Post(profile_id=ids["me"]["profile_id"], category_id=1, commodity_id=1,
                title="Wheat for sale", caption="Selling 20MT wheat",
                image_urls=["http://img/p1.png"])
    db.add(post); db.flush()
    ids["post_id"] = post.id

    from app.modules.groups.data.models import Group, GroupMember
    g = Group(
        id=uuid.uuid4(), name="Wheat Traders MH", description="Maharashtra wheat",
        created_by=ids["me"]["user_id"], commodity=["wheat"], target_roles=["trader"],
        region_market="Pune", accessibility="public",
    )
    db.add(g); db.flush()
    db.add(GroupMember(group_id=g.id, user_id=ids["me"]["user_id"], role="admin"))
    db.flush()
    ids["group_id"] = g.id

    db.commit()
    return ids
