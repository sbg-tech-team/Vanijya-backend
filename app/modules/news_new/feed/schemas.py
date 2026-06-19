# Schemas:
#
# CursorMeta
#   next_cursor: str | None   — base64(platform_arrived_at + article_id)
#   has_more: bool
#
# NewsCard  — list view
#   article_id, title, image_url
#   time_on_platform: str     — computed: "3h" / "Yesterday" / "2 days ago"
#   summary: str | None       — our summary if available, else api_summary, else null
#   impact: dict | None       — null until intelligence pipeline runs
#   like_count: int
#   share_count: int
#   is_liked: bool
#   is_saved: bool
#
# NewsCardDetail  — on open (extends NewsCard)
#   source_name: str
#   source_url: str
#   published_at: datetime    — original source timestamp
#   platform_arrived_at: datetime  — raw ISO for frontend to compute "2h 14m ago"
#   content: str | None
#
# FeedPage
#   items: list[NewsCard]
#   cursor: CursorMeta
