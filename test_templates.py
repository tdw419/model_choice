"""Tests for model_choice templates."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTemplateBuiltins(unittest.TestCase):
    """Built-in templates are always available."""

    def test_builtin_templates_exist(self):
        from model_choice import list_templates
        tmpls = list_templates()
        for name in ["default", "ai_daemon", "agent", "ollama_only",
                      "cloud_only", "cheap", "thorough"]:
            self.assertIn(name, tmpls)

    def test_ai_daemon_uses_ollama_only(self):
        from model_choice import pick
        provider = pick(template="ai_daemon")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider, "ollama")

    def test_agent_starts_with_zai(self):
        from model_choice import pick
        provider = pick(template="agent", complexity="balanced")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider, "zai")

    def test_default_template_uses_all_providers(self):
        from model_choice import list_templates
        tmpls = list_templates()
        self.assertEqual(tmpls["default"]["providers"], ["*"])

    def test_ollama_only_excludes_cloud(self):
        from model_choice import pick
        provider = pick(template="ollama_only", complexity="thorough")
        # Even at thorough, ollama_only should only give ollama
        # If ollama isn't available this returns None, which is correct
        if provider:
            self.assertEqual(provider.provider, "ollama")

    def test_cloud_only_excludes_ollama(self):
        from model_choice import pick
        provider = pick(template="cloud_only", complexity="fast")
        # cloud_only has zai/gemini/claude -- no ollama
        # At fast complexity, none of those match (zai=balanced, gemini/claude=thorough)
        # So this should return None (no fast cloud providers)
        self.assertIsNone(provider)

    def test_thorough_template_picks_strongest(self):
        from model_choice import pick
        provider = pick(template="thorough", complexity="thorough")
        self.assertIsNotNone(provider)


class TestTemplatePerCall(unittest.TestCase):
    """Template parameter on individual calls."""

    def test_pick_with_template(self):
        from model_choice import pick
        p = pick(template="ai_daemon")
        self.assertEqual(p.provider, "ollama")

    def test_pick_without_template(self):
        from model_choice import pick
        # Default behavior -- picks cheapest available (ollama if running)
        p = pick()
        self.assertIsNotNone(p)

    def test_pick_model_overrides_template(self):
        from model_choice import pick
        # model= with template still respects template's provider list
        # ai_daemon only allows ollama, so model="zai" returns None
        p = pick(model="zai", template="ai_daemon")
        self.assertIsNone(p)
        # But model="ollama" within ai_daemon works
        p2 = pick(model="ollama", template="ai_daemon")
        self.assertIsNotNone(p2)
        self.assertEqual(p2.provider, "ollama")


class TestTemplateConfigure(unittest.TestCase):
    """Module-level configure() sets defaults."""

    def test_configure_template(self):
        from model_choice import configure, pick, _active_template
        # Save original
        import model_choice
        orig = model_choice._active_template
        try:
            configure(template="ai_daemon")
            self.assertEqual(model_choice._active_template, "ai_daemon")
            p = pick()
            self.assertEqual(p.provider, "ollama")
        finally:
            model_choice._active_template = orig

    def test_configure_complexity(self):
        from model_choice import configure
        import model_choice
        orig = model_choice._default_complexity
        try:
            configure(complexity="thorough")
            self.assertEqual(model_choice._default_complexity, "thorough")
        finally:
            model_choice._default_complexity = orig


class TestTemplateEnvVar(unittest.TestCase):
    """MODEL_CHOICE_TEMPLATE env var."""

    def test_env_var_sets_template(self):
        from model_choice.templates import resolve_template
        with patch.dict(os.environ, {"MODEL_CHOICE_TEMPLATE": "ollama_only"}):
            result = resolve_template(None)
            self.assertEqual(result, "ollama_only")

    def test_explicit_arg_overrides_env(self):
        from model_choice.templates import resolve_template
        with patch.dict(os.environ, {"MODEL_CHOICE_TEMPLATE": "ollama_only"}):
            result = resolve_template("agent")
            self.assertEqual(result, "agent")

    def test_no_env_no_arg_returns_none(self):
        from model_choice.templates import resolve_template
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if present
            os.environ.pop("MODEL_CHOICE_TEMPLATE", None)
            result = resolve_template(None)
            self.assertIsNone(result)


class TestUserTemplates(unittest.TestCase):
    """User-defined templates in tiers.yaml."""

    def test_user_template_from_config(self):
        """User templates in config override/add to builtins."""
        import tempfile
        import yaml

        tmpdir = tempfile.mkdtemp()
        config_path = os.path.join(tmpdir, "tiers.yaml")

        config = {
            "providers": [
                {
                    "provider": "test",
                    "model": "test-model",
                    "label": "Test",
                    "backend": "litellm",
                    "auth": "local",
                    "complexity": "fast",
                    "api_base": "http://localhost:9999",
                }
            ],
            "templates": [
                {
                    "name": "my_template",
                    "providers": ["test"],
                    "default_complexity": "fast",
                    "default_temperature": 0.3,
                }
            ],
        }

        with open(config_path, "w") as f:
            yaml.dump(config, f)

        from model_choice.registry import Registry
        reg = Registry(config_path=config_path)

        self.assertIn("my_template", reg.templates)
        tmpl = reg.templates["my_template"]
        self.assertEqual(tmpl.providers, ["test"])
        self.assertEqual(tmpl.default_temperature, 0.3)

        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
