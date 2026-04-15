# model_choice

Universal LLM model selector and caller. Pick the right model for the job, call it, and get a string back. One import.

```python
from model_choice import generate

# Let it pick the cheapest model that fits
text = generate("explain quicksort", complexity="fast")

# Auto-classify -- local model decides difficulty, then picks the tier
text = generate("architect a distributed database", complexity="auto")

# Call a specific model
text = generate("write a haiku", model="gemini-2.5-flash")

# Streaming -- iterate over chunks as they arrive
for chunk in generate("explain recursion", stream=True):
    print(chunk, end="", flush=True)

# Get parsed JSON
from model_choice import generate_json
data = generate_json("list 5 colors as JSON", complexity="fast")
```

## Why

Autonomous agents and multi-model tools need to route prompts to the right provider. You don't want to send "what's 2+2" to Claude Sonnet 4, and you don't want to send "architect a microservices system" to a local 14B model. `model_choice` handles the routing so your code just says `generate(prompt)`.

## Features

- **Tier-based model selection** -- configure providers as `fast`, `balanced`, or `thorough`. Pick the complexity level, it picks the model.
- **Auto-classification** -- set `complexity="auto"` and a local model rates the task difficulty, then selects the right tier.
- **Streaming responses** -- `generate(prompt, stream=True)` returns a generator yielding text chunks. Works with both API and CLI backends.
- **Fallback chains** -- if a provider fails, automatically tries the next one in config order. Transparent to callers.
- **Persistent cache** -- SQLite-backed LRU cache survives process restarts. Same prompt + model + params = instant cached response. 256 entries, SHA-256 keys, WAL mode. On by default.
- **Cost tracking** -- per-provider call counts, failure counts, token usage. `cost_summary()` for breakdowns, `--stats` on CLI.
- **Multiple backends** -- LiteLLM (API providers) and CLI (OAuth tools like `gemini`, `claude`).
- **Zero-config CLI** -- `model_choice "explain recursion" -c fast`
- **27 tests** covering cache, streaming, backends, and backwards compatibility.

## Install

```bash
pip install -e .
```

Dependencies: `litellm`, `pyyaml`

## Config

Config lives at `~/.config/model_choice/tiers.yaml`. Created automatically on first run. Example:

```yaml
providers:
  - provider: ollama
    model: ollama/qwen2.5-coder:14b
    label: Ollama qwen2.5-coder 14B
    backend: litellm
    auth: local
    api_base: http://localhost:11434
    complexity: fast

  - provider: zai
    model: openai/glm-5.1
    label: ZAI glm-5.1
    backend: litellm
    auth: api_key
    env_key: ZAI_API_KEY
    api_base: https://api.z.ai/api/coding/paas/v4
    complexity: balanced

  - provider: gemini
    model: gemini-2.5-flash
    label: Gemini Flash
    backend: cli
    auth: oauth
    cli_cmd: gemini
    complexity: thorough

  - provider: claude
    model: claude-sonnet-4-20250514
    label: Claude Sonnet 4
    backend: cli
    auth: oauth
    cli_cmd: claude
    complexity: thorough
```

Provider order = priority. Fast providers get tried first. Complexity levels stack: `fast` uses only fast providers, `balanced` uses fast + balanced, `thorough` uses all.

## API

```python
from model_choice import (
    generate,           # prompt -> string (or generator if stream=True)
    generate_json,      # prompt -> parsed dict/list
    pick,               # returns Provider object for a complexity level
    list_models,        # list available providers
    cost_summary,       # per-provider usage stats
    cost_totals,        # aggregate stats
    cache_stats,        # cache hit/miss rates
    clear_cache,        # reset the cache
)

# generate() parameters:
#   prompt, complexity="balanced", model=None, temperature=0.7,
#   max_tokens=2000, system=None, use_cache=True, fallback=True,
#   stream=False
```

## CLI

```bash
# Run a prompt
model_choice "explain recursion" -c fast

# Auto-classify complexity
model_choice "design a cache system" -c auto -v

# Get JSON output
model_choice "list 5 colors as JSON" -j

# List available models
model_choice --list

# Usage stats
model_choice --stats

# Skip cache / fallback
model_choice "hello" --no-cache --no-fallback

# System prompt
model_choice "review this code" -s "You are a senior engineer"
```

## Architecture

```
model_choice/
  __init__.py   334   # Public API (generate, generate_json, pick, streaming, caching)
  registry.py   183   # Provider registry -- loads config, resolves models
  backends.py   220   # LiteLLM and CLI backends, sync + streaming
  classifier.py  84   # Auto-classification via local model
  fallback.py    83   # Fallback chain logic
  cache.py      123   # SQLite-backed persistent LRU cache
  tracking.py    74   # Per-provider cost/usage tracking
  config.py      53   # Default config generation
  parsers.py     51   # Response parsing utilities
  cli.py        124   # CLI entry point
```

1329 lines, 10 modules, 27 tests, 0 dependencies beyond litellm + pyyaml.

## License

MIT
