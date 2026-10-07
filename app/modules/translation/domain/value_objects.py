# Sentinel returned by target-language resolution when no explicit override, no
# per-conversation preference, and no reader default exist. The prompt assembler
# swaps in a different static instruction for this case (detect source language;
# translate to Hindi if it's already English, otherwise English) instead of
# treating it as a real language code.
AUTO_FALLBACK = "__auto__"


# Every single-tap translation is a paid Gemini call. Without a ceiling one
# account can burn the whole translation budget in an afternoon, and there is
# no per-user billing to notice it. Generous enough to tap through a long
# thread, low enough that a script cannot run up a bill.
TRANSLATE_RATE_LIMIT: int = 60
TRANSLATE_RATE_WINDOW_SECONDS: int = 3600


# ── Content (post / comment / news) translation ──────────────────────────────
# Items per request. Bounds a single tap's worst case: a post plus its visible
# comments fits comfortably.
CONTENT_MAX_ITEMS_PER_REQUEST: int = 20
# Items per engine call. Batching shares the static instruction across items;
# capping it keeps one response small enough that a single malformed item does
# not cost a huge output, and a timeout does not lose a whole page.
CONTENT_ITEMS_PER_ENGINE_CALL: int = 5
# The lock outlives any plausible engine call, so a crashed holder frees it
# on its own.
CONTENT_LOCK_TTL_SECONDS: int = 60
# Items retried once, each on its own, after their batch was rejected by a
# check (shape, script, numbers). In the per-language review, rejected items
# were often batch contamination — a Hindi word or a stray key picked up from
# the item next to them. Capped because each retry is another engine call on
# the reader's clock.
CONTENT_MAX_RETRY_ITEMS: int = 3
# Per engine call. A live probe saw 2-3 s normally but 10 s and 25 s outliers;
# past this the reader is better served by "failed, tap again" than a spinner.
CONTENT_ENGINE_TIMEOUT_SECONDS: int = 15
# Low, not zero: the same post should read the same for every reader who
# gets a fresh translation, but a little freedom helps phrasing.
CONTENT_ENGINE_TEMPERATURE: float = 0.2
# How long a reader waits for someone else's in-flight translation of the same
# item before being told it is still in progress.
CONTENT_WAIT_SECONDS: float = 8.0
CONTENT_WAIT_POLL_SECONDS: float = 0.5
# Only requests that reach the engine count — a cache hit is free, so it is
# never rate limited.
CONTENT_TRANSLATE_RATE_LIMIT: int = 60
CONTENT_TRANSLATE_RATE_WINDOW_SECONDS: int = 3600


# ── Chat translation checks ───────────────────────────────────────────────────
# After a continuous-mode message fails the checks twice, skip it for this
# long. The 5-minute recovery job looks back 60 minutes, so without this a
# message the engine cannot translate cleanly would be re-sent ~24 times.
CHAT_REJECTION_MEMO_TTL_SECONDS: int = 2 * 3600
