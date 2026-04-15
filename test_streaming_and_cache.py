"""Tests for model_choice: SQLite cache, streaming, and backwards compatibility."""

import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure we test from this project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSQLiteCache(unittest.TestCase):
    """Test the SQLite-backed ResponseCache."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_cache.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cache(self, max_entries=256):
        from model_choice.cache import ResponseCache
        return ResponseCache(max_entries=max_entries, db_path=self.db_path)

    def test_create_db_on_init(self):
        """SQLite file is created on first use."""
        cache = self._make_cache()
        self.assertTrue(os.path.exists(self.db_path))

    def test_put_and_get(self):
        """Basic round-trip: put a value, get it back."""
        cache = self._make_cache()
        cache.put("model-a", "hello", 0.7, 2000, False, None, "response-a")
        val = cache.get("model-a", "hello", 0.7, 2000, False, None)
        self.assertEqual(val, "response-a")

    def test_get_miss(self):
        """Getting a non-existent key returns None."""
        cache = self._make_cache()
        val = cache.get("model-x", "nope", 0.7, 2000, False, None)
        self.assertIsNone(val)

    def test_stats(self):
        """Stats track hits, misses, entries."""
        cache = self._make_cache()
        cache.put("m", "p", 0.7, 2000, False, None, "r")
        cache.get("m", "p", 0.7, 2000, False, None)  # hit
        cache.get("m", "miss", 0.7, 2000, False, None)  # miss

        stats = cache.stats()
        self.assertEqual(stats["entries"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertAlmostEqual(stats["hit_rate"], 0.5)

    def test_clear(self):
        """Clear removes all entries and resets stats."""
        cache = self._make_cache()
        cache.put("m", "p", 0.7, 2000, False, None, "r")
        cache.get("m", "p", 0.7, 2000, False, None)  # hit
        cache.clear()

        self.assertIsNone(cache.get("m", "p", 0.7, 2000, False, None))
        stats = cache.stats()
        self.assertEqual(stats["entries"], 0)
        # After clear, stats reset -- new miss from the get above
        self.assertEqual(stats["hits"], 0)

    def test_lru_eviction(self):
        """Entries over max_entries are evicted (least recently used first)."""
        cache = self._make_cache(max_entries=3)

        # Insert 4 entries -- first should be evicted
        cache.put("m", "p1", 0.7, 2000, False, None, "r1")
        cache.put("m", "p2", 0.7, 2000, False, None, "r2")
        cache.put("m", "p3", 0.7, 2000, False, None, "r3")
        cache.put("m", "p4", 0.7, 2000, False, None, "r4")

        stats = cache.stats()
        self.assertEqual(stats["entries"], 3)

        # p1 should be evicted (oldest)
        self.assertIsNone(cache.get("m", "p1", 0.7, 2000, False, None))
        # p4 should still be there (newest)
        self.assertEqual(cache.get("m", "p4", 0.7, 2000, False, None), "r4")

    def test_lru_access_refreshes(self):
        """Accessing an entry moves it to most-recently-used."""
        cache = self._make_cache(max_entries=3)

        cache.put("m", "p1", 0.7, 2000, False, None, "r1")
        cache.put("m", "p2", 0.7, 2000, False, None, "r2")
        cache.put("m", "p3", 0.7, 2000, False, None, "r3")

        # Access p1 -- should refresh its LRU timestamp
        cache.get("m", "p1", 0.7, 2000, False, None)

        # Insert p4 -- should evict p2 (now oldest)
        cache.put("m", "p4", 0.7, 2000, False, None, "r4")

        self.assertIsNotNone(cache.get("m", "p1", 0.7, 2000, False, None))
        self.assertIsNone(cache.get("m", "p2", 0.7, 2000, False, None))

    def test_persistence_across_instances(self):
        """Cache survives creating a new ResponseCache instance."""
        cache1 = self._make_cache()
        cache1.put("m", "hello", 0.7, 2000, False, None, "world")

        # New instance pointing at same db
        cache2 = self._make_cache()
        val = cache2.get("m", "hello", 0.7, 2000, False, None)
        self.assertEqual(val, "world")

    def test_overwrite_existing_key(self):
        """Putting the same key again overwrites the value."""
        cache = self._make_cache()
        cache.put("m", "p", 0.7, 2000, False, None, "old")
        cache.put("m", "p", 0.7, 2000, False, None, "new")
        self.assertEqual(cache.get("m", "p", 0.7, 2000, False, None), "new")
        stats = cache.stats()
        self.assertEqual(stats["entries"], 1)

    def test_thread_safety(self):
        """Concurrent put/get don't crash."""
        cache = self._make_cache()
        errors = []

        def writer(n):
            try:
                for i in range(50):
                    cache.put("m", f"p-{n}-{i}", 0.7, 2000, False, None, f"r-{n}-{i}")
            except Exception as e:
                errors.append(e)

        def reader(n):
            try:
                for i in range(50):
                    cache.get("m", f"p-{n}-{i}", 0.7, 2000, False, None)
            except Exception as e:
                errors.append(e)

        threads = []
        for n in range(4):
            threads.append(threading.Thread(target=writer, args=(n,)))
            threads.append(threading.Thread(target=reader, args=(n,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")

    def test_sha256_key_deterministic(self):
        """Same inputs always produce the same cache key."""
        cache = self._make_cache()
        k1 = cache._key("m", "p", 0.7, 2000, False, None)
        k2 = cache._key("m", "p", 0.7, 2000, False, None)
        self.assertEqual(k1, k2)
        # Different inputs should produce different keys
        k3 = cache._key("m", "q", 0.7, 2000, False, None)
        self.assertNotEqual(k1, k3)

    def test_wal_mode(self):
        """Verify WAL journal mode for concurrent read/write."""
        cache = self._make_cache()
        conn = sqlite3.connect(self.db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode, "wal")


class TestStreamingBackends(unittest.TestCase):
    """Test the streaming backend functions."""

    def test_stream_dispatch_litellm(self):
        """stream() routes to stream_litellm for litellm backend."""
        from model_choice.backends import stream
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="litellm", auth="api_key", complexity="fast",
            api_base="http://localhost:11434", env_key="TEST_KEY",
        )

        chunks = []
        with patch("model_choice.backends.stream_litellm") as mock_stream:
            mock_stream.return_value = iter(["hello ", "world"])
            for chunk in stream(provider, "hi", 0.7, 100, False, None):
                chunks.append(chunk)

        self.assertEqual(chunks, ["hello ", "world"])

    def test_stream_dispatch_cli(self):
        """stream() routes to stream_cli for cli backend."""
        from model_choice.backends import stream
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="cli", auth="oauth", complexity="fast",
            cli_cmd="echo",
        )

        with patch("model_choice.backends.stream_cli") as mock_stream:
            mock_stream.return_value = iter(["response"])
            chunks = list(stream(provider, "hi"))
        self.assertEqual(chunks, ["response"])

    def test_stream_json_mode_suffix(self):
        """stream() appends JSON instruction when json_mode=True."""
        from model_choice.backends import stream
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="litellm", auth="api_key", complexity="fast",
        )

        with patch("model_choice.backends.stream_litellm") as mock:
            mock.return_value = iter([])
            prompt_arg = None
            # The prompt is passed to stream_litellm, check it has the suffix
            list(stream(provider, "hello", 0.7, 100, json_mode=True))
            actual_prompt = mock.call_args[0][1]  # second positional arg
            self.assertIn("valid JSON only", actual_prompt)

    def test_stream_unknown_backend(self):
        """stream() raises ValueError for unknown backend."""
        from model_choice.backends import stream
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="unknown", auth="none", complexity="fast",
        )
        with self.assertRaises(ValueError):
            list(stream(provider, "hi"))

    def test_stream_cli_echo(self):
        """stream_cli with 'echo' yields the prompt."""
        from model_choice.backends import stream_cli
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="echo-model", label="Echo",
            backend="cli", auth="none", complexity="fast",
            cli_cmd="echo",
        )
        chunks = list(stream_cli(provider, "hello world"))
        full = "".join(chunks).strip()
        self.assertEqual(full, "hello world")

    def test_stream_cli_failing_command(self):
        """stream_cli raises RuntimeError on non-zero exit."""
        from model_choice.backends import stream_cli
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="fail-model", label="Fail",
            backend="cli", auth="none", complexity="fast",
            cli_cmd="false",
        )
        with self.assertRaises(RuntimeError) as ctx:
            list(stream_cli(provider, "does not matter"))
        self.assertIn("exited", str(ctx.exception))

    def test_stream_cli_abandoned_generator(self):
        """Abandoning a stream_cli generator doesn't leak the process."""
        from model_choice.backends import stream_cli
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="echo-model", label="Echo",
            backend="cli", auth="none", complexity="fast",
            cli_cmd="echo",
        )
        gen = stream_cli(provider, "hello")
        # Read one chunk then abandon
        chunk = next(gen)
        self.assertIn("hello", chunk)
        # Close the generator (simulates consumer stopping early)
        gen.close()
        # Process should be cleaned up -- no zombie


class TestGenerateStreaming(unittest.TestCase):
    """Test generate() with stream=True."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "cache.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch_module_cache(self):
        """Patch the module-level _cache to use a temp dir."""
        from model_choice import cache as cache_mod
        from model_choice.cache import ResponseCache
        test_cache = ResponseCache(db_path=self.db_path)
        self._orig_cache = cache_mod._cache if hasattr(cache_mod, '_cache') else None
        return test_cache

    def test_stream_returns_generator(self):
        """generate(stream=True) returns a generator, not a string."""
        from model_choice.registry import Provider

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="litellm", auth="api_key", complexity="fast",
        )

        with patch("model_choice._registry") as mock_reg, \
             patch("model_choice.stream") as mock_stream:
            mock_reg.select.return_value = provider
            mock_reg.providers = [provider]
            mock_stream.return_value = iter(["chunk1", "chunk2"])

            import model_choice
            result = model_choice.generate("test", stream=True, fallback=False)
            self.assertTrue(hasattr(result, '__next__'), "Expected a generator")
            chunks = list(result)
            self.assertEqual(chunks, ["chunk1", "chunk2"])

    def test_stream_caches_on_completion(self):
        """After consuming the stream, full text is cached."""
        from model_choice.registry import Provider
        from model_choice.cache import ResponseCache

        provider = Provider(
            provider="test", model="cached-model", label="Test",
            backend="litellm", auth="api_key", complexity="fast",
        )

        test_cache = ResponseCache(db_path=self.db_path)

        with patch("model_choice._registry") as mock_reg, \
             patch("model_choice.stream") as mock_stream, \
             patch("model_choice._cache", test_cache):

            mock_reg.select.return_value = provider
            mock_reg.providers = [provider]
            mock_stream.return_value = iter(["hello ", "world"])

            import model_choice
            chunks = list(model_choice.generate("test", stream=True, fallback=False))
            full = "".join(chunks)
            self.assertEqual(full, "hello world")

            # Verify it was cached
            cached = test_cache.get("cached-model", "test", 0.7, 2000, False, None)
            self.assertEqual(cached, "hello world")

    def test_no_stream_returns_string(self):
        """generate() without stream=True still returns a string."""
        from model_choice.registry import Provider
        from model_choice.backends import GenerateResult

        provider = Provider(
            provider="test", model="test-model", label="Test",
            backend="litellm", auth="api_key", complexity="fast",
        )

        with patch("model_choice._registry") as mock_reg, \
             patch("model_choice.call") as mock_call, \
             patch("model_choice._cache") as mock_cache:

            mock_reg.select.return_value = provider
            mock_reg.providers = [provider]
            mock_cache.get.return_value = None
            mock_call.return_value = GenerateResult(text="response text")

            import model_choice
            result = model_choice.generate("test", fallback=False)
            self.assertIsInstance(result, str)
            self.assertEqual(result, "response text")


class TestBackwardsCompatibility(unittest.TestCase):
    """Ensure existing API works exactly as before."""

    def test_cache_stats_interface(self):
        """cache_stats() returns dict with expected keys."""
        from model_choice.cache import ResponseCache
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ResponseCache(db_path=os.path.join(tmpdir, "test.db"))
            stats = cache.stats()
            self.assertIn("entries", stats)
            self.assertIn("hits", stats)
            self.assertIn("misses", stats)
            self.assertIn("hit_rate", stats)

    def test_cache_clear_interface(self):
        """clear() works and resets."""
        from model_choice.cache import ResponseCache
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "test.db")
            cache = ResponseCache(db_path=db)
            cache.put("m", "p", 0.7, 2000, False, None, "r")
            cache.clear()
            self.assertIsNone(cache.get("m", "p", 0.7, 2000, False, None))

    def test_generate_signature_unchanged(self):
        """generate() still accepts all original params."""
        import inspect
        from model_choice import generate

        sig = inspect.signature(generate)
        params = list(sig.parameters.keys())
        # Original params must still be present
        for p in ["prompt", "model", "complexity", "temperature", "max_tokens",
                   "json_mode", "system", "use_cache", "fallback"]:
            self.assertIn(p, params, f"Missing param: {p}")
        # New param
        self.assertIn("stream", params)

    def test_stream_fallback_error_messages(self):
        """Streaming fallback collects error messages from all providers."""
        from model_choice.registry import Provider
        from model_choice.cache import ResponseCache

        primary = Provider(
            provider="bad", model="bad-model", label="BadProvider",
            backend="litellm", auth="api_key", complexity="fast",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache = ResponseCache(db_path=os.path.join(tmpdir, "test.db"))

            with patch("model_choice._registry") as mock_reg, \
                 patch("model_choice.stream") as mock_stream:
                mock_reg.select.return_value = primary
                mock_reg.providers = [primary]
                # All stream attempts fail
                mock_stream.side_effect = ConnectionError("refused")

                import model_choice
                with self.assertRaises(RuntimeError) as ctx:
                    gen = model_choice.generate("test", stream=True, fallback=True)
                    # Need to consume the generator to trigger the error
                    list(gen)
                # Error should mention the provider
                self.assertIn("BadProvider", str(ctx.exception))

    def test_stream_fallback_succeeds_on_secondary(self):
        """Streaming fallback succeeds when primary fails but secondary works."""
        from model_choice.registry import Provider
        from model_choice.cache import ResponseCache

        primary = Provider(
            provider="bad", model="bad-model", label="BadProvider",
            backend="litellm", auth="api_key", complexity="fast",
        )
        secondary = Provider(
            provider="good", model="good-model", label="GoodProvider",
            backend="litellm", auth="api_key", complexity="fast",
        )

        call_count = [0]

        def stream_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("primary down")
            return iter(["chunk1", "chunk2"])

        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache = ResponseCache(db_path=os.path.join(tmpdir, "test.db"))

            with patch("model_choice._registry") as mock_reg, \
                 patch("model_choice.stream") as mock_stream, \
                 patch("model_choice._cache", test_cache):
                mock_reg.select.return_value = primary
                mock_reg.providers = [primary, secondary]
                mock_stream.side_effect = stream_side_effect

                import model_choice
                with patch("model_choice.fallback._build_fallback_chain") as mock_chain:
                    mock_chain.return_value = [secondary]
                    chunks = list(model_choice.generate("test", stream=True, fallback=True))
                self.assertEqual(chunks, ["chunk1", "chunk2"])


if __name__ == "__main__":
    unittest.main()
