# Sentinel returned by target-language resolution when no explicit override, no
# per-conversation preference, and no reader default exist. The prompt assembler
# swaps in a different static instruction for this case (detect source language;
# translate to Hindi if it's already English, otherwise English) instead of
# treating it as a real language code.
AUTO_FALLBACK = "__auto__"
