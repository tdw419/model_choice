"""Tests for model_choice ollama management."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthCheck(unittest.TestCase):
    """Ollama health check."""

    def test_health_check_running(self):
        from model_choice.ollama import health_check
        # Ollama is actually running on this machine
        self.assertTrue(health_check())

    def test_health_check_down(self):
        from model_choice.ollama import health_check
        self.assertFalse(health_check("http://localhost:19999"))


class TestModelLoaded(unittest.TestCase):
    """Model presence detection."""

    def test_model_loaded_exact(self):
        from model_choice.ollama import model_loaded
        self.assertTrue(model_loaded("qwen2.5-coder:14b"))

    def test_model_loaded_litellm_prefix(self):
        from model_choice.ollama import model_loaded
        self.assertTrue(model_loaded("ollama/qwen2.5-coder:14b"))

    def test_model_loaded_without_tag(self):
        from model_choice.ollama import model_loaded
        # 'qwen2.5-coder' should match 'qwen2.5-coder:14b'
        self.assertTrue(model_loaded("qwen2.5-coder"))

    def test_model_not_loaded(self):
        from model_choice.ollama import model_loaded
        self.assertFalse(model_loaded("nonexistent-model:99b"))


class TestListModels(unittest.TestCase):
    """List models from running ollama."""

    def test_list_models(self):
        from model_choice.ollama import list_models
        models = list_models()
        self.assertIsInstance(models, list)
        self.assertTrue(len(models) > 0)
        self.assertIn("qwen2.5-coder:14b", models)

    def test_list_models_down(self):
        from model_choice.ollama import list_models
        models = list_models("http://localhost:19999")
        self.assertEqual(models, [])


class TestFindBinary(unittest.TestCase):
    """Binary detection."""

    def test_find_binary(self):
        from model_choice.ollama import _find_binary
        binary = _find_binary()
        self.assertIsNotNone(binary)
        self.assertTrue(os.path.isfile(binary))

    def test_find_binary_path(self):
        from model_choice.ollama import _find_binary
        binary = _find_binary()
        # Should be the symlink in ~/.local/bin or the real binary
        self.assertIn("ollama", binary)


class TestSystemdDetection(unittest.TestCase):
    """Systemd user service detection."""

    def test_has_systemd_service(self):
        from model_choice.ollama import _has_systemd_service
        # Ollama is set up as systemd user service on this machine
        self.assertTrue(_has_systemd_service())


class TestOllamaStatusAPI(unittest.TestCase):
    """Public ollama_status() API."""

    def test_status(self):
        from model_choice import ollama_status
        status = ollama_status()
        self.assertIn("running", status)
        self.assertIn("models", status)
        self.assertTrue(status["running"])
        self.assertIsInstance(status["models"], list)


class TestEnsureRunning(unittest.TestCase):
    """ensure_running() with ollama already up."""

    def test_ensure_running_already_up(self):
        from model_choice.ollama import ensure_running
        # Ollama is already running -- should return True immediately
        result = ensure_running()
        self.assertTrue(result)

    def test_ensure_running_model_check(self):
        from model_choice.ollama import ensure_running
        # Model is already loaded
        result = ensure_running(model="qwen2.5-coder:14b")
        self.assertTrue(result)

    def test_ensure_running_no_auto_start(self):
        from model_choice.ollama import ensure_running
        # Already running, auto_start=False should still work
        result = ensure_running(auto_start=False)
        self.assertTrue(result)

    def test_ensure_running_down_port(self):
        from model_choice.ollama import ensure_running
        # Non-existent port, no auto-start
        result = ensure_running(
            api_base="http://localhost:19999",
            auto_start=False,
        )
        self.assertFalse(result)


class TestManageOllamaIntegration(unittest.TestCase):
    """manage_ollama flag integration with generate/pick."""

    def test_pick_manage_ollama(self):
        from model_choice import pick
        # Ollama is running, should work with manage_ollama
        p = pick(template="ai_daemon", manage_ollama=True)
        self.assertIsNotNone(p)
        self.assertEqual(p.provider, "ollama")

    def test_configure_manage_ollama(self):
        from model_choice import configure, _manage_ollama
        import model_choice
        orig = model_choice._manage_ollama
        try:
            configure(manage_ollama=True)
            self.assertTrue(model_choice._manage_ollama)
        finally:
            model_choice._manage_ollama = orig


if __name__ == "__main__":
    unittest.main()
