# model_choice -- AI Agent Guide

## What This Is

A reusable Python package that picks the right LLM for the job and calls it. One config file shared across all projects. Import it, say what complexity you need, get a response.

**The problem it solves:** Every AI project on this machine was copy-pasting its own tier list, availability checks, API key loading, and backend dispatch logic. model_choice consolidates that into one place.

**Where it lives:** `~/zion/projects/model_choice/`
**Config:** `~/.config/model_choice/tiers.yaml` (auto-generated on first use)
**587 lines total** across 6 source files.

## Quick Reference

```bash
# Install (already installed, but if needed)
pip install -e ~/zion/projects/model_choice --break-system-packages

# CLI
model_choice "explain recursion" -c fast          # local model only
model_choice "design a schema" -c balanced -v     # shows which model picked
model_choice "review this arch" -c thorough        # strongest available
model_choice "list colors as JSON" -j              # parses and pretty-prints JSON
model_choice -m zai "write a test"                 # force specific provider
model_choice --list                                # show all providers + status

# Library
from model_choice import generate, generate_json, pick, list_models
text = generate("prompt", complexity="fast")
data = generate_json("prompt returning JSON", complexity="balanced")
provider = pick(complexity="thorough")  # just select, don't call
```

## Architecture

```
model_choice/           (587 lines total)
  __init__.py   135 ln  Public API: generate(), generate_json(), choose(), pick(), list_models(), refresh()
  registry.py   159 ln  Loads tiers.yaml, checks availability, selects cheapest provider
  backends.py    93 ln  Two backends: litellm (Ollama/ZAI) and CLI subprocess (Gemini/Claude)
  config.py      53 ln  Generates default tiers.yaml if missing
  parsers.py     51 ln  Robust JSON extraction from LLM output (handles markdown fences)
  cli.py         80 ln  argparse CLI, installed as `model_choice` command
  pyproject.toml 16 ln  Dependencies: litellm, pyyaml
```

## How It Works

### Selection Logic

1. On import, `__init__.py` creates a module-level `Registry` singleton
2. Registry loads `~/.config/model_choice/tiers.yaml` (auto-generates if missing)
3. On first `select()` call, runs `refresh()` which checks every provider's availability
4. Availability checks are cached for the process lifetime (call `refresh()` to force re-check)

### How Providers Are Checked

| Auth type | How it checks | What makes it "available" |
|---|---|---|
| `local` | `urllib.request.urlopen(provider.api_base/api/tags, timeout=5)` | Ollama is running on localhost:11434 |
| `api_key` | Load key from `~/.bashrc`, check `os.environ.get(env_key)` | API key exists in env |
| `oauth` | `subprocess.run(["which", cli_cmd])` | CLI tool is installed |

### How Selection Works

Providers in tiers.yaml are ordered cheapest-first. The `complexity` field on each provider sets the minimum tier required to use it.

```
complexity="fast"      -> only providers with complexity=fast       (Ollama)
complexity="balanced"  -> fast + balanced providers                 (Ollama, ZAI)
complexity="thorough"  -> all providers                              (Ollama, ZAI, Gemini, Claude)
```

The selector walks the list in order and returns the first available provider at or below the requested tier. If you pass `model="zai"` or `model="openai/glm-5.1"`, it finds that specific provider (ignoring complexity filter).

### How Backends Work

**litellm backend** (Ollama, ZAI):
- Builds `messages` list (optional system prompt + user prompt)
- Passes `api_base`, `api_key` from provider config
- Returns `resp.choices[0].message.content`

**CLI backend** (Gemini, Claude):
- Gemini: `TERM=dumb gemini -p "{prompt}" --sandbox` (TERM=dumb suppresses GPU shader warnings)
- Claude: `claude -p "{prompt}" --dangerously-skip-permissions` (non-interactive mode)
- Both: `subprocess.run()` with 120s timeout, raises RuntimeError on non-zero exit
- Temperature and max_tokens are IGNORED for CLI backends (these tools don't expose them)

**JSON mode:**
When `json_mode=True`, the `call()` dispatcher appends `"IMPORTANT: Respond with valid JSON only..."` to the prompt BEFORE routing to either backend. This ensures both litellm and CLI providers get the instruction.

### API Key Loading

Keys not in env are loaded from `~/.bashrc`. The loader:
1. Scans all providers for `auth=api_key` entries
2. Collects which `env_key` values are missing from `os.environ`
3. Reads `~/.bashrc` line by line, looking for `export VARNAME=value`
4. Strips quotes, sets in `os.environ`
5. Runs once per process (`_env_loaded` flag)

## Public API Reference

### `generate(prompt, **kwargs) -> str`

The main function. Picks a model, sends the prompt, returns raw text.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `prompt` | str | required | The text prompt |
| `model` | str or None | None | Exact model name or provider name. Overrides complexity. |
| `complexity` | str | "balanced" | "fast", "balanced", or "thorough" |
| `temperature` | float | 0.7 | Sampling temp (litellm only, ignored for CLI) |
| `max_tokens` | int | 2000 | Max response tokens (litellm only, ignored for CLI) |
| `json_mode` | bool | False | Appends JSON instruction to prompt. Returns str, not parsed. |
| `system` | str or None | None | System prompt (litellm only, ignored for CLI) |

Raises: `RuntimeError` if no model available.

### `generate_json(prompt, **kwargs) -> object`

Same as `generate()` but forces `json_mode=True` and parses the response through `parse_json_output()`. Returns a dict, list, or whatever the model output.

Raises: `RuntimeError` (no model), `ValueError` (JSON parse failed).

### `choose(prompt, **kwargs) -> str`

Alias for `generate()`. Identical behavior.

### `pick(complexity="balanced", model=None) -> Provider or None`

Select a provider without calling it. Returns the `Provider` dataclass or `None`.

### `list_models() -> list[dict]`

Returns list of dicts with keys: `provider`, `model`, `label`, `complexity`, `available`.

### `refresh()`

Force re-check all provider availability. Useful if Ollama was started mid-session.

### `parse_json_output(text: str) -> Any`

Standalone function in `model_choice.parsers`. Extracts JSON from LLM text that may contain markdown fences, explanatory text, or other noise.

Parse order: markdown code blocks -> bracket matching -> entire string. Raises `ValueError` if nothing parseable.

## CLI Reference

```
model_choice "prompt" [-c fast|balanced|thorough] [-m MODEL] [-t TEMP]
                       [--max-tokens N] [-j] [-v] [-s SYSTEM] [--list]
```

| Flag | Short | Default | What it does |
|---|---|---|---|
| prompt | (positional) | required | The prompt to send (not needed with --list) |
| `--complexity` | `-c` | balanced | Selection tier |
| `--model` | `-m` | auto | Force specific model or provider |
| `--temperature` | `-t` | 0.7 | Sampling temperature |
| `--max-tokens` | | 2000 | Max response tokens |
| `--json` | `-j` | off | Parse response as JSON, pretty-print |
| `--verbose` | `-v` | off | Print selected model to stderr |
| `--system` | `-s` | | System prompt |
| `--list` | | off | List all providers and exit |

## The Config File

Location: `~/.config/model_choice/tiers.yaml`

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

**Provider fields:**

| Field | Required | Used by | What it does |
|---|---|---|---|
| `provider` | all | selection | Short name, used with `pick(model="zai")` |
| `model` | all | litellm + selection | Full model identifier for litellm or display |
| `label` | all | display | Human-readable name |
| `backend` | all | dispatch | "litellm" or "cli" |
| `auth` | all | availability | "local", "api_key", or "oauth" |
| `complexity` | all | selection | "fast", "balanced", or "thorough" |
| `api_base` | litellm | litellm calls | API endpoint URL |
| `env_key` | api_key | key loading | Environment variable name for API key |
| `cli_cmd` | cli | CLI dispatch | Command name (gemini, claude) |

**To add a provider:** append a new entry to the YAML. Order matters -- cheapest first.

**To add a second model to the same provider** (e.g., another Ollama model): add a second entry with the same `provider` name but different `model`. The selector treats them as separate providers and picks the first available.

## How to Use This From Other Projects

### Replace project-specific tier configs

If a project has its own provider/escalation code, replace it:

```python
# BEFORE: project-specific tier definitions
TIERS = [
    {"provider": "ollama", "model": "ollama/qwen2.5-coder:14b", ...},
    {"provider": "zai", "model": "openai/glm-5.1", ...},
]
# ... 100 lines of availability checks, dispatch, key loading

# AFTER: one import
from model_choice import generate, generate_json, pick
result = generate("prompt", complexity="balanced")
```

### Wrap for backward compatibility

If existing code uses a `LLMClient` class, make it a thin shim:

```python
from model_choice import generate as _generate
from model_choice.parsers import parse_json_output

class LLMClient:
    def __init__(self, model: str, temperature: float = 0.9):
        self.model = model
        self.temperature = temperature

    def generate(self, prompt: str) -> str:
        return _generate(prompt, model=self.model, temperature=self.temperature, max_tokens=3000)

    def generate_json(self, prompt: str) -> list[dict]:
        raw = self.generate(prompt)
        result = parse_json_output(raw)
        if isinstance(result, list):
            return result
        return [result]
```

## Gotchas

- **ZAI uses reasoning tokens.** The glm-5.1 model via ZAI allocates tokens to internal reasoning. With low `max_tokens` (under ~100), all tokens go to reasoning and you get an empty string response. Use `max_tokens=500+` for ZAI.
- **Temperature and max_tokens are ignored for CLI backends.** Gemini and Claude CLI tools don't expose these parameters. The values are accepted but have no effect.
- **CLI timeout is 120 seconds.** Both Gemini and Claude have a hardcoded 120s subprocess timeout. Long prompts with large responses may hit this. If you need longer, call the CLI tools directly instead of through model_choice.
- **Availability is cached per process.** If Ollama isn't running when you import model_choice, it'll be marked unavailable for the rest of the process. Call `model_choice.refresh()` to force a re-check.
- **API keys loaded from ~/.bashrc.** If keys are in a different file or set dynamically, they need to be in `os.environ` before the first `generate()` call. The loader only reads `~/.bashrc`.
- **OAuth CLIs need prior interactive login.** `gemini` and `claude` must be logged in interactively before they work in `-p` mode. If not authed, they'll error. model_choice only checks if the binary exists (`which`), not if the auth session is valid.
- **`generate()` with `json_mode=True` returns a string, not parsed JSON.** Use `generate_json()` if you want the parsed object. `json_mode` just appends the instruction to the prompt; it doesn't change the return type.
- **`parse_json_output` raises ValueError, not returns empty.** Unlike the original `parse_json_response` in possibilities/llm.py (which returns `[]` on failure), this raises. This is intentional -- silent empty returns mask errors. Wrap in try/except if you need fallback behavior.

## Project Layout

```
~/zion/projects/model_choice/
  model_choice/
    __init__.py      # Public API + module-level Registry singleton
    registry.py      # Provider dataclass, Registry class (load/check/select)
    backends.py      # call_litellm(), call_cli(), unified call()
    config.py        # DEFAULT_YAML string, generate_default_config()
    parsers.py       # parse_json_output() -- robust JSON from LLM text
    cli.py           # argparse CLI, entry point: model_choice.cli:main
  pyproject.toml     # deps: litellm, pyyaml
  AI_GUIDE.md        # This file
```

## Dependencies

- **litellm** -- unified API for calling Ollama and ZAI
- **pyyaml** -- parsing tiers.yaml config

Both are listed in pyproject.toml and installed automatically with `pip install -e`.
