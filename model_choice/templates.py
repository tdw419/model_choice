"""Templates -- named presets that constrain provider selection and defaults.

A template selects a subset of providers and sets default call parameters.
Useful when different consumers need different models (e.g. ai_daemon always
uses ollama, while other agents default to zai).
"""

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class Template:
    """A named configuration preset."""

    name: str
    providers: list[str]          # provider names to include, in order
    default_complexity: str = "balanced"
    default_temperature: float = 0.7
    default_max_tokens: int = 2000
    fallback: bool = True
    use_cache: bool = True

    def __repr__(self):
        return (
            f"Template({self.name!r}, providers={self.providers}, "
            f"complexity={self.default_complexity!r})"
        )


# Built-in templates
BUILTINS: dict[str, dict] = {
    "default": {
        "providers": ["*"],  # wildcard = all providers from config
        "default_complexity": "balanced",
    },
    "ai_daemon": {
        "providers": ["ollama"],
        "default_complexity": "fast",
        "fallback": False,
    },
    "agent": {
        "providers": ["zai", "ollama", "gemini", "claude"],
        "default_complexity": "balanced",
    },
    "ollama_only": {
        "providers": ["ollama"],
        "default_complexity": "fast",
        "default_temperature": 0.7,
    },
    "hermes": {
        "providers": ["zai", "gemini", "claude", "ollama"],
        "default_complexity": "balanced",
    },
    "cloud_only": {
        "providers": ["zai", "gemini", "claude"],
        "default_complexity": "balanced",
    },
    "cheap": {
        "providers": ["ollama", "zai"],
        "default_complexity": "fast",
    },
    "thorough": {
        "providers": ["*"],
        "default_complexity": "thorough",
    },
}


def load_templates(config_path: Optional[str] = None) -> dict[str, Template]:
    """Load templates from config file + builtins.

    User-defined templates in tiers.yaml override builtins with the same name.
    Returns dict of name -> Template.
    """
    templates: dict[str, Template] = {}

    # Start with builtins
    for name, cfg in BUILTINS.items():
        templates[name] = Template(name=name, **cfg)

    # Load user templates from config
    if config_path is None:
        xdg = os.environ.get("XDG_CONFIG_HOME",
                             os.path.expanduser("~/.config"))
        config_path = os.path.join(xdg, "model_choice", "tiers.yaml")

    if os.path.exists(config_path):
        with open(config_path) as f:
            data = yaml.safe_load(f)

        for entry in data.get("templates", []):
            name = entry.pop("name")
            templates[name] = Template(name=name, **entry)

    return templates


def resolve_template(
    template_name: Optional[str],
    env_var: str = "MODEL_CHOICE_TEMPLATE",
) -> Optional[str]:
    """Resolve which template to use.

    Priority: explicit argument > env var > None (no template).
    """
    if template_name:
        return template_name
    return os.environ.get(env_var)
