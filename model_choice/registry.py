"""Registry -- load config, check availability, select model."""

import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import yaml

COMPLEXITY_ORDER = {"fast": 0, "balanced": 1, "thorough": 2}


@dataclass
class Provider:
    provider: str
    model: str
    label: str
    backend: str            # "litellm" or "cli"
    auth: str               # "local", "api_key", "oauth"
    complexity: str         # "fast", "balanced", "thorough"

    # litellm fields
    api_base: Optional[str] = None
    env_key: Optional[str] = None

    # cli fields
    cli_cmd: Optional[str] = None

    # rate limiting
    max_concurrent: Optional[int] = None   # e.g. 4 for ZAI
    min_interval: Optional[float] = None   # e.g. 1.0 seconds

    # runtime -- set by Registry.refresh()
    available: Optional[bool] = field(default=None, repr=False)


class Registry:
    """Load tiers.yaml, check provider availability, select models."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._default_path()
        self.providers: list[Provider] = []
        self.templates: dict[str, "Template"] = {}
        self._env_loaded = False
        self._load()

    @staticmethod
    def _default_path() -> str:
        xdg = os.environ.get("XDG_CONFIG_HOME",
                             os.path.expanduser("~/.config"))
        return os.path.join(xdg, "model_choice", "tiers.yaml")

    def _load(self):
        if not os.path.exists(self.config_path):
            from .config import generate_default_config
            generate_default_config(self.config_path)

        with open(self.config_path) as f:
            data = yaml.safe_load(f)

        valid_fields = set(Provider.__dataclass_fields__.keys())
        for entry in data.get("providers", []):
            filtered = {k: v for k, v in entry.items() if k in valid_fields}
            self.providers.append(Provider(**filtered))

        # Load templates from same config
        from .templates import BUILTINS, Template
        for name, cfg in BUILTINS.items():
            self.templates[name] = Template(name=name, **cfg)
        for entry in data.get("templates", []):
            name = entry.pop("name")
            self.templates[name] = Template(name=name, **entry)

    # ---- env key loading ----

    def _ensure_env_keys(self):
        """Load API keys from ~/.bashrc into os.environ, once."""
        if self._env_loaded:
            return

        needed = {
            p.env_key for p in self.providers
            if p.auth == "api_key" and p.env_key
            and not os.environ.get(p.env_key)
        }

        if needed:
            bashrc = os.path.expanduser("~/.bashrc")
            if os.path.exists(bashrc):
                with open(bashrc) as f:
                    for line in f:
                        line = line.strip()
                        for var in list(needed):
                            if line.startswith(f"export {var}="):
                                val = (line.split("=", 1)[1]
                                       .strip().strip('"').strip("'"))
                                os.environ[var] = val
                                needed.discard(var)
                                break
        self._env_loaded = True

    # ---- availability ----

    def check_available(self, provider: Provider) -> bool:
        """Check if a single provider is reachable/authed/installed."""
        if provider.auth == "local":
            from .ollama import health_check
            return health_check(provider.api_base)

        elif provider.auth == "api_key":
            self._ensure_env_keys()
            return bool(os.environ.get(provider.env_key or ""))

        elif provider.auth == "oauth":
            try:
                r = subprocess.run(
                    ["which", provider.cli_cmd],
                    capture_output=True, timeout=5,
                )
                return r.returncode == 0
            except Exception:
                return False

        return False

    def refresh(self):
        """Re-check all providers. Call if env changed mid-session."""
        self._ensure_env_keys()
        for p in self.providers:
            p.available = self.check_available(p)

    # ---- selection ----

    def select(
        self,
        complexity: str = "balanced",
        model: Optional[str] = None,
        template: Optional[str] = None,
        manage_ollama: bool = False,
    ) -> Optional[Provider]:
        """Pick a provider for the given complexity.

        Normal modes: picks the cheapest available at or below the tier.
        "thorough_strong": picks the STRONGEST available (last in list).
            Used by auto-classification for extreme-difficulty tasks.

        If model is specified, find it by model name or provider name,
        ignoring the complexity filter.

        If template is specified, only consider providers in that template.

        If manage_ollama is True, attempt to start ollama and load models
        when ollama providers are unavailable.
        """
        if any(p.available is None for p in self.providers):
            self.refresh()

        providers = self._filter_providers(template)

        # Auto-manage ollama if requested
        if manage_ollama:
            providers = self._ensure_ollama(providers)

        # Exact model or provider match (ignores complexity)
        if model:
            for p in providers:
                if p.model == model or p.provider == model:
                    return p if p.available else None
            return None

        # thorough_strong: pick STRONGEST available (last in list)
        if complexity == "thorough_strong":
            for p in reversed(providers):
                if p.available:
                    return p
            return None

        # balanced_only: pick cheapest provider at exactly balanced tier
        if complexity == "balanced_only":
            for p in providers:
                tier = COMPLEXITY_ORDER.get(p.complexity, 1)
                if tier == 1 and p.available:
                    return p
            # Fallback: try thorough if nothing at balanced
            for p in providers:
                tier = COMPLEXITY_ORDER.get(p.complexity, 2)
                if tier >= 1 and p.available:
                    return p
            return None

        # Pick cheapest available at or below requested complexity
        requested = COMPLEXITY_ORDER.get(complexity, 1)
        for p in providers:
            tier = COMPLEXITY_ORDER.get(p.complexity, 1)
            if tier <= requested and p.available:
                return p

        return None

    def list_available(self) -> list[Provider]:
        if any(p.available is None for p in self.providers):
            self.refresh()
        return [p for p in self.providers if p.available]

    # ---- templates ----

    def _filter_providers(self, template: Optional[str]) -> list[Provider]:
        """Filter providers to only those in the template.

        If template is None or "default", returns all providers.
        If template name is unknown, returns all providers.
        """
        if not template or template == "default":
            return self.providers

        tmpl = self.templates.get(template)
        if not tmpl:
            return self.providers

        # Wildcard means all providers
        if tmpl.providers == ["*"]:
            return self.providers

        # Filter by provider name, preserving template order
        allowed = set(tmpl.providers)
        filtered = [p for p in self.providers if p.provider in allowed]
        # Re-sort to match template's provider order
        order = {name: i for i, name in enumerate(tmpl.providers)}
        filtered.sort(key=lambda p: order.get(p.provider, 999))
        return filtered

    def get_template(self, name: str) -> Optional["Template"]:
        """Get a template by name. Returns None if not found."""
        return self.templates.get(name)

    def list_templates(self) -> dict[str, "Template"]:
        """Return all loaded templates."""
        return dict(self.templates)

    # ---- ollama management ----

    def _ensure_ollama(self, providers: list[Provider]) -> list[Provider]:
        """Auto-manage ollama providers: start, pull model, recover.

        For each ollama provider that's unavailable:
        1. Try to start ollama
        2. Try to pull the model
        3. If still unhealthy, try restart

        Updates provider.available in place.
        """
        from .ollama import ensure_running, recover, health_check

        for p in providers:
            if p.auth != "local" or p.available:
                continue

            # Ollama is down -- try to fix it
            model_name = p.model.split("/", 1)[-1] if "/" in p.model else p.model

            ok = ensure_running(
                model=model_name,
                api_base=p.api_base,
                auto_start=True,
                auto_pull=True,
            )

            if ok:
                p.available = True
            else:
                # Last resort: full restart
                if recover(p.api_base):
                    # Re-check model after restart
                    from .ollama import model_loaded, pull_model
                    if not model_loaded(model_name, p.api_base):
                        pull_model(model_name)
                    p.available = health_check(p.api_base)

        return providers
