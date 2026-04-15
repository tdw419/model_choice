"""Response caching -- avoid redundant LLM calls."""

import hashlib
import threading
from typing import Optional


class ResponseCache:
    """Simple in-memory cache keyed on (model, prompt, params).

    Thread-safe. Bounded to max_entries (LRU eviction).
    """

    def __init__(self, max_entries: int = 256):
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def _key(self, model: str, prompt: str, temperature: float,
             max_tokens: int, json_mode: bool, system: Optional[str]) -> str:
        raw = f"{model}|{prompt}|{temperature}|{max_tokens}|{json_mode}|{system or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, model: str, prompt: str, temperature: float,
            max_tokens: int, json_mode: bool, system: Optional[str]) -> Optional[str]:
        k = self._key(model, prompt, temperature, max_tokens, json_mode, system)
        with self._lock:
            val = self._cache.get(k)
            if val is not None:
                self.hits += 1
            else:
                self.misses += 1
            return val

    def put(self, model: str, prompt: str, temperature: float,
            max_tokens: int, json_mode: bool, system: Optional[str],
            response: str):
        k = self._key(model, prompt, temperature, max_tokens, json_mode, system)
        with self._lock:
            if len(self._cache) >= self.max_entries:
                # Evict oldest entry (first key)
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[k] = response

    def clear(self):
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._cache),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": self.hits / max(1, self.hits + self.misses),
            }
