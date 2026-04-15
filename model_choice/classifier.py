"""Auto-classify task difficulty using the local model."""

from .registry import Registry, COMPLEXITY_ORDER

_CLASSIFY_PROMPT = """\
Rate this task's AI difficulty. Reply with exactly one word from: easy hard extreme

easy = simple lookup, greeting, basic math, one-liner, list items
hard = write code, analyze data, compare options, summarize, debug
extreme = architect systems, design algorithms, deep analysis, multi-step reasoning

Task: """

_VALID = {"easy", "hard", "extreme"}
_WORD_MAP = {
    # easy task -> use a fast/cheap model (Ollama)
    "easy": "fast",
    # hard task -> use a mid-tier model (ZAI), skip local
    "hard": "balanced_only",
    # extreme task -> use the strongest model available (Gemini/Claude)
    "extreme": "thorough_strong",
}


def classify(prompt: str, registry: Registry) -> str:
    """Classify a prompt's difficulty. Returns complexity tier string.

    Uses the cheapest available litellm provider (typically Ollama local)
    to rate the task. Falls back to "balanced" if classification fails.

    Returns one of: "fast", "balanced", "thorough"
    """
    # Ensure availability is checked -- may not have been triggered yet
    if any(p.available is None for p in registry.providers):
        registry.refresh()

    # Find a litellm provider for classification (cheapest first)
    classifier_provider = None
    for p in registry.providers:
        if p.backend == "litellm" and p.available:
            classifier_provider = p
            break

    if not classifier_provider:
        # No local model available, fall back
        return "balanced"

    try:
        from .backends import call
        raw = call(
            classifier_provider,
            _CLASSIFY_PROMPT + prompt,
            temperature=0.0,
            max_tokens=10,
            json_mode=False,
            system=None,
        )
        word = raw.strip().lower()

        # Handle cases like "easy." or "Easy!" or "hard\n"
        word = word.rstrip(".!?\n ")

        # Direct match
        if word in _VALID:
            return _WORD_MAP[word]

        # Partial match -- sometimes models say "this is easy" or "easy task"
        for valid in _VALID:
            if valid in word:
                return _WORD_MAP[valid]

        # Number-like responses (some models say "1" for easy, "3" for extreme)
        num_map = {"1": "fast", "2": "balanced", "3": "thorough"}
        if word in num_map:
            return num_map[word]

        # Tier name directly
        if word in COMPLEXITY_ORDER:
            return word

    except Exception:
        pass

    return "balanced"
