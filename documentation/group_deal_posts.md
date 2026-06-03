# Implementation Plan: Group Deal/Requirement Posts

## Context

The original proposal (attaching `group_id` to the `Post` model) was revised based on two clarifications:

1. **Only Deal/Requirement (category_id=4) is in scope** for group posts. The other categories (Market Update, Knowledge, Discussion) have no structured format and don't belong in groups.
2. **A group deal is a first-class entity in the groups module**, not a repurposing of the Post model. The Post module is used only when the author explicitly promotes the deal to their personal feed.

This design avoids the 15 problems identified in the original proposal (feed leakage, rec-engine conflicts, visibility contradictions) because the `Post` model is not touched at all until the author opts in to publishing.

The group deal appears in the **group chat** as a special message card (`message_type="deal"`), which is the existing mechanism for group-scoped content — the chat module already supports `context_type="group"` messages with `media_metadata` JSONB for structured payloads.

---

## Architecture: Two Layers

### Layer 1 — `GroupDeal` entity (lives in groups module)
A structured deal/requirement card visible only to group members. It is the source of truth for the deal.

### Layer 2 — `Post` promotion (optional, lives in post module)
When the author chooses to broadcast, a standard `Post` (category_id=4) + `PostDealDetails` is created. The `GroupDeal.post_id` FK records the link. The Post is independent — it has its own lifecycle in the recommendation engine.

---

## New Model: `GroupDeal`

**File:** `app/modules/groups/models.py`

| Field | Type | Constraint |
|-------|------|------------|
| `id` | UUID PK | default uuid4 |
| `group_id` | UUID FK → groups.id | ON DELETE CASCADE |
| `posted_by` | UUID FK → users.id | ON DELETE RESTRICT |
| `commodity_id` | Integer FK → commodities.id | required |
| `title` | String(200) | NOT NULL |
| `caption` | Text | NOT NULL |
| `grain_type` | String(50) | required |
| `grain_size` | String(50) | required |
| `commodity_quantity` | Numeric(12,2) | required |
| `quantity_unit` | String(20) | MT \| quintal |
| `commodity_price` | Numeric(12,2) | required |
| `price_type` | String(20) | fixed \| negotiable |
| `is_closed` | Boolean | default False |
| `post_id` | Integer FK → posts.id | NULL until promoted |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

Deal fields mirror `PostDealDetails` intentionally — this makes future extraction into a standalone deals module straightforward.

---

## Endpoints: `/api/v1/groups/{group_id}/deals`

**Files:** `app/modules/groups/router.py`, `app/modules/groups/service.py`, `app/modules/groups/schemas.py`

| Method | Path | Purpose | Auth constraint |
|--------|------|---------|----------------|
| POST | `/groups/{group_id}/deals` | Create group deal (+ optional immediate publish) | Member + posting_perm + not frozen |
| GET | `/groups/{group_id}/deals` | List all deals in group | Member only |
| GET | `/groups/{group_id}/deals/{deal_id}` | Get single deal card | Member only |
| PATCH | `/groups/{group_id}/deals/{deal_id}` | Update deal (while not closed) | Author only |
| POST | `/groups/{group_id}/deals/{deal_id}/close` | Toggle is_closed | Author only |
| POST | `/groups/{group_id}/deals/{deal_id}/publish` | Promote to post feed | Author only, post_id must be NULL |

---

## Schemas

**File:** `app/modules/groups/schemas.py`

```python
class GroupDealCreate(BaseModel):
    commodity_id: int
    title: str                              # required, non-empty
    caption: str                            # required, non-empty
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: Literal["MT", "quintal"]
    commodity_price: float
    price_type: Literal["fixed", "negotiable"]
    publish_to_feed: bool = False           # immediately create a Post?
    feed_is_public: bool = True            # if publishing, public or private?

class GroupDealUpdate(BaseModel):
    title: Optional[str]
    caption: Optional[str]
    grain_type: Optional[str]
    grain_size: Optional[str]
    commodity_quantity: Optional[float]
    quantity_unit: Optional[Literal["MT", "quintal"]]
    commodity_price: Optional[float]
    price_type: Optional[Literal["fixed", "negotiable"]]

class GroupDealResponse(BaseModel):
    id: UUID
    group_id: UUID
    posted_by: UUID
    commodity_id: int
    title: str
    caption: str
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str
    is_closed: bool
    post_id: Optional[int]                 # None until promoted
    created_at: datetime
    updated_at: datetime

class GroupDealPublishRequest(BaseModel):
    is_public: bool = True                 # public or private post on the feed
```

---

## Service Logic

**File:** `app/modules/groups/service.py`

### `create_group_deal(db, group_id, user_id, payload)`

1. Fetch Group — raise 404 if not found
2. Fetch GroupMember for `(group_id, user_id)` via existing `_get_membership()` helper — raise 403 if not found
3. Check `group.posting_perm == "admins_only"` AND `member.role != "admin"` → raise 403
4. Check `member.is_frozen == True` → raise 403
5. Insert `GroupDeal` row
6. Insert group chat message via chat repository:
   - `context_type="group"`, `context_id=group_id`, `message_type="deal"`, `sender_id=user_id`
   - `media_metadata={"group_deal_id": str(deal.id), "title": deal.title, "commodity_id": deal.commodity_id}`
7. If `payload.publish_to_feed=True`: call `_create_post_from_deal(db, deal, profile_id, payload.feed_is_public)`, set `deal.post_id`
8. Commit and return `GroupDealResponse`

### `publish_group_deal(db, group_id, deal_id, user_id, profile_id, is_public)`

1. Fetch GroupDeal — raise 404 if not in this group
2. Verify `deal.posted_by == user_id` — raise 403 if not author
3. If `deal.post_id is not None` → raise 409 "already published"
4. Call `_create_post_from_deal(db, deal, profile_id, is_public)`
5. Set `deal.post_id = post.id`, commit
6. Return updated `GroupDealResponse`

### `_create_post_from_deal(db, deal, profile_id, is_public)` (internal helper)

1. Insert `Post` (category_id=4, commodity_id, title, caption, profile_id, is_public)
2. Insert `PostDealDetails` (post_id, grain_type, grain_size, commodity_quantity, quantity_unit, commodity_price, price_type, is_closed=deal.is_closed)
3. Call `rec_service.index_post(post)`
4. Return Post

---

## Chat Module Change

**File:** `app/modules/chat/presentation/schemas.py`

Add `"deal"` to the `message_type` regex pattern.

Current: `text|image|video|document|audio|location|system|post|news|user`
Updated: append `|deal`

---

## Auth Context Note

Groups router auth resolves to `user_id` (UUID). Post module auth resolves to `profile_id` (Integer). The `_create_post_from_deal` helper needs `profile_id` since `Post.profile_id` is Integer. The groups endpoint must request both from the auth dependency, or look up `profile_id` from `user_id` internally.

Reuse the existing `_get_membership(db, group_id, user_id)` helper already in `app/modules/groups/service.py`.

---

## Migration

**New file:** `alembic/versions/<timestamp>_add_group_deals_table.py`

Creates `group_deals` table. Foreign keys:
- `group_id` → `groups.id` (UUID, ON DELETE CASCADE)
- `posted_by` → `users.id` (UUID, ON DELETE RESTRICT)
- `commodity_id` → `commodities.id` (Integer)
- `post_id` → `posts.id` (Integer, nullable, ON DELETE SET NULL)

---

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Group deal separate from Post | Yes — `GroupDeal` entity | Post module untouched; clean future deals module extraction |
| Appears in group chat | Yes — `message_type="deal"` | Reuses existing group chat infrastructure |
| Promoted Post is independent | Yes — snapshot of deal data | Deal lifecycle in group is separate from broadcast Post lifecycle |
| title + caption compulsory | NOT NULL in model + schema validation | Matches existing Post constraint; required for meaningful card display |
| Closed deal can be promoted | Yes — `is_closed` copied to PostDealDetails | Author may want to broadcast a completed deal |
| `posting_perm` + `is_frozen` enforced | Yes — checked in service | Existing group ACL model respected |

---

## Original Proposal Problems — Resolution Map

| Problem | Status |
|---------|--------|
| 1 — Contradiction global exclusion vs publish-to-global | Resolved — no group_id on Post |
| 2 — No publish endpoint | Resolved — `POST /deals/{id}/publish` |
| 3 — Feed leakage (global/mine/following) | Resolved — Post module untouched until explicit promote |
| 4 — `index_post()` called unconditionally | Resolved — GroupDeal never touches post module on creation |
| 5 — No indexing on publish | Resolved — `_create_post_from_deal` calls `index_post()` |
| 6 — No group feed endpoint | Resolved — group chat + `GET /groups/{id}/deals` |
| 7 — `profile → user` lookup | Handled — groups auth uses user_id; profile_id only needed at promote step |
| 8 — `posting_perm` + `is_frozen` ignored | Resolved — enforced in `create_group_deal()` |
| 9–13 — `is_public` bypass, schema, feed ambiguity | Resolved — no group_id on Post, clean separation |
| 14 — Saved posts feed | Resolved — group deals don't enter saved posts |
| 15 — No migration | Resolved — migration for `group_deals` table |

---

## Verification

1. **Create deal (no publish):** `POST /groups/{id}/deals` → response has `post_id=null`; group chat has a `message_type="deal"` message with correct `media_metadata`
2. **Create deal with immediate publish:** `publish_to_feed=true` → `post_id` set; Post visible in `GET /posts/mine` and `/feed/home`
3. **Promote after creation:** `POST /groups/{id}/deals/{deal_id}/publish` → `post_id` populated; second call returns 409
4. **Permission checks:** non-member → 403; frozen member → 403; non-admin in admins_only group → 403
5. **Global feeds untouched:** `GET /posts/` and `GET /posts/following` contain no group-only deals unless promoted
