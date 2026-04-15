"""model_choice -- universal LLM model selector and caller.

Usage:
    # Simplest: pick model, run prompt, get string
    from model_choice import generate
    text = generate("explain quicksort", complexity="fast")

    # Get parsed JSON
    from model_choice import generate_json
    data = generate_json("list 5 colors as JSON", complexity="fast")

    # See which model would be picked
    from model_choice import pick
    provider = pick(complexity="thorough")
    print(provider.label, provider.model)

    # Call a specific model
    text = generate("write a haiku", model="gemini-2.5-flash")

    # List what's available
    from model_choice import list_models
    for m in list_models():
        print(m["label"], m["available"])

    # CLI:
    #   model_choice "explain recursion" -c fast
    #   model_choice "architect a DB" -c thorough -v
    #   model_choice --list
"""

from .registry import Registry, Provider
from .backends import call
from .parsers import parse_json_output

_registry = Registry()


def generate(
    prompt: str,
    model: str | None = None,
    complexity: str = "balanced",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    json_mode: bool = False,
    system: str | None = None,
) -> str:
    """Run a prompt. Returns raw text string.

    Args:
        prompt: The text prompt.
        model: Exact model name or provider name. Overrides complexity.
        complexity: "fast", "balanced", or "thorough".
        temperature: Sampling temperature (litellm backends only).
        max_tokens: Max response tokens (litellm backends only).
        json_mode: If True, append JSON instruction to prompt.
                   NOTE: Returns str, not parsed object.
                   Use generate_json() for parsed results.
        system: Optional system prompt (litellm backends only).

    Returns:
        Raw text from the model.

    Raises:
        RuntimeError: No available model found or backend error.
    """
    provider = _registry.select(complexity=complexity, model=model)
    if not provider:
        raise RuntimeError(
            f"No available model for complexity={complexity}"
            + (f" model={model}" if model else "")
        )
    return call(provider, prompt, temperature, max_tokens, json_mode, system)


def generate_json(
    prompt: str,
    model: str | None = None,
    complexity: str = "balanced",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    system: str | None = None,
) -> object:
    """Run a prompt requesting JSON. Returns parsed Python object.

    Same as generate() but:
    - Forces json_mode=True
    - Parses the response through parse_json_output()
    - Returns dict, list, or whatever the model output

    Raises:
        RuntimeError: No available model.
        ValueError: Response couldn't be parsed as JSON.
    """
    raw = generate(
        prompt, model, complexity, temperature, max_tokens,
        json_mode=True, system=system,
    )
    return parse_json_output(raw)


def choose(
    prompt: str,
    **kwargs,
) -> str:
    """Alias for generate(). Same signature."""
    return generate(prompt, **kwargs)


def pick(
    complexity: str = "balanced",
    model: str | None = None,
) -> Provider | None:
    """Select a provider without calling it."""
    return _registry.select(complexity=complexity, model=model)


def list_models() -> list[dict]:
    """List all configured providers with availability status."""
    if any(p.available is None for p in _registry.providers):
        _registry.refresh()
    return [
        {
            "provider": p.provider,
            "model": p.model,
            "label": p.label,
            "complexity": p.complexity,
            "available": p.available,
        }
        for p in _registry.providers
    ]


def refresh():
    """Force re-check all provider availability."""
    _registry.refresh()
