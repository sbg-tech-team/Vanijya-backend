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
