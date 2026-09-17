from __future__ import annotations

import hashlib
from collections import OrderedDict
from threading import Lock
from typing import Optional

from app.modules.translation.domain.interfaces.translation_cache import ITranslationCache


class InMemoryTranslationCache(ITranslationCache):
    """Thin, per-process LRU — gone on restart, never persisted. Just avoids a
    duplicate Gemini call when the same text+target+context is requested twice
    in quick succession (e.g. two people tapping translate on the same message).
    The durable copy of a translation lives on the reader's device."""

    def __init__(self, max_size: int = 2000):
        self._max_size = max_size
        self._store: OrderedDict[str, str] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _key(text: str, target_lang: str, context_fingerprint: str) -> str:
        raw = f"{target_lang}|{context_fingerprint}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text: str, target_lang: str, context_fingerprint: str) -> Optional[str]:
        key = self._key(text, target_lang, context_fingerprint)
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, text: str, target_lang: str, context_fingerprint: str, translated_text: str) -> None:
        key = self._key(text, target_lang, context_fingerprint)
        with self._lock:
            self._store[key] = translated_text
            self._store.move_to_end(key)
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)
