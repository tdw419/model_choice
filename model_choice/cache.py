"""Response caching -- avoid redundant LLM calls.

SQLite-backed persistent cache with LRU eviction.
Survives process restarts. Same public API as the old in-memory version.
"""

import hashlib
import os
import sqlite3
import threading
import time
from typing import Optional


class ResponseCache:
    """Persistent cache keyed on (model, prompt, params).

    Thread-safe. Bounded to max_entries (LRU eviction).
    Stores entries in SQLite so cache survives process restarts.
    """

    def __init__(self, max_entries: int = 256, db_path: Optional[str] = None):
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

        if db_path is None:
            cache_dir = os.environ.get(
                "XDG_CACHE_HOME",
                os.path.expanduser("~/.cache"),
            )
            db_path = os.path.join(cache_dir, "model_choice", "cache.db")

        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = self._connect()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                last_access REAL NOT NULL,
                created REAL NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_last_access ON cache(last_access)"
        )
        self._conn.commit()

    def _key(self, model: str, prompt: str, temperature: float,
             max_tokens: int, json_mode: bool, system: Optional[str]) -> str:
        raw = f"{model}|{prompt}|{temperature}|{max_tokens}|{json_mode}|{system or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, model: str, prompt: str, temperature: float,
            max_tokens: int, json_mode: bool, system: Optional[str]) -> Optional[str]:
        k = self._key(model, prompt, temperature, max_tokens, json_mode, system)
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM cache WHERE key = ?", (k,)
            ).fetchone()
            if row is not None:
                self._conn.execute(
                    "UPDATE cache SET last_access = ? WHERE key = ?",
                    (time.time(), k),
                )
                self._conn.commit()
                self.hits += 1
                return row[0]
            else:
                self.misses += 1
                return None

    def put(self, model: str, prompt: str, temperature: float,
            max_tokens: int, json_mode: bool, system: Optional[str],
            response: str):
        k = self._key(model, prompt, temperature, max_tokens, json_mode, system)
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO cache (key, value, last_access, created)
                   VALUES (?, ?, ?, ?)""",
                (k, response, now, now),
            )
            # LRU eviction: remove oldest entries over the limit
            count = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            if count > self.max_entries:
                excess = count - self.max_entries
                self._conn.execute(
                    """DELETE FROM cache WHERE key IN (
                        SELECT key FROM cache ORDER BY last_access ASC
                        LIMIT ?
                    )""",
                    (excess,),
                )
            self._conn.commit()

    def clear(self):
        with self._lock:
            self._conn.execute("DELETE FROM cache")
            self._conn.commit()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            return {
                "entries": count,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": self.hits / max(1, self.hits + self.misses),
            }
