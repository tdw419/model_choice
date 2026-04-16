"""model_choice -- universal LLM model selector and caller.

Usage:
    # Simplest: pick model, run prompt, get string
    from model_choice import generate
    text = generate("explain quicksort", complexity="fast")

    # Auto-classify: let the local model decide difficulty
    text = generate("explain quicksort", complexity="auto")

    # Streaming: iterate over text chunks as they arrive
    for chunk in generate("explain quicksort", stream=True):
        print(chunk, end="", flush=True)

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

    # Usage stats
    from model_choice import cost_summary, cache_stats
    print(cost_summary())
    print(cache_stats())

    # CLI:
    #   model_choice "explain recursion" -c fast
    #   model_choice "architect a DB" -c auto
    #   model_choice --list
    #   model_choice "prompt" --no-cache --no-fallback
"""

from typing import Generator, Optional

from .registry import Registry, Provider
from .backends import call, stream, GenerateResult
from .parsers import parse_json_output
from .classifier import classify
from .cache import ResponseCache
from .tracking import CostTracker
from .fallback import call_with_fallback
from .templates import Template, resolve_template
from .rate_limiter import get_limiter

_registry = Registry()
_cache = ResponseCache()
_tracker = CostTracker()

# Module-level template (set via configure() or env var)
_active_template: Optional[str] = None
_manage_ollama: bool = False


def _resolve_complexity(complexity: str, prompt: str) -> str:
    """Resolve 'auto' to a real tier. Pass-through for everything else."""
    if complexity == "auto":
        return classify(prompt, _registry)
    return complexity


def _rate_limit(provider: Provider):
    """Context manager: rate-limit calls to a provider if configured.

    If the provider has max_concurrent or min_interval set, acquires a slot
    from the cross-process rate limiter. Otherwise, a no-op context manager.
    """
    if provider.max_concurrent or provider.min_interval:
        return get_limiter().limit(
            provider=provider.provider,
            max_concurrent=provider.max_concurrent or 0,
            min_interval=provider.min_interval or 0.0,
            timeout=60.0,
        )
    from contextlib import nullcontext
    return nullcontext()


def _stream_wrapper(
    provider: Provider,
    prompt: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    system: Optional[str],
    use_cache: bool,
) -> Generator[str, None, None]:
    """Wrap streaming backend to collect full text for caching on completion."""
    collected = []
    try:
        for chunk in stream(provider, prompt, temperature, max_tokens,
                            json_mode, system):
            collected.append(chunk)
            yield chunk
    finally:
        # Cache the complete response even if the consumer stops early
        if use_cache and collected:
            full_text = "".join(collected)
            _cache.put(provider.model, prompt, temperature,
                       max_tokens, json_mode, system, full_text)
            _tracker.record(provider.provider, success=True)


def generate(
    prompt: str,
    model: str | None = None,
    complexity: str = "balanced",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    json_mode: bool = False,
    system: str | None = None,
    use_cache: bool = True,
    fallback: bool = True,
    stream: bool = False,
    template: str | None = None,
    manage_ollama: bool = False,
) -> str | Generator[str, None, None]:
    """Run a prompt. Returns raw text string, or a generator if stream=True.

    Args:
        prompt: The text prompt.
        model: Exact model name or provider name. Overrides complexity.
        complexity: "fast", "balanced", "thorough", or "auto".
                    "auto" uses the local model to classify difficulty.
        temperature: Sampling temperature (litellm backends only).
        max_tokens: Max response tokens (litellm backends only).
        json_mode: If True, append JSON instruction to prompt.
                   NOTE: Returns str, not parsed object.
                   Use generate_json() for parsed results.
        system: Optional system prompt (litellm backends only).
        use_cache: If True, return cached response for identical calls.
        fallback: If True, try next provider on failure.
        stream: If True, return a generator yielding text chunks.
                Streaming skips cache lookup but caches the full response
                when the generator is exhausted.
        template: Named preset constraining provider selection and defaults.
                  Falls back to module-level template from configure() or
                  MODEL_CHOICE_TEMPLATE env var.
        manage_ollama: If True, auto-start ollama and pull models when
                       ollama providers are unavailable.

    Returns:
        Raw text from the model, or Generator[str] if stream=True.

    Raises:
        RuntimeError: No available model found or all providers failed.
    """
    # Resolve template: explicit arg > module-level > env var
    tmpl_name = resolve_template(template) or _active_template
    tmpl = _registry.get_template(tmpl_name) if tmpl_name else None

    # Apply template defaults (call-level args take precedence)
    if tmpl:
        if complexity == "balanced":  # only override if caller didn't change
            complexity = tmpl.default_complexity
        if temperature == 0.7:
            temperature = tmpl.default_temperature
        if max_tokens == 2000:
            max_tokens = tmpl.default_max_tokens
        if fallback and not tmpl.fallback:
            fallback = tmpl.fallback
        if use_cache and not tmpl.use_cache:
            use_cache = tmpl.use_cache

    resolved = _resolve_complexity(complexity, prompt)
    provider = _registry.select(
        complexity=resolved, model=model, template=tmpl_name,
        manage_ollama=manage_ollama or _manage_ollama,
    )
    if not provider:
        raise RuntimeError(
            f"No available model for complexity={resolved}"
            + (f" template={tmpl_name}" if tmpl_name else "")
            + (f" model={model}" if model else "")
        )

    # Streaming path (rate-limited)
    if stream:
        if fallback:
            return _stream_with_fallback(
                provider, prompt, temperature, max_tokens,
                json_mode, system, resolved, use_cache,
            )
        # Rate limit wraps the stream start
        limiter_ctx = _rate_limit(provider)
        limiter_ctx.__enter__()
        gen = _stream_wrapper(
            provider, prompt, temperature, max_tokens,
            json_mode, system, use_cache,
        )
        # Wrap generator to release rate limit on exhaustion
        def _rate_limited_gen():
            try:
                yield from gen
            finally:
                try:
                    limiter_ctx.__exit__(None, None, None)
                except Exception:
                    pass
        return _rate_limited_gen()

    # Synchronous path -- check cache first
    if use_cache:
        cached = _cache.get(provider.model, prompt, temperature,
                            max_tokens, json_mode, system)
        if cached is not None:
            _tracker.record(provider.provider, success=True)
            return cached

    # Call with fallback (rate-limited)
    try:
        with _rate_limit(provider):
            if fallback:
                result, used_provider = call_with_fallback(
                    _registry, provider, prompt, temperature, max_tokens,
                    json_mode, system, resolved,
                )
            else:
                result = call(provider, prompt, temperature, max_tokens,
                              json_mode, system)
                used_provider = provider

        # Track usage
        _tracker.record(
            used_provider.provider, success=True,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        )

        # Cache the response
        if use_cache:
            _cache.put(provider.model, prompt, temperature,
                       max_tokens, json_mode, system, result.text)

        return result.text

    except Exception as e:
        _tracker.record(provider.provider, success=False)
        raise


def _stream_with_fallback(
    start_provider: Provider,
    prompt: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    system: Optional[str],
    complexity: str,
    use_cache: bool,
) -> Generator[str, None, None]:
    """Stream with fallback: try primary, fall back to next on failure.

    Falls back BEFORE yielding any chunks if the initial connection fails.
    If streaming has already started, we let the error propagate (can't
    cleanly switch mid-stream).
    """
    from .fallback import _build_fallback_chain

    errors = []
    try:
        # Check if we can start streaming (try the first chunk)
        gen = stream(start_provider, prompt, temperature, max_tokens,
                     json_mode, system)
        first_chunk = next(gen)
    except Exception as e:
        # Primary failed to even start -- try fallbacks
        errors.append(f"{start_provider.label}: {e}")
        chain = _build_fallback_chain(_registry, start_provider, complexity)
        for fb_provider in chain:
            try:
                gen = stream(fb_provider, prompt, temperature, max_tokens,
                             json_mode, system)
                first_chunk = next(gen)
                start_provider = fb_provider
                break
            except Exception as e2:
                errors.append(f"{fb_provider.label}: {e2}")
                continue
        else:
            raise RuntimeError(
                f"All providers failed for streaming: {'; '.join(errors)}"
            )

    # Yield first chunk, then the rest, with caching
    collected = [first_chunk]
    yield first_chunk
    try:
        for chunk in gen:
            collected.append(chunk)
            yield chunk
    finally:
        if use_cache and collected:
            full_text = "".join(collected)
            _cache.put(start_provider.model, prompt, temperature,
                       max_tokens, json_mode, system, full_text)
            _tracker.record(start_provider.provider, success=True)


def generate_json(
    prompt: str,
    model: str | None = None,
    complexity: str = "balanced",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    system: str | None = None,
    use_cache: bool = True,
    fallback: bool = True,
    template: str | None = None,
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
        use_cache=use_cache, fallback=fallback, template=template,
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
    template: str | None = None,
    manage_ollama: bool = False,
) -> Provider | None:
    """Select a provider without calling it."""
    tmpl_name = resolve_template(template) or _active_template
    return _registry.select(complexity=complexity, model=model,
                            template=tmpl_name,
                            manage_ollama=manage_ollama or _manage_ollama)


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


def cost_summary() -> dict:
    """Get usage stats per provider."""
    return _tracker.summary()


def cost_totals() -> dict:
    """Get aggregated usage stats."""
    return _tracker.totals()


def cache_stats() -> dict:
    """Get cache hit/miss stats."""
    return _cache.stats()


def clear_cache():
    """Clear the response cache."""
    _cache.clear()


def reset_stats():
    """Reset all cost tracking counters."""
    _tracker.reset()


def configure(
    template: str | None = None,
    complexity: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    manage_ollama: bool | None = None,
):
    """Set module-level defaults for all future calls.

    These defaults are overridden by per-call arguments.

    Args:
        template: Named preset to use for provider selection.
        complexity: Default complexity tier.
        temperature: Default sampling temperature.
        max_tokens: Default max response tokens.
        manage_ollama: If True, auto-start ollama and pull models.
    """
    global _active_template, _default_complexity, _default_temperature
    global _default_max_tokens, _manage_ollama

    if template is not None:
        _active_template = template
    if complexity is not None:
        _default_complexity = complexity
    if temperature is not None:
        _default_temperature = temperature
    if max_tokens is not None:
        _default_max_tokens = max_tokens
    if manage_ollama is not None:
        _manage_ollama = manage_ollama


def list_templates() -> dict[str, dict]:
    """List all available templates with their settings."""
    return {
        name: {
            "providers": tmpl.providers,
            "default_complexity": tmpl.default_complexity,
            "default_temperature": tmpl.default_temperature,
            "default_max_tokens": tmpl.default_max_tokens,
            "fallback": tmpl.fallback,
            "use_cache": tmpl.use_cache,
        }
        for name, tmpl in _registry.templates.items()
    }


# Module-level defaults (can be overridden via configure())
_default_complexity: str = "balanced"
_default_temperature: float = 0.7
_default_max_tokens: int = 2000


# ---- ollama management (public) ----

def ollama_status() -> dict:
    """Get ollama status: running, models loaded, health."""
    from .ollama import health_check, list_models
    healthy = health_check()
    return {
        "running": healthy,
        "models": list_models() if healthy else [],
    }


def ollama_start() -> bool:
    """Start ollama if not running. Returns True if healthy after attempt."""
    from .ollama import start_ollama
    return start_ollama()


def ollama_restart() -> bool:
    """Restart ollama. Returns True if healthy after restart."""
    from .ollama import restart_ollama
    return restart_ollama()


def ollama_pull(model: str) -> bool:
    """Pull a model. Handles 'ollama/name' prefix."""
    from .ollama import pull_model
    return pull_model(model)


# ---- rate limiting (public) ----

def rate_limit_status() -> dict:
    """Get current active requests per provider."""
    return get_limiter().status()


def rate_limit_reset():
    """Clear all rate limit slots (emergency reset)."""
    get_limiter().reset()
