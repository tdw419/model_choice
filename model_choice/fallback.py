"""Fallback chains -- retry with next provider on failure."""

from .registry import Registry, Provider, COMPLEXITY_ORDER


def _build_fallback_chain(registry: Registry, start_provider: Provider,
                           complexity: str) -> list[Provider]:
    """Build an ordered list of fallback providers after start_provider.

    Walks the providers list starting after start_provider, collecting
    available ones that match the complexity tier or higher.
    """
    chain = []
    started = False
    requested = COMPLEXITY_ORDER.get(
        _canonical_complexity(complexity), 2
    )

    for p in registry.providers:
        if p is start_provider:
            started = True
            continue
        if not started:
            continue
        if not p.available:
            continue
        # Only include providers at or below the effective tier
        tier = COMPLEXITY_ORDER.get(p.complexity, 2)
        if tier <= requested:
            chain.append(p)

    return chain


def _canonical_complexity(complexity: str) -> str:
    """Map internal modes to their canonical complexity tier."""
    if complexity in ("balanced_only",):
        return "balanced"
    if complexity in ("thorough_strong",):
        return "thorough"
    return complexity


def call_with_fallback(
    registry: Registry,
    provider: Provider,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    json_mode: bool = False,
    system: str | None = None,
    complexity: str = "balanced",
) -> tuple[str, Provider]:
    """Call provider, fall back to next available on failure.

    Returns (GenerateResult, provider_that_succeeded).
    Raises RuntimeError only if ALL providers in the chain fail.
    """
    from .backends import call as backend_call

    errors = []

    # Try the primary provider
    try:
        result = backend_call(provider, prompt, temperature, max_tokens,
                              json_mode, system)
        return result, provider
    except Exception as e:
        errors.append(f"{provider.label}: {e}")

    # Build fallback chain and try each
    fallbacks = _build_fallback_chain(registry, provider, complexity)
    for fallback in fallbacks:
        try:
            result = backend_call(fallback, prompt, temperature, max_tokens,
                                  json_mode, system)
            return result, fallback
        except Exception as e:
            errors.append(f"{fallback.label}: {e}")

    raise RuntimeError(
        f"All providers failed: {'; '.join(errors)}"
    )
