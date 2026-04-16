"""Per-provider rate limiting with cross-process coordination.

Uses SQLite to track active connections across processes. When max_concurrent
is reached, new requests wait (with timeout) instead of firing and getting 429'd.

Config in tiers.yaml:
  providers:
    - provider: zai
      max_concurrent: 4       # max simultaneous connections
      min_interval: 1.0       # min seconds between requests

Or per-call:
  generate(prompt, max_concurrent=4)
"""

import os
import sqlite3
import threading
import time
import uuid
import logging
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger("model_choice.rate_limiter")

DEFAULT_DB_PATH = None  # set lazily


def _default_db_path() -> str:
    global DEFAULT_DB_PATH
    if DEFAULT_DB_PATH is None:
        cache_dir = os.environ.get(
            "XDG_CACHE_HOME",
            os.path.expanduser("~/.cache"),
        )
        DEFAULT_DB_PATH = os.path.join(cache_dir, "model_choice", "rate_limit.db")
    return DEFAULT_DB_PATH


class RateLimiter:
    """Cross-process rate limiter using SQLite.

    Tracks active requests per provider. When max_concurrent is reached,
    new requests poll until a slot opens or timeout expires.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _default_db_path()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._local_lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS active_requests (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    started REAL NOT NULL,
                    pid INTEGER NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_provider "
                "ON active_requests(provider)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_started "
                "ON active_requests(started)"
            )
            conn.commit()
        finally:
            conn.close()

    def _cleanup_stale(self, conn, max_age: float = 300):
        """Remove requests older than max_age seconds (stale/orphaned)."""
        cutoff = time.time() - max_age
        conn.execute(
            "DELETE FROM active_requests WHERE started < ?", (cutoff,)
        )
        conn.commit()

    def active_count(self, provider: str) -> int:
        """Count active requests for a provider."""
        conn = self._connect()
        try:
            self._cleanup_stale(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM active_requests WHERE provider = ?",
                (provider,),
            ).fetchone()
            return row[0]
        finally:
            conn.close()

    def acquire(
        self,
        provider: str,
        max_concurrent: int = 4,
        min_interval: float = 0.0,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> Optional[str]:
        """Wait for a rate limit slot. Returns request ID or None on timeout.

        Args:
            provider: Provider name (e.g. "zai").
            max_concurrent: Max simultaneous connections.
            min_interval: Min seconds between requests. 0 = no limit.
            timeout: Max seconds to wait for a slot.
            poll_interval: How often to check for an open slot.

        Returns:
            Request ID string (use for release()), or None if timed out.
        """
        request_id = uuid.uuid4().hex[:12]
        pid = os.getpid()
        deadline = time.time() + timeout

        with self._local_lock:
            conn = self._connect()
            try:
                while True:
                    self._cleanup_stale(conn)

                    # Check min_interval: when was the last request?
                    if min_interval > 0:
                        last = conn.execute(
                            "SELECT MAX(started) FROM active_requests "
                            "WHERE provider = ?",
                            (provider,),
                        ).fetchone()[0]
                        if last and (time.time() - last) < min_interval:
                            wait = min_interval - (time.time() - last)
                            if time.time() + wait > deadline:
                                logger.warning(
                                    f"Rate limit: {provider} min_interval "
                                    f"timeout ({wait:.1f}s needed)"
                                )
                                return None
                            time.sleep(wait)

                    # Count active
                    count = conn.execute(
                        "SELECT COUNT(*) FROM active_requests "
                        "WHERE provider = ?",
                        (provider,),
                    ).fetchone()[0]

                    if count < max_concurrent:
                        # Slot available -- register
                        conn.execute(
                            "INSERT INTO active_requests "
                            "(id, provider, started, pid) VALUES (?, ?, ?, ?)",
                            (request_id, provider, time.time(), pid),
                        )
                        conn.commit()
                        logger.debug(
                            f"Rate limit: acquired {provider} slot "
                            f"({count + 1}/{max_concurrent})"
                        )
                        return request_id

                    # No slot -- wait or timeout
                    if time.time() >= deadline:
                        logger.warning(
                            f"Rate limit: {provider} timed out waiting for "
                            f"slot ({count}/{max_concurrent} active, "
                            f"{timeout}s timeout)"
                        )
                        return None

                    time.sleep(poll_interval)
            finally:
                conn.close()

    def release(self, provider: str, request_id: str):
        """Release a rate limit slot after call completes."""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM active_requests WHERE id = ?",
                (request_id,),
            )
            conn.commit()
            logger.debug(f"Rate limit: released {provider} slot {request_id}")
        finally:
            conn.close()

    @contextmanager
    def limit(
        self,
        provider: str,
        max_concurrent: int = 4,
        min_interval: float = 0.0,
        timeout: float = 60.0,
    ):
        """Context manager: acquire slot, yield, release on exit.

        Usage:
            with limiter.limit("zai", max_concurrent=4):
                result = call(provider, ...)
        """
        request_id = self.acquire(
            provider, max_concurrent, min_interval, timeout
        )
        if request_id is None:
            raise RuntimeError(
                f"Rate limit: timed out waiting for {provider} slot "
                f"(max_concurrent={max_concurrent}, timeout={timeout}s)"
            )
        try:
            yield
        finally:
            self.release(provider, request_id)

    def status(self) -> dict:
        """Get current rate limit status for all providers."""
        conn = self._connect()
        try:
            self._cleanup_stale(conn)
            rows = conn.execute(
                "SELECT provider, COUNT(*) FROM active_requests "
                "GROUP BY provider"
            ).fetchall()
            return {provider: count for provider, count in rows}
        finally:
            conn.close()

    def reset(self):
        """Clear all active requests (emergency reset)."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM active_requests")
            conn.commit()
        finally:
            conn.close()


# Module-level singleton (shared across all calls within a process)
_limiter: Optional[RateLimiter] = None


def get_limiter() -> RateLimiter:
    """Get the shared rate limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
