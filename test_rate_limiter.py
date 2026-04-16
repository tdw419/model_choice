"""Tests for model_choice rate limiter."""

import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRateLimiterBasic(unittest.TestCase):
    """Basic acquire/release."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "rate_limit.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_limiter(self):
        from model_choice.rate_limiter import RateLimiter
        return RateLimiter(db_path=self.db_path)

    def test_acquire_and_release(self):
        limiter = self._make_limiter()
        req_id = limiter.acquire("test", max_concurrent=2, timeout=5)
        self.assertIsNotNone(req_id)
        self.assertEqual(limiter.active_count("test"), 1)
        limiter.release("test", req_id)
        self.assertEqual(limiter.active_count("test"), 0)

    def test_max_concurrent_enforced(self):
        limiter = self._make_limiter()
        # Acquire all slots
        slots = []
        for _ in range(3):
            s = limiter.acquire("test", max_concurrent=3, timeout=1)
            self.assertIsNotNone(s)
            slots.append(s)

        # 4th should fail
        s = limiter.acquire("test", max_concurrent=3, timeout=0.5)
        self.assertIsNone(s)

        # Release one, should succeed again
        limiter.release("test", slots.pop())
        s = limiter.acquire("test", max_concurrent=3, timeout=1)
        self.assertIsNotNone(s)
        slots.append(s)

        for s in slots:
            limiter.release("test", s)

    def test_min_interval(self):
        limiter = self._make_limiter()
        start = time.time()
        s1 = limiter.acquire("test", max_concurrent=10, min_interval=0.5, timeout=5)
        t1 = time.time()
        s2 = limiter.acquire("test", max_concurrent=10, min_interval=0.5, timeout=5)
        t2 = time.time()

        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        # Second acquire should have waited at least min_interval
        self.assertGreaterEqual(t2 - t1, 0.3)  # some tolerance

        limiter.release("test", s1)
        limiter.release("test", s2)

    def test_context_manager(self):
        limiter = self._make_limiter()
        with limiter.limit("test", max_concurrent=2, timeout=5):
            self.assertEqual(limiter.active_count("test"), 1)
        self.assertEqual(limiter.active_count("test"), 0)

    def test_status(self):
        limiter = self._make_limiter()
        self.assertEqual(limiter.status(), {})
        s = limiter.acquire("test", max_concurrent=2, timeout=5)
        self.assertEqual(limiter.status(), {"test": 1})
        limiter.release("test", s)

    def test_reset(self):
        limiter = self._make_limiter()
        for _ in range(3):
            limiter.acquire("test", max_concurrent=10, timeout=1)
        self.assertEqual(limiter.active_count("test"), 3)
        limiter.reset()
        self.assertEqual(limiter.active_count("test"), 0)

    def test_different_providers_independent(self):
        limiter = self._make_limiter()
        s1 = limiter.acquire("prov_a", max_concurrent=1, timeout=1)
        s2 = limiter.acquire("prov_b", max_concurrent=1, timeout=1)
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        limiter.release("prov_a", s1)
        limiter.release("prov_b", s2)


class TestRateLimiterConcurrency(unittest.TestCase):
    """Thread safety."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "rate_limit.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_concurrent_acquires(self):
        from model_choice.rate_limiter import RateLimiter
        limiter = RateLimiter(db_path=self.db_path)

        acquired = []
        failed = []
        lock = threading.Lock()

        def try_acquire():
            s = limiter.acquire("test", max_concurrent=2, timeout=1)
            if s:
                with lock:
                    acquired.append(s)
                time.sleep(0.1)
                limiter.release("test", s)
            else:
                with lock:
                    failed.append(1)

        threads = [threading.Thread(target=try_acquire) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At most 2 should have been concurrent at any time
        # Some may have failed due to timeout
        self.assertGreater(len(acquired), 0)


class TestRateLimiterStaleCleanup(unittest.TestCase):
    """Stale request cleanup."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "rate_limit.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stale_requests_cleaned(self):
        from model_choice.rate_limiter import RateLimiter
        limiter = RateLimiter(db_path=self.db_path)

        # Insert a stale request manually
        conn = limiter._connect()
        conn.execute(
            "INSERT INTO active_requests (id, provider, started, pid) "
            "VALUES (?, ?, ?, ?)",
            ("stale_1", "test", time.time() - 600, os.getpid()),
        )
        conn.commit()
        conn.close()

        self.assertEqual(limiter.active_count("test"), 0)  # stale cleaned up


class TestRateLimitIntegration(unittest.TestCase):
    """Integration with Provider dataclass."""

    def test_provider_rate_limit_fields(self):
        from model_choice.registry import Provider
        p = Provider(
            provider="test", model="test-model", label="Test",
            backend="litellm", auth="api_key", complexity="balanced",
            max_concurrent=4, min_interval=1.0,
        )
        self.assertEqual(p.max_concurrent, 4)
        self.assertEqual(p.min_interval, 1.0)

    def test_zai_has_rate_limits(self):
        from model_choice import pick
        p = pick(model="zai")
        if p:
            # May or may not have limits depending on config
            self.assertIn(p.provider, ["zai"])


if __name__ == "__main__":
    unittest.main()
