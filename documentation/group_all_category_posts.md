# Implementation Plan: Group Posts — All Categories

## Context

This extends [group_deal_posts.md](group_deal_posts.md) to cover all four post categories within groups, not just Deal/Requirement. The key insight is that Market Update, Knowledge, and Discussion posts have no structured fields beyond title + caption + optional image — they are simpler than deals but follow the same two-layer architecture.

**The four categories:**
| category_id | Name | Structured fields beyond title/caption/image? |
|-------------|------|-----------------------------------------------|
| 1 | Market Update | No |
| 2 | Knowledge | No |
| 3 | Discussion | No |
| 4 | Deal/Requirement | Yes — grain, quantity, price, type |

Since categories 1–3 share the same shape, they all fit into one unified `GroupPost` model. Category 4 adds a companion `GroupPostDealDetails` row, mirroring exactly how the post module works (`Post` + `PostDealDetails`).

---

## Architecture: Unified Two-Layer Design

### Layer 1 — `GroupPost` entity (groups module)
A content card visible only to group members. Covers all four categories. For category 4 it has a companion `GroupPostDealDetails` row.

### Layer 2 — `Post` promotion (post module, optional)
When the author broadcasts, a `Post` is created (category_id copied). For category 4 a `PostDealDetails` row is also created. The `GroupPost.post_id` FK records the link. The Post is independent — it has its own rec engine lifecycle.

---

## New Models

**File:** `app/modules/groups/models.py`

### `GroupPost`

| Field | Type | Constraint |
|-------|------|------------|
| `id` | UUID PK | default uuid4 |
| `group_id` | UUID FK → groups.id | ON DELETE CASCADE |
| `posted_by` | UUID FK → users.id | ON DELETE RESTRICT |
| `category_id` | Integer FK → post_categories.id | 1–4 |
| `commodity_id` | Integer FK → commodities.id | required |
| `title` | String(200) | NOT NULL |
| `caption` | Text | NOT NULL |
| `image_url` | String(500) | NULL |
| `is_closed` | Boolean | default False, only used for category 4 |
| `post_id` | Integer FK → posts.id | NULL until promoted |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

Relationship: `deal_details` → `GroupPostDealDetails` (one-to-one, cascade delete)

### `GroupPostDealDetails`

| Field | Type | Constraint |
|-------|------|------------|
| `id` | UUID PK | default uuid4 |
| `group_post_id` | UUID FK → group_posts.id | UNIQUE, ON DELETE CASCADE |
| `grain_type` | String(50) | required |
| `grain_size` | String(50) | required |
| `commodity_quantity` | Numeric(12,2) | required |
| `quantity_unit` | String(20) | MT \| quintal |
| `commodity_price` | Numeric(12,2) | required |
| `price_type` | String(20) | fixed \| negotiable |

This mirrors `PostDealDetails` exactly, making future extraction into a standalone deals module straightforward.

---

## Endpoints: `/api/v1/groups/{group_id}/posts`

**Files:** `app/modules/groups/router.py`, `app/modules/groups/service.py`, `app/modules/groups/schemas.py`

| Method | Path | Purpose | Auth constraint |
|--------|------|---------|----------------|
| POST | `/groups/{group_id}/posts` | Create group post (any category) | Member + posting_perm + not frozen |
| GET | `/groups/{group_id}/posts` | List group posts (optional filter by category_id) | Member only |
| GET | `/groups/{group_id}/posts/{gpost_id}` | Get single post card | Member only |
| PATCH | `/groups/{group_id}/posts/{gpost_id}` | Update (while not closed, if deal) | Author only |
| POST | `/groups/{group_id}/posts/{gpost_id}/close` | Toggle is_closed (category 4 only) | Author only |
| POST | `/groups/{group_id}/posts/{gpost_id}/publish` | Promote to personal feed | Author only, post_id must be NULL |

---

## Schemas

**File:** `app/modules/groups/schemas.py`

```python
class GroupPostDealCreate(BaseModel):
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: Literal["MT", "quintal"]
    commodity_price: float
    price_type: Literal["fixed", "negotiable"]

class GroupPostCreate(BaseModel):
    category_id: int                        # 1–4
    commodity_id: int
    title: str                              # required, non-empty
    caption: str                            # required, non-empty
    image_url: Optional[str] = None
    deal_details: Optional[GroupPostDealCreate] = None  # required when category_id=4, forbidden otherwise
    publish_to_feed: bool = False
    feed_is_public: bool = True

    @validator("deal_details", always=True)
    def validate_deal_details(cls, v, values):
        if values.get("category_id") == 4 and v is None:
            raise ValueError("deal_details required for category 4")
        if values.get("category_id") != 4 and v is not None:
            raise ValueError("deal_details only allowed for category 4")
        return v

class GroupPostDealUpdate(BaseModel):
    grain_type: Optional[str]
    grain_size: Optional[str]
    commodity_quantity: Optional[float]
    quantity_unit: Optional[Literal["MT", "quintal"]]
    commodity_price: Optional[float]
    price_type: Optional[Literal["fixed", "negotiable"]]

class GroupPostUpdate(BaseModel):
    title: Optional[str]
    caption: Optional[str]
    image_url: Optional[str]
    deal_details: Optional[GroupPostDealUpdate] = None   # only for category 4

class GroupPostDealDetailsResponse(BaseModel):
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str

class GroupPostResponse(BaseModel):
    id: UUID
    group_id: UUID
    posted_by: UUID
    category_id: int
    commodity_id: int
    title: str
    caption: str
    image_url: Optional[str]
    is_closed: bool
    deal_details: Optional[GroupPostDealDetailsResponse]  # present only for category 4
    post_id: Optional[int]                               # None until promoted
    created_at: datetime
    updated_at: datetime

class GroupPostPublishRequest(BaseModel):
    is_public: bool = True
```

---

## Service Logic

**File:** `app/modules/groups/service.py`

### `create_group_post(db, group_id, user_id, profile_id, payload)`

1. Fetch Group — raise 404 if not found
2. Fetch GroupMember via `_get_membership(db, group_id, user_id)` — raise 403 if not found
3. Check `posting_perm == "admins_only"` AND `role != "admin"` → raise 403
4. Check `is_frozen == True` → raise 403
5. Insert `GroupPost` row
6. If `payload.category_id == 4`: insert `GroupPostDealDetails` row linked to group_post.id
7. Insert group chat message:
   - `context_type="group"`, `context_id=group_id`
   - `message_type="group_post"`
   - `sender_id=user_id`
   - `media_metadata={"group_post_id": str(gp.id), "category_id": gp.category_id, "title": gp.title}`
8. If `payload.publish_to_feed=True`:
   - Call `_create_post_from_group_post(db, gp, profile_id, payload.feed_is_public)`
   - Set `gp.post_id = post.id`
9. Commit and return `GroupPostResponse`

### `publish_group_post(db, group_id, gpost_id, user_id, profile_id, is_public)`

1. Fetch GroupPost — raise 404 if not in this group
2. Verify `gp.posted_by == user_id` — raise 403 if not author
3. If `gp.post_id is not None` → raise 409 "already published"
4. Call `_create_post_from_group_post(db, gp, profile_id, is_public)`
5. Set `gp.post_id = post.id`, commit
6. Return updated `GroupPostResponse`

### `_create_post_from_group_post(db, gp, profile_id, is_public)` (internal helper)

1. Insert `Post` (category_id=gp.category_id, commodity_id, title, caption, image_url, profile_id, is_public)
2. If `gp.category_id == 4`:
   - Insert `PostDealDetails` (post_id, grain_type, grain_size, commodity_quantity, quantity_unit, commodity_price, price_type, is_closed=gp.is_closed)
3. Call `rec_service.index_post(post)`
4. Return Post

---

## Chat Module Change

**File:** `app/modules/chat/presentation/schemas.py`

Add `"group_post"` to the `message_type` regex pattern.

Current: `text|image|video|document|audio|location|system|post|news|user`
Updated: append `|group_post`

> **Why `"group_post"` and not `"deal"`?**
> The existing `"post"` type is used for sharing an existing Post from the public feed. `"group_post"` is a different semantic: a privately-scoped card that lives in the group. Using a distinct type lets the client render them differently without inspecting `media_metadata`.

---

## Auth Context Note

Groups router auth resolves to `user_id` (UUID, from `users` table).  
Post module auth resolves to `profile_id` (Integer, from `profiles` table).

`_create_post_from_group_post` needs `profile_id` because `Post.profile_id` is Integer. The groups endpoint must either:
- Accept both from the auth dependency, or
- Look up `profile_id` from `Profile` where `users_id == user_id`

Check how other endpoints in `app/modules/groups/router.py` handle this — if a `profile_id` auth dependency already exists for groups, reuse it.

---

## Migration

**New file:** `alembic/versions/<timestamp>_add_group_posts_tables.py`

Creates two tables:

**`group_posts`:**
- `group_id` → `groups.id` (UUID, ON DELETE CASCADE)
- `posted_by` → `users.id` (UUID, ON DELETE RESTRICT)
- `category_id` → `post_categories.id` (Integer)
- `commodity_id` → `commodities.id` (Integer)
- `post_id` → `posts.id` (Integer, nullable, ON DELETE SET NULL)

**`group_post_deal_details`:**
- `group_post_id` → `group_posts.id` (UUID, UNIQUE, ON DELETE CASCADE)

---

## Comparison: Deal-Only Plan vs All-Categories Plan

| Aspect | `group_deal_posts.md` | This plan |
|--------|----------------------|-----------|
| Scope | category 4 only | categories 1–4 |
| Model | `GroupDeal` (inline deal fields) | `GroupPost` + `GroupPostDealDetails` |
| Tables | 1 new table | 2 new tables |
| Deal fields location | Inline on `GroupDeal` | Separate `GroupPostDealDetails` (mirrors Post module pattern) |
| Chat message_type | `"deal"` | `"group_post"` |
| Endpoint prefix | `/groups/{id}/deals` | `/groups/{id}/posts` |
| Future deals module extraction | Deal fields inline, needs migration later | Already in separate table, extraction is simpler |

The all-categories plan has a marginally higher upfront cost (one extra table, slightly more complex schema validation) but is architecturally cleaner and avoids a second migration when other categories eventually need group support.

---

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Unified model for all 4 categories | Yes — `GroupPost` | Avoids separate tables per category; categories 1–3 are identical in shape |
| Deal fields in separate table | Yes — `GroupPostDealDetails` | Mirrors existing Post + PostDealDetails pattern; future deals module extraction is clean |
| `is_closed` on `GroupPost` (not `GroupPostDealDetails`) | Yes | Allows querying closed/open deals without a join |
| `message_type="group_post"` | Yes | Distinct from `"post"` (public feed share); client can render group cards differently |
| Promoted Post is independent snapshot | Yes | Group deal lifecycle is independent from broadcast Post lifecycle |
| title + caption compulsory | NOT NULL + validator | Required for meaningful card display in all categories |
| `posting_perm` + `is_frozen` enforced | Yes | Existing group ACL must be respected |
| `close` endpoint only valid for category 4 | Yes | Raise 400 if called on categories 1–3 |

---

## Verification

1. **Create Market Update (category 1):** `POST /groups/{id}/posts` with `category_id=1`, no `deal_details` → success; `deal_details=null` in response
2. **Create Deal/Req (category 4):** same endpoint with `category_id=4` + `deal_details` → success; `GroupPostDealDetails` row created
3. **Category 4 without deal_details:** → 422 validation error
4. **Category 1 with deal_details:** → 422 validation error
5. **Close on category 1 post:** `POST /posts/{id}/close` → 400 "not a deal post"
6. **Publish any category:** `POST /posts/{id}/publish` → Post created with correct category_id; Post appears in `/posts/mine`
7. **Publish category 4:** Post created with PostDealDetails row
8. **Double-publish:** second call → 409
9. **Permission checks:** non-member → 403; frozen → 403; non-admin in admins_only group → 403
10. **Global feeds clean:** `GET /posts/`, `/posts/following`, `/posts/mine` return no group-only posts unless promoted
