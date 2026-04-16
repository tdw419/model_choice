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

# Templates -- constrain providers for different consumers
text = generate("build a function", template="ai_daemon")  # ollama only

# Module-level defaults
from model_choice import configure
configure(template="ai_daemon")  # all future calls use ollama

# Get parsed JSON
from model_choice import generate_json
data = generate_json("list 5 colors as JSON", complexity="fast")
```

## Why

Autonomous agents and multi-model tools need to route prompts to the right provider. You don't want to send "what's 2+2" to Claude Sonnet 4, and you don't want to send "architect a microservices system" to a local 14B model. `model_choice` handles the routing so your code just says `generate(prompt)`.

## Features

- **Tier-based model selection** -- configure providers as `fast`, `balanced`, or `thorough`. Pick the complexity level, it picks the model.
- **Templates** -- named presets that constrain which providers a consumer can use. `ai_daemon` stays on ollama, `agent` defaults to zai. Per-call, module-level, or env var.
- **Auto-classification** -- set `complexity="auto"` and a local model rates the task difficulty, then selects the right tier.
- **Streaming responses** -- `generate(prompt, stream=True)` returns a generator yielding text chunks. Works with both API and CLI backends.
- **Fallback chains** -- if a provider fails, automatically tries the next one in config order. Transparent to callers.
- **Persistent cache** -- SQLite-backed LRU cache survives process restarts. Same prompt + model + params = instant cached response. 256 entries, SHA-256 keys, WAL mode. On by default.
- **Cost tracking** -- per-provider call counts, failure counts, token usage. `cost_summary()` for breakdowns, `--stats` on CLI.
- **Multiple backends** -- LiteLLM (API providers) and CLI (OAuth tools like `gemini`, `claude`).
- **Zero-config CLI** -- `model_choice "explain recursion" -c fast`
- **43 tests** covering cache, streaming, backends, templates, and backwards compatibility.

## Install

```bash
pip install -e .
```

Dependencies: `litellm`, `pyyaml`

## Templates

Templates constrain which providers a consumer can use and set default parameters. Three ways to activate:

```python
# 1. Per-call
text = generate("prompt", template="ai_daemon")

# 2. Module-level (all future calls)
configure(template="ai_daemon")

# 3. Environment variable
# MODEL_CHOICE_TEMPLATE=ai_daemon
```

Built-in templates:

| Name | Providers | Default | Notes |
|------|-----------|---------|-------|
| `default` | all | balanced | No filtering |
| `ai_daemon` | ollama | fast, no fallback | Local-only autonomous builder |
| `agent` | zai, ollama, gemini, claude | balanced | General agent with cloud priority |
| `ollama_only` | ollama | fast | Force local |
| `cloud_only` | zai, gemini, claude | balanced | Skip local |
| `cheap` | ollama, zai | fast | Budget mode |
| `thorough` | all | thorough | Use strongest available |

Add custom templates in `~/.config/model_choice/tiers.yaml`:

```yaml
templates:
  - name: my_template
    providers:
      - zai
      - gemini
    default_complexity: balanced
    default_temperature: 0.5
    fallback: true
```

CLI: `model_choice --templates` to list, `-T ai_daemon` to use.

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
    configure,          # set module-level defaults (template, complexity, etc.)
    list_templates,     # list all available templates
)

# generate() parameters:
#   prompt, complexity="balanced", model=None, temperature=0.7,
#   max_tokens=2000, system=None, use_cache=True, fallback=True,
#   stream=False, template=None
```

## CLI

```bash
# Run a prompt
model_choice "explain recursion" -c fast

# Auto-classify complexity
model_choice "design a cache system" -c auto -v

# Use a template
model_choice "build a function" -T ai_daemon -v

# Get JSON output
model_choice "list 5 colors as JSON" -j

# List available models
model_choice --list

# List templates
model_choice --templates

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
  __init__.py   416   # Public API (generate, generate_json, pick, streaming, caching, templates)
  registry.py   232   # Provider registry -- loads config, resolves models, template-aware selection
  backends.py   220   # LiteLLM and CLI backends, sync + streaming
  templates.py  108   # Named presets -- provider filtering, defaults, env var resolution
  classifier.py  84   # Auto-classification via local model
  fallback.py    83   # Fallback chain logic
  cache.py      123   # SQLite-backed persistent LRU cache
  tracking.py    74   # Per-provider cost/usage tracking
  config.py      73   # Default config generation
  parsers.py     51   # Response parsing utilities
  cli.py        143   # CLI entry point
```

1607 lines, 11 modules, 43 tests, 0 dependencies beyond litellm + pyyaml.

## License

MIT
