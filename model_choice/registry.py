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

    # runtime -- set by Registry.refresh()
    available: Optional[bool] = field(default=None, repr=False)


class Registry:
    """Load tiers.yaml, check provider availability, select models."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._default_path()
        self.providers: list[Provider] = []
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
            try:
                urllib.request.urlopen(
                    f"{provider.api_base}/api/tags", timeout=5
                )
                return True
            except Exception:
                return False

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
    ) -> Optional[Provider]:
        """Pick a provider for the given complexity.

        Normal modes: picks the cheapest available at or below the tier.
        "thorough_strong": picks the STRONGEST available (last in list).
            Used by auto-classification for extreme-difficulty tasks.

        If model is specified, find it by model name or provider name,
        ignoring the complexity filter.
        """
        if any(p.available is None for p in self.providers):
            self.refresh()

        # Exact model or provider match (ignores complexity)
        if model:
            for p in self.providers:
                if p.model == model or p.provider == model:
                    return p if p.available else None
            return None

        # thorough_strong: pick STRONGEST available (last in list)
        if complexity == "thorough_strong":
            for p in reversed(self.providers):
                if p.available:
                    return p
            return None

        # balanced_only: pick cheapest provider at exactly balanced tier
        if complexity == "balanced_only":
            for p in self.providers:
                tier = COMPLEXITY_ORDER.get(p.complexity, 1)
                if tier == 1 and p.available:
                    return p
            # Fallback: try thorough if nothing at balanced
            for p in self.providers:
                tier = COMPLEXITY_ORDER.get(p.complexity, 2)
                if tier >= 1 and p.available:
                    return p
            return None

        # Pick cheapest available at or below requested complexity
        requested = COMPLEXITY_ORDER.get(complexity, 1)
        for p in self.providers:
            tier = COMPLEXITY_ORDER.get(p.complexity, 1)
            if tier <= requested and p.available:
                return p

        return None

    def list_available(self) -> list[Provider]:
        if any(p.available is None for p in self.providers):
            self.refresh()
        return [p for p in self.providers if p.available]
