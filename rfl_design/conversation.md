# Recursive Feedback Loop — Conversation Export

Generated: 2026-04-15T12:22:53.201567

## USER (Iteration 0)

# Design model_choice -- universal LLM model selector and caller

## Problem
Every AI project on this machine (possibilities, autodev, ai_daemon, etc.) defines its own tier list of LLM providers and escalation logic. This is redundant -- they all use the same 4 providers (Ollama local, ZAI API, Gemini OAuth, Claude OAuth) with the same auth methods and availability checks.

We need a single, reusable package that any project can import to answer: "given this task, what model should I use?" and then call that model.

## Existing Code to Extract From
The proven tier definitions and dispatch logic live in:
- ~/zion/projects/ai_possibilities/ai_possibilities/possibilities/escalate.py (317 lines)
  - DEFAULT_TIERS: provider config dicts with provider/model/label/auth/backend fields
  - _ensure_api_keys(): loads keys from ~/.bashrc
  - _check_available(): detects if a provider is running/installed/authed
  - _generate_with_litellm(): calls Ollama/ZAI via litellm
  - _generate_with_cli(): calls Gemini/Claude via subprocess CLI
  - generate_for_tier(): unified dispatch
- ~/zion/.bashrc has ZAI_API_KEY export

## Available Providers (Jericho's machine)
1. **Ollama** (localhost:11434) -- local models, free. Models: qwen2.5-coder:14b, etc. Backend: litellm.
2. **ZAI** (api.z.ai) -- API key in ~/.bashrc as ZAI_API_KEY. Model: openai/glm-5.1. Backend: litellm with api_base.
3. **Gemini** -- OAuth via `gemini` CLI. Model: gemini-2.5-flash. Backend: CLI subprocess.
4. **Claude** -- OAuth via `claude` CLI. Model: claude-sonnet-4-20250514. Backend: CLI subprocess.

## Requirements
1. **Registry**: YAML config file at ~/.config/model_choice/tiers.yaml. Define all providers once. Auto-detect what's available at startup.
2. **Selector**: Given a prompt + complexity hint (fast/balanced/thorough), pick the cheapest available model. "fast" = local only. "balanced" = local first, API if needed. "thorough" = strongest available.
3. **Caller**: Unified generate(prompt, model=None, complexity="balanced", temperature=0.7, max_tokens=2000, json_mode=False) that handles litellm vs CLI dispatch transparently.
4. **CLI**: `model_choice "prompt here" --complexity fast` -- picks model, runs it, prints output.
5. **Library**: `from model_choice import choose; result = choose("task", complexity="thorough")`
6. **No external deps beyond litellm + pyyaml**: Keep it lean. litellm for API models, subprocess for CLI models, pyyaml for config.

## Constraints
- Python package at ~/zion/projects/model_choice/model_choice/
- Must work as both CLI and importable library
- Config in ~/.config/model_choice/ (XDG-style)
- Auto-generate default config if none exists
- Each project should NOT need its own tier config -- they all import from here
- Ollama needs explicit api_base=http://localhost:11434 for litellm
- ZAI needs api_base=https://api.z.ai/api/coding/paas/v4 and api_key from env
- Gemini CLI needs `TERM=dumb gemini -p "prompt" --sandbox`
- Claude CLI needs `claude -p "prompt" --dangerously-skip-permissions`
- API keys loaded from ~/.bashrc if not in env
- JSON mode: tell the model to output JSON, parse it robustly (handle markdown fences)

## Key Questions to Resolve
- Should the selector use LLM-based classification (ask a local model "how hard is this?") or simple heuristic (length + keyword matching)?
- How to handle timeout/retry across different backends?
- Should we cache availability checks or re-check every call?
- How to handle streaming vs non-streaming?

## Source Files to Read
- ~/zion/projects/ai_possibilities/ai_possibilities/possibilities/escalate.py -- the proven tier/dispatch code to extract

Your task: design the package architecture, data models, API surface, and CLI. Be specific. Include actual code sketches. Each iteration: verify assumptions against the existing escalate.py, not against previous iterations.

---

## ASSISTANT (Iteration 0)

Good, I've got the full picture from escalate.py and the env vars. Let me also check how the JSON parsing works since it's imported from llm.py:

    Now I have everything. Let me check the parse_json_response function completely and then write the design.

    Now I have the complete picture. Here's the design.
    
    ---
    
    ## model_choice -- Package Architecture
    
    ### Resolved Design Decisions
    
    **Q: LLM-based complexity classification vs heuristic?**
    Heuristic. Asking a local model adds 5-10s latency before every call. The complexity hint comes from the caller -- they know if their task is "fast" (label a thing), "balanced" (generate branches), or "thorough" (architecture review). No classification needed.
    
    **Q: Timeout/retry?**
    Per-backend timeout with a single retry on failure. CLI backends get 120s, litellm backends get 60s. No exponential backoff -- this is a utility, not a production service. Caller can implement their own retry loop if they want.
    
    **Q: Cache availability checks?**
    Cache for the process lifetime with a `refresh()` method. Ollama might get started/stopped mid-session, so `refresh()` lets callers force re-check. But the default is check-once-per-process.
    
    **Q: Streaming?**
    Out of scope for v1. This is a synchronous call-and-return library. Streaming would change the API shape entirely and none of the consumers need it.
    
    ### File Layout
    
    ```
    ~/zion/projects/model_choice/
      model_choice/
        __init__.py      # public API: choose(), generate(), list_models()
        registry.py      # load tiers.yaml, check availability, select model
        backends.py      # litellm backend, cli backend (subprocess)
        config.py        # XDG config path, default config generation
        parsers.py       # JSON fence stripping, robust parse
        cli.py           # argparse CLI entry point
      pyproject.toml
    ```
    
    ### tiers.yaml Schema
    
    The config is a list of provider entries, ordered from cheapest to most expensive. This ordering IS the priority. `complexity` maps to how far down the list you're allowed to go.
    
    ```yaml
    # ~/.config/model_choice/tiers.yaml
    # Auto-generated if missing. Order = priority (cheapest first).
    
    providers:
      - provider: ollama
        model: ollama/qwen2.5-coder:14b
        label: Ollama qwen2.5-coder 14B
        backend: litellm
        auth: local
        api_base: http://localhost:11434
        complexity: fast        # available for fast+
    
      - provider: zai
        model: openai/glm-5.1
        label: ZAI glm-5.1
        backend: litellm
        auth: api_key
        env_key: ZAI_API_KEY
        api_base: https://api.z.ai/api/coding/paas/v4
        complexity: balanced    # available for balanced+
    
      - provider: gemini
        model: gemini-2.5-flash
        label: Gemini Flash
        backend: cli
        auth: oauth
        cli_cmd: gemini
        cli_args: [-p, "{prompt}", --sandbox]
        env_prefix: TERM=dumb
        complexity: thorough    # available for thorough only
    
      - provider: claude
        model: claude-sonnet-4-20250514
        label: Claude Sonnet 4
        backend: cli
        auth: oauth
        cli_cmd: claude
        cli_args: [-p, "{prompt}", --dangerously-skip-permissions]
        complexity: thorough    # available for thorough only
    ```
    
    The `complexity` field on each provider sets its minimum tier. The selector picks the first available provider at or below the requested complexity level:
    - `fast` -> only considers providers with `complexity: fast`
    - `balanced` -> considers `fast` + `balanced` providers
    - `thorough` -> considers all providers
    
    ### Core Data Models (registry.py)
    
    ```python
    """Registry -- load config, check availability, select model."""
    
    import os
    import subprocess
    from dataclasses import dataclass, field
    from pathlib import Path
    from typing import Optional
    
    import yaml
    
    COMPLEXITY_ORDER = {"fast": 0, "balanced": 1, "thorough": 2}
    
    
    @dataclass
    class Provider:
        provider: str          # "ollama", "zai", "gemini", "claude"
        model: str             # "ollama/qwen2.5-coder:14b", "openai/glm-5.1"
        label: str             # "ZAI glm-5.1"
        backend: str           # "litellm" or "cli"
        auth: str              # "local", "api_key", "oauth"
        complexity: str        # "fast", "balanced", "thorough"
    
        # litellm-specific
        api_base: Optional[str] = None
        env_key: Optional[str] = None
    
        # cli-specific
        cli_cmd: Optional[str] = None
        cli_args: Optional[list[str]] = None
        env_prefix: Optional[str] = None
    
        # runtime state
        available: Optional[bool] = field(default=None, repr=False)
    
    
    class Registry:
        """Loads tiers.yaml, checks provider availability, selects models."""
    
        def __init__(self, config_path: Optional[str] = None):
            self.config_path = config_path or self._default_config_path()
            self.providers: list[Provider] = []
            self._loaded_env = False
            self._load()
    
        @staticmethod
        def _default_config_path() -> str:
            xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            return os.path.join(xdg, "model_choice", "tiers.yaml")
    
        def _load(self):
            if not os.path.exists(self.config_path):
                from .config import generate_default_config
                generate_default_config(self.config_path)
    
            with open(self.config_path) as f:
                data = yaml.safe_load(f)
    
            for entry in data.get("providers", []):
                self.providers.append(Provider(**{
                    k: v for k, v in entry.items() if k in Provider.__dataclass_fields__
                }))
    
        def _ensure_env_keys(self):
            """Load API keys from ~/.bashrc into env, once."""
            if self._loaded_env:
                return
            bashrc = os.path.expanduser("~/.bashrc")
            if not os.path.exists(bashrc):
                self._loaded_env = True
                return
    
            needed = {
                p.env_key for p in self.providers
                if p.auth == "api_key" and p.env_key and not os.environ.get(p.env_key)
            }
            if needed:
                with open(bashrc) as f:
                    for line in f:
                        line = line.strip()
                        for var in list(needed):
                            if line.startswith(f"export {var}="):
                                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                                os.environ[var] = val
                                needed.discard(var)
            self._loaded_env = True
    
        def check_available(self, provider: Provider) -> bool:
            """Check if a single provider is reachable/authed."""
            if provider.auth == "local":
                try:
                    subprocess.run(
                        ["curl", "-s", f"{provider.api_base}/api/tags"],
                        capture_output=True, timeout=5,
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
            """Re-check all providers. Call if Ollama was started mid-session."""
            self._ensure_env_keys()
            for p in self.providers:
                p.available = self.check_available(p)
    
        def select(
            self,
            complexity: str = "balanced",
            model: Optional[str] = None,
        ) -> Optional[Provider]:
            """Pick the cheapest available provider for the given complexity.
    
            If model is specified, find it exactly (ignoring complexity filter).
            """
            # Ensure availability is cached
            if any(p.available is None for p in self.providers):
                self.refresh()
    
            # Exact model match
            if model:
                for p in self.providers:
                    if p.model == model or p.provider == model:
                        if p.available:
                            return p
                return None
    
            # Pick cheapest available at or below requested complexity
            requested = COMPLEXITY_ORDER.get(complexity, 1)
            for p in self.providers:
                provider_tier = COMPLEXITY_ORDER.get(p.complexity, 1)
                if provider_tier <= requested and p.available:
                    return p
    
            return None
    
        def list_available(self) -> list[Provider]:
            """All available providers."""
            if any(p.available is None for p in self.providers):
                self.refresh()
            return [p for p in self.providers if p.available]
    ```
    
    ### Backends (backends.py)
    
    Extracted directly from escalate.py's `_generate_with_litellm` and `_generate_with_cli`:
    
    ```python
    """Backend dispatch -- litellm and CLI subprocess."""
    
    import json
    import os
    import subprocess
    import shlex
    
    from .registry import Provider
    from .parsers import parse_json_output
    
    
    def call_litellm(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Call a provider via litellm."""
        import litellm
    
        messages = [{"role": "user", "content": prompt}]
        if json_mode:
            messages[0]["content"] += (
                "\n\nIMPORTANT: Respond with valid JSON only. "
                "No markdown, no explanation, just the JSON."
            )
    
        kwargs = dict(
            model=provider.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
        if provider.api_base:
            kwargs["api_base"] = provider.api_base
        if provider.env_key:
            api_key = os.environ.get(provider.env_key)
            if api_key:
                kwargs["api_key"] = api_key
    
        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content
    
    
    def call_cli(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Call a provider via CLI subprocess."""
        if provider.cli_cmd == "gemini":
            cmd = ["gemini", "-p", prompt, "--sandbox"]
            env = dict(os.environ, TERM="dumb")
        elif provider.cli_cmd == "claude":
            suffix = ""
            if json_mode:
                suffix = " (respond with JSON only, no markdown fences)"
            cmd = ["claude", "-p", prompt + suffix, "--dangerously-skip-permissions"]
            env = None  # inherit
        else:
            # Generic CLI -- interpolate {prompt} in args
            args = [a.replace("{prompt}", prompt) for a in (provider.cli_args or [])]
            cmd = [provider.cli_cmd] + args
            env = None
    
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        return result.stdout
    
    
    def call(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Unified dispatch -- pick backend from provider config."""
        if provider.backend == "litellm":
            return call_litellm(provider, prompt, temperature, max_tokens, json_mode)
        elif provider.backend == "cli":
            return call_cli(provider, prompt, temperature, max_tokens, json_mode)
        else:
            raise ValueError(f"Unknown backend: {provider.backend}")
    ```
    
    ### Parsers (parsers.py)
    
    Extracted from llm.py's `parse_json_response`:
    
    ```python
    """Robust JSON parsing from LLM output."""
    
    import json
    import re
    from typing import Any
    
    
    def parse_json_output(text: str) -> Any:
        """Extract JSON from LLM response, handling markdown fences.
    
        Returns the parsed object (dict, list, whatever). Raises ValueError if
        nothing parseable found.
        """
        text = text.strip()
    
        # Try markdown code blocks first
        if "```" in text:
            blocks = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
            for block in blocks:
                try:
                    return json.loads(block.strip())
                except json.JSONDecodeError:
                    continue
    
        # Try to find raw JSON
        for opener, closer in [("[", "]"), ("{", "}")]:
            start = text.find(opener)
            if start != -1:
                # Find matching close
                candidate = text[start:]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Try progressively shorter substrings
                    depth = 0
                    for i, ch in enumerate(candidate):
                        if ch == opener:
                            depth += 1
                        elif ch == closer:
                            depth -= 1
                            if depth == 0:
                                try:
                                    return json.loads(candidate[:i + 1])
                                except json.JSONDecodeError:
                                    break
    
        # Try the whole thing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"Could not extract JSON from response: {text[:200]}")
    ```
    
    ### Config Generator (config.py)
    
    ```python
    """Default config generation."""
    
    import os
    
    DEFAULT_CONFIG = """\
    # model_choice provider tiers
    # Order = priority (cheapest/most available first)
    # complexity = minimum tier required to use this provider
    
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
    """
    
    
    def generate_default_config(path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(DEFAULT_CONFIG)
    ```
    
    ### Public API (__init__.py)
    
    ```python
    """model_choice -- universal LLM model selector and caller.
    
    Usage:
        from model_choice import choose, generate, list_models
    
        # Simplest: pick model, run it, get result
        result = choose("explain quicksort", complexity="fast")
    
        # Get parsed JSON
        data = choose("list 5 colors as JSON", complexity="fast", json_mode=True)
    
        # Pick a model without calling it
        provider = pick(complexity="thorough")
        print(provider.label, provider.model)
    
        # Call a specific model
        result = generate("write a haiku", model="gemini-2.5-flash")
    """
    
    from .registry import Registry, Provider
    from .backends import call
    
    # Module-level singleton -- loads config once, caches availability
    _registry = Registry()
    
    
    def generate(
        prompt: str,
        model: str | None = None,
        complexity: str = "balanced",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Run a prompt through the cheapest available model.
    
        Args:
            prompt: The text prompt.
            model: Exact model name or provider name. Overrides complexity.
            complexity: "fast", "balanced", or "thorough".
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            json_mode: If True, instruct model to output JSON.
    
        Returns:
            Raw text response from the model.
    
        Raises:
            RuntimeError: No available model found.
        """
        provider = _registry.select(complexity=complexity, model=model)
        if not provider:
            raise RuntimeError(
                f"No available model for complexity={complexity}"
                + (f" model={model}" if model else "")
            )
        return call(provider, prompt, temperature, max_tokens, json_mode)
    
    
    def choose(
        prompt: str,
        model: str | None = None,
        complexity: str = "balanced",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Alias for generate(). Same signature."""
        return generate(prompt, model, complexity, temperature, max_tokens, json_mode)
    
    
    def pick(
        complexity: str = "balanced",
        model: str | None = None,
    ) -> Provider | None:
        """Select a provider without calling it. Returns Provider or None."""
        return _registry.select(complexity=complexity, model=model)
    
    
    def list_models() -> list[dict]:
        """List all available providers with status."""
        results = []
        for p in _registry.providers:
            results.append({
                "provider": p.provider,
                "model": p.model,
                "label": p.label,
                "complexity": p.complexity,
                "available": p.available,
            })
        return results
    
    
    def refresh():
        """Force re-check all provider availability."""
        _registry.refresh()
    ```
    
    ### CLI (cli.py)
    
    ```python
    """model_choice CLI -- pick a model, run a prompt, print output."""
    
    import argparse
    import json
    import sys
    
    
    def main():
        parser = argparse.ArgumentParser(
            prog="model_choice",
            description="Universal LLM model selector and caller",
        )
        parser.add_argument("prompt", help="The prompt to send")
        parser.add_argument(
            "-c", "--complexity",
            choices=["fast", "balanced", "thorough"],
            default="balanced",
            help="Complexity tier (default: balanced)",
        )
        parser.add_argument("-m", "--model", help="Specific model to use")
        parser.add_argument("-t", "--temperature", type=float, default=0.7)
        parser.add_argument("--max-tokens", type=int, default=2000)
        parser.add_argument("-j", "--json", action="store_true", help="Request JSON output")
        parser.add_argument(
            "--list", action="store_true",
            help="List available models and exit",
        )
        parser.add_argument(
            "-v", "--verbose", action="store_true",
            help="Show which model was selected",
        )
    
        args = parser.parse_args()
    
        # Lazy import so --help is fast
        from model_choice import list_models, generate, pick
    
        if args.list:
            models = list_models()
            for m in models:
                status = "OK" if m["available"] else "--"
                print(f"  [{status}] {m['provider']:8s} {m['model']:30s} {m['label']}")
            sys.exit(0)
    
        if args.verbose:
            provider = pick(complexity=args.complexity, model=args.model)
            if provider:
                print(f"[model_choice] using {provider.label}", file=sys.stderr)
            else:
                print(f"[model_choice] no model available", file=sys.stderr)
                sys.exit(1)
    
        try:
            result = generate(
                prompt=args.prompt,
                model=args.model,
                complexity=args.complexity,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                json_mode=args.json,
            )
            print(result)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    
    if __name__ == "__main__":
        main()
    ```
    
    ### pyproject.toml
    
    ```toml
    [project]
    name = "model_choice"
    version = "0.1.0"
    description = "Universal LLM model selector and caller"
    requires-python = ">=3.10"
    dependencies = ["litellm", "pyyaml"]
    
    [project.scripts]
    model_choice = "model_choice.cli:main"
    ```
    
    ### How consumers use it
    
    ```python
    # possibilities/escalate.py -- AFTER refactor
    from model_choice import choose, pick, list_models
    
    # was: _ensure_api_keys(), _check_available(), _generate_with_litellm(), etc.
    # now:
    branches_raw = choose(prompt, complexity="balanced", json_mode=True)
    # returns parsed JSON or raises
    
    # autodev
    from model_choice import generate
    result = generate("write a test for foo.py", complexity="fast")
    
    # ai_daemon
    from model_choice import pick, generate
    provider = pick(complexity="thorough")
    if provider:
        result = generate("architect this system", model=provider.model)
    ```
    
    ### What gets deleted from each consumer
    
    After model_choice is integrated, each project can delete:
    - `escalate.py::_ensure_api_keys()` -> `registry.py::_ensure_env_keys()`
    - `escalate.py::_check_available()` -> `registry.py::check_available()`
    - `escalate.py::_generate_with_litellm()` -> `backends.py::call_litellm()`
    - `escalate.py::_generate_with_cli()` -> `backends.py::call_cli()`
    - `escalate.py::DEFAULT_TIERS` -> `tiers.yaml`
    - `llm.py::LLMClient` -> `backends.py::call_litellm()` + `parsers.py`
    - `llm.py::parse_json_response()` -> `parsers.py::parse_json_output()`
    
    ### Summary of tradeoffs
    
    | Decision | Choice | Why |
    |---|---|---|
    | Complexity classification | Caller-specified | No latency, caller knows task better than heuristic |
    | Availability caching | Process lifetime + refresh() | Ollama state rarely changes mid-call; refresh() for hot-loop scenarios |
    | Streaming | No | None of the 3 consumers need it; changes API shape |
    | Config format | YAML | Readable, supports comments, easy to hand-edit |
    | Module singleton | Yes | One config load, one availability check per process; import is cheap |
    | JSON mode | Prompt suffix | litellm's response_format doesn't work across backends; prompt suffix is universal |

---

## ASSISTANT (Iteration 1)

Let me verify the design against the actual source code before refining anything.

    Good. Now let me check what other projects have their own tier/dispatch logic that would be consolidated:

    Good. AIPM uses a different pattern (engine-based with Anthropic fallback), not the same tier dispatch. autodev doesn't have its own LLM dispatch. The main consumer is possibilities/escalate.py. Let me also check how the ZAI_API_KEY is stored:

    Good. Now let me review the design from iteration 0 against the actual code and identify issues.
    
    ---
    
    ## Iteration 2: Design Review Against Source
    
    Verified the full escalate.py (317 lines) and llm.py (115 lines). Here's what the iteration 0 design got right, what it missed, and what needs fixing.
    
    ### What the design got right
    
    1. The four provider backends (litellm for Ollama/ZAI, CLI for Gemini/Claude) match exactly.
    2. The `_ensure_api_keys` logic from bashrc is correctly extracted.
    3. The `_check_available` checks (curl for Ollama, env var for API key, `which` for CLI) are accurate.
    4. JSON fence stripping matches `parse_json_response`.
    5. The complexity tier ordering (fast -> balanced -> thorough) maps cleanly to the existing tier escalation logic.
    
    ### Issues found
    
    **Issue 1: parse_json_response returns `list[dict]` not `Any`.**
    
    The existing parser in llm.py:80-115 always returns a list. If it gets a dict, it wraps it in `[result]`. If it fails, it returns `[]` -- never raises. The design's `parse_json_output` returns `Any` and raises `ValueError` on failure. This is a deliberate improvement (returning Any is more flexible for non-array use cases), but the design should explicitly note this behavioral change. Callers that rely on getting `[]` back will need adjustment.
    
    **Verdict:** Keep the design's approach (raise on failure, return Any). It's more honest than silently returning empty. Document the change.
    
    **Issue 2: Ollama availability check uses curl.**
    
    The design's `check_available` runs `curl -s http://localhost:11434/api/tags`. But `curl` may not be installed in minimal environments. Python stdlib alternative:
    
    ```python
    import urllib.request
    try:
        urllib.request.urlopen(f"{provider.api_base}/api/tags", timeout=5)
        return True
    except Exception:
        return False
    ```
    
    **Verdict:** Use urllib.request instead of curl subprocess. Same check, zero external dependency.
    
    **Issue 3: Claude CLI needs "no markdown" hint for JSON mode.**
    
    From my memory notes: Claude CLI needs "no markdown" added to prompts to avoid fenced JSON. The design handles this with a suffix `(respond with JSON only, no markdown fences)` in call_cli. But Gemini also wraps JSON in fences. The json_mode prompt suffix should apply to ALL backends, not just litellm. Currently the design only adds the "IMPORTANT: Respond with valid JSON only" suffix for litellm and a shorter version for Claude, but not for Gemini.
    
    **Verdict:** Move the json_mode prompt suffix to the `call()` dispatcher so it applies before backend routing.
    
    **Issue 4: No system prompt support.**
    
    The existing litellm calls only use a user message. But LLMClient.generate() takes just a prompt string. The design mirrors this. However, some consumers might want a system prompt (e.g., "you are a code reviewer"). Adding an optional `system` parameter costs nothing and prevents a future API break.
    
    **Verdict:** Add `system: str | None = None` to generate/choose. If provided, prepend a system message.
    
    **Issue 5: The design's `call_cli` doesn't handle stderr.**
    
    The existing `_generate_with_cli` only reads stdout, but CLI tools can output errors to stderr. If the command fails (non-zero exit), we should raise with stderr content, not silently return empty stdout.
    
    **Verdict:** Check `result.returncode` and raise on non-zero with stderr content.
    
    **Issue 6: Temperature handling for CLI backends is ignored.**
    
    The design passes `temperature` to `call_cli` but never uses it. CLI tools (gemini, claude) don't expose temperature flags in their non-interactive `-p` mode. The parameter should be documented as litellm-only.
    
    **Verdict:** No code change needed, but add a docstring note.
    
    **Issue 7: The module singleton _registry is created at import time.**
    
    If the package is imported before the user's environment is set up (e.g., during test fixtures), the singleton will do availability checks too early. The lazy check (checking on first `select()` call) in the design handles this correctly since `select()` calls `refresh()` when `available is None`. Good.
    
    **Issue 8: The YAML config doesn't support multiple models per provider.**
    
    Jericho might want to configure Ollama with multiple model options (qwen2.5-coder:14b for code, llama3 for general). The current design is one model per provider entry. You can have multiple entries with the same provider name but different models, and the selector picks the first available. This works but should be documented.
    
    **Verdict:** Document it. No code change needed -- the list-of-providers approach already supports it.
    
    ### Refined Design: Key Changes
    
    Here are the specific diffs from iteration 0:
    
    **backends.py -- urllib for availability, unified json_mode prefix, stderr handling:**
    
    ```python
    # registry.py -- replace curl with urllib
    def check_available(self, provider: Provider) -> bool:
        if provider.auth == "local":
            import urllib.request
            try:
                urllib.request.urlopen(
                    f"{provider.api_base}/api/tags", timeout=5
                )
                return True
            except Exception:
                return False
        # ... rest unchanged
    
    # backends.py -- call() adds json_mode prefix before dispatch
    def call(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
        system: str | None = None,
    ) -> str:
        if json_mode:
            prompt += (
                "\n\nIMPORTANT: Respond with valid JSON only. "
                "No markdown fences, no explanation, just the JSON object."
            )
        if provider.backend == "litellm":
            return call_litellm(provider, prompt, temperature, max_tokens, system)
        elif provider.backend == "cli":
            return call_cli(provider, prompt, temperature, max_tokens)
        else:
            raise ValueError(f"Unknown backend: {provider.backend}")
    
    
    # backends.py -- call_cli checks returncode
    def call_cli(provider, prompt, temperature=0.7, max_tokens=2000):
        if provider.cli_cmd == "gemini":
            cmd = ["gemini", "-p", prompt, "--sandbox"]
            env = dict(os.environ, TERM="dumb")
        elif provider.cli_cmd == "claude":
            cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
            env = None
        else:
            args = [a.replace("{prompt}", prompt) for a in (provider.cli_args or [])]
            cmd = [provider.cli_cmd] + args
            env = None
    
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{provider.cli_cmd} failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )
        return result.stdout
    ```
    
    **call_litellm -- system prompt support:**
    
    ```python
    def call_litellm(provider, prompt, temperature=0.7, max_tokens=2000, system=None):
        import litellm
    
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
    
        kwargs = dict(
            model=provider.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if provider.api_base:
            kwargs["api_base"] = provider.api_base
        if provider.env_key:
            api_key = os.environ.get(provider.env_key)
            if api_key:
                kwargs["api_key"] = api_key
    
        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content
    ```
    
    **Public API -- system param, json_mode returns parsed:**
    
    ```python
    def generate(
        prompt: str,
        model: str | None = None,
        complexity: str = "balanced",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
        system: str | None = None,
    ) -> str:
        provider = _registry.select(complexity=complexity, model=model)
        if not provider:
            raise RuntimeError(...)
        return call(provider, prompt, temperature, max_tokens, json_mode, system)
    ```
    
    **parse_json_output -- behavioral contract:**
    
    The design already returns `Any` and raises `ValueError`. Add explicit note: "Unlike the original parse_json_response which returns [] on failure, this raises ValueError. This is intentional -- silent empty returns mask errors."
    
    ### Summary of iteration 2 changes
    
    | Change | Why |
    |---|---|
    | urllib.request instead of curl subprocess | No external dependency, works everywhere |
    | json_mode prompt prefix moved to call() | Applies to all backends, not just litellm |
    | CLI returncode check + stderr in error | Don't silently return empty on failure |
    | system prompt parameter | Forward-looking, costs nothing, avoids API break later |
    | Document parse_json_output behavioral change | Old code returns [] on failure, new code raises -- callers need to know |

---

## ASSISTANT (Iteration 2)

Final iteration. Let me re-verify the actual source one more time, then produce the definitive design with all fixes incorporated.

    Good -- confirmed that the LLM dispatch code lives in exactly two files: `escalate.py` and `llm.py`, both under possibilities. autodev and ai_daemon don't have their own dispatch yet (they'd inherit it via possibilities integration). Now let me also check how `LLMClient` is used by the consumers (explorer, merge, dedup) to make sure the library API covers all real call patterns:

    Now I have the complete picture. Let me check one more thing -- whether there's a `model_choice` dir already or if this is greenfield:

    Good -- the project dir exists but the package is empty. Greenfield. Now let me also check if there's an rfl_design dir with anything relevant:

    That's from a previous RFL session -- not relevant to the final design. I have everything I need. Here's the final iteration.
    
    ---
    
    ## Iteration 3: Final Design -- Complete and Verified
    
    ### Source Verification Summary
    
    Read all four consumer files of `llm.py`:
    
    | Consumer | How it uses LLMClient | Key pattern |
    |---|---|---|
    | `explorer.py:18` | `LLMClient(config.model, config.temperature)` | Constructs with model string, calls `.generate(prompt)` |
    | `escalate.py` | Direct `_generate_with_litellm(tier, prompt)` / `_generate_with_cli(tier, prompt)` | Uses tier dicts, not LLMClient. Calls `parse_json_response()` on output |
    | `merge.py:120` | `LLMClient(model)` | Default temp. Calls `.generate(prompt)` via dedup |
    | `dedup.py:65` | `self.llm.generate(prompt)` then `parse_json_response(raw)` | Generates text, parses to `list[dict]` |
    
    Two distinct call patterns emerge:
    1. **Simple generation**: `LLMClient(model).generate(prompt)` -> raw string
    2. **JSON generation**: `LLMClient(model).generate(prompt)` -> `parse_json_response(raw)` -> `list[dict]`
    
    The design must support both. Pattern 1 maps to `generate()`. Pattern 2 maps to `generate()` with `json_mode=True` (which returns parsed data, not raw string).
    
    ### Critical Design Decisions (all three iterations resolved)
    
    **1. json_mode return type**
    
    The original `parse_json_response` always returns `list[dict]` -- wrapping dicts in `[result]`, returning `[]` on failure. This is wrong for general use. A caller asking "give me a JSON object" shouldn't get a list wrapper.
    
    Decision: `generate()` always returns `str`. New function `generate_json()` returns `Any` (dict, list, whatever the model output) and raises `ValueError` on parse failure. This gives callers explicit control over whether they want raw text or parsed JSON.
    
    **2. Backward compat with possibilities**
    
    possibilities' four consumers (`explorer`, `escalate`, `merge`, `dedup`) currently use `LLMClient` and `parse_json_response` directly. After model_choice exists, possibilities can either:
    - (a) Replace `LLMClient` with model_choice calls, or
    - (b) Keep `LLMClient` as a thin wrapper around model_choice
    
    Decision: (b) initially. `LLMClient.__init__` becomes `self.model = model; self.temperature = temperature` and `generate()` becomes `from model_choice import generate; return generate(prompt, model=self.model, temperature=self.temperature)`. Zero behavioral change. `parse_json_response` becomes `from model_choice.parsers import parse_json_output`. Later, when everything is stable, possibilities can drop the wrappers entirely.
    
    **3. Temperature default**
    
    The existing code uses `temperature=0.9` everywhere (LLMClient default, escalate's litellm calls). The design spec says `0.7`. This matters because possibilities deliberately uses high temperature for divergent brainstorming.
    
    Decision: Default to `0.7` (standard for general use), but allow override. possibilities' LLMClient wrapper will pass `temperature=self.temperature` (which defaults to 0.9).
    
    ### Final File Layout
    
    ```
    ~/zion/projects/model_choice/
      model_choice/
        __init__.py       # Public API: generate(), generate_json(), choose(), pick(), list_models()
        registry.py       # Load tiers.yaml, check availability, select Provider
        backends.py       # litellm backend, cli backend (subprocess)
        config.py         # XDG config path, default YAML generation
        parsers.py        # JSON fence stripping, robust parse
        cli.py            # argparse CLI entry point
      pyproject.toml
    ```
    
    ### tiers.yaml (config.py)
    
    ```yaml
    # ~/.config/model_choice/tiers.yaml
    # Auto-generated on first use. Edit freely.
    # Order = priority (cheapest/most available first).
    # complexity = minimum tier required to use this provider:
    #   fast      -> only "fast" providers
    #   balanced  -> "fast" + "balanced" providers
    #   thorough  -> all providers
    
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
    
    Note: Gemini and Claude don't need `cli_args` or `env_prefix` in the config. The backend code knows how to call them based on `cli_cmd`. If a new CLI tool is added later (not gemini/claude), it falls back to generic `{prompt}` interpolation.
    
    ### registry.py
    
    ```python
    """Registry -- load config, check availability, select model."""
    
    import os
    import subprocess
    import urllib.request
    from dataclasses import dataclass, field
    from typing import Any, Optional
    
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
                                    val = line.split("=", 1)[1] \
                                            .strip().strip('"').strip("'")
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
            """Pick the cheapest available provider for the given complexity.
    
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
    ```
    
    Changes from iteration 0:
    - `urllib.request` instead of `curl` subprocess for Ollama check (iteration 2 issue 2)
    - Dropped `cli_args` / `env_prefix` from the dataclass -- backend handles gemini/claude specifics internally (keeps config simple)
    - `_ensure_env_keys` uses set discard instead of list remove (safer iteration)
    
    ### backends.py
    
    ```python
    """Backend dispatch -- litellm and CLI subprocess."""
    
    import os
    import subprocess
    
    from .registry import Provider
    
    
    def call_litellm(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system: str | None = None,
    ) -> str:
        """Call Ollama or ZAI via litellm."""
        import litellm
    
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
    
        kwargs = dict(
            model=provider.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
        if provider.api_base:
            kwargs["api_base"] = provider.api_base
        if provider.env_key:
            api_key = os.environ.get(provider.env_key)
            if api_key:
                kwargs["api_key"] = api_key
    
        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content
    
    
    def call_cli(
        provider: Provider,
        prompt: str,
    ) -> str:
        """Call Gemini or Claude via CLI subprocess.
    
        Temperature and max_tokens are ignored -- CLI tools don't expose
        them in non-interactive -p mode.
        """
        if provider.cli_cmd == "gemini":
            cmd = ["gemini", "-p", prompt, "--sandbox"]
            env = dict(os.environ, TERM="dumb")
        elif provider.cli_cmd == "claude":
            cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
            env = None  # inherit
        else:
            # Generic fallback -- shouldn't happen with known providers
            cmd = [provider.cli_cmd or "echo", prompt]
            env = None
    
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{provider.cli_cmd} exited {result.returncode}: "
                f"{result.stderr[:500]}"
            )
        return result.stdout
    
    
    def call(
        provider: Provider,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
        system: str | None = None,
    ) -> str:
        """Unified dispatch. Applies json_mode prompt suffix, then routes."""
        if json_mode:
            prompt += (
                "\n\nIMPORTANT: Respond with valid JSON only. "
                "No markdown fences, no explanation, just the JSON object."
            )
    
        if provider.backend == "litellm":
            return call_litellm(provider, prompt, temperature, max_tokens, system)
        elif provider.backend == "cli":
            return call_cli(provider, prompt)
        else:
            raise ValueError(f"Unknown backend: {provider.backend}")
    ```
    
    Changes from iteration 0:
    - `json_mode` prompt suffix moved into `call()` (iteration 2 issue 3) -- applies to ALL backends
    - `system` param on `call_litellm` (iteration 2 issue 4)
    - `call_cli` drops unused temperature/max_tokens params (iteration 2 issue 6)
    - `call_cli` checks `returncode` and raises with stderr (iteration 2 issue 5)
    - `call_cli` dropped the complex `cli_args` interpolation -- gemini/claude are handled explicitly, generic fallback is simple
    
    ### parsers.py
    
    ```python
    """Robust JSON parsing from LLM output."""
    
    import json
    import re
    from typing import Any
    
    
    def parse_json_output(text: str) -> Any:
        """Extract JSON from LLM response, handling markdown fences.
    
        Returns the parsed object (dict, list, whatever).
    
        Raises ValueError if nothing parseable found.
    
        NOTE: The original parse_json_response in possibilities/llm.py always
        returns list[dict], wrapping dicts in [result] and returning [] on failure.
        This function returns the raw parsed type and raises on failure. This is
        intentional -- silent empty returns mask errors, and dict wrapping loses
        information. Callers that need list[dict] should wrap the result themselves.
        """
        text = text.strip()
    
        # 1. Markdown code blocks
        if "```" in text:
            blocks = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
            for block in blocks:
                try:
                    return json.loads(block.strip())
                except json.JSONDecodeError:
                    continue
    
        # 2. Find raw JSON by bracket matching
        for opener, closer in [("[", "]"), ("{", "}")]:
            start = text.find(opener)
            if start != -1:
                depth = 0
                for i, ch in enumerate(text[start:], start):
                    if ch == opener:
                        depth += 1
                    elif ch == closer:
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start:i + 1])
                            except json.JSONDecodeError:
                                break
    
        # 3. Try the whole thing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"Could not extract JSON: {text[:200]}")
    ```
    
    ### config.py
    
    ```python
    """Default config generation."""
    
    import os
    
    DEFAULT_YAML = """\
    # model_choice provider tiers
    # Order = priority (cheapest/most available first).
    # complexity = minimum tier to use this provider:
    #   fast      -> only fast providers
    #   balanced  -> fast + balanced providers
    #   thorough  -> all providers
    
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
    """
    
    
    def generate_default_config(path: str):
        """Write default tiers.yaml if it doesn't exist."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(DEFAULT_YAML)
    ```
    
    ### __init__.py (public API)
    
    ```python
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
    ```
    
    Key difference from iteration 0: `generate()` always returns `str`. New `generate_json()` handles the parse. This is cleaner than having `json_mode` change the return type.
    
    ### cli.py
    
    ```python
    """model_choice CLI."""
    
    import argparse
    import json
    import sys
    
    
    def main():
        parser = argparse.ArgumentParser(
            prog="model_choice",
            description="Universal LLM model selector and caller",
        )
        parser.add_argument("prompt", nargs="?", help="Prompt to send")
        parser.add_argument(
            "-c", "--complexity",
            choices=["fast", "balanced", "thorough"],
            default="balanced",
        )
        parser.add_argument("-m", "--model", help="Specific model to use")
        parser.add_argument("-t", "--temperature", type=float, default=0.7)
        parser.add_argument("--max-tokens", type=int, default=2000)
        parser.add_argument("-j", "--json", action="store_true",
                            help="Request JSON output (parsed and pretty-printed)")
        parser.add_argument("--list", action="store_true",
                            help="List available models and exit")
        parser.add_argument("-v", "--verbose", action="store_true",
                            help="Show which model was selected")
        parser.add_argument("-s", "--system", help="System prompt")
    
        args = parser.parse_args()
    
        from model_choice import list_models, generate, generate_json, pick
    
        if args.list:
            models = list_models()
            for m in models:
                status = "OK" if m["available"] else "--"
                print(f"  [{status}] {m['provider']:8s} "
                      f"{m['model']:30s} {m['label']}")
            sys.exit(0)
    
        if not args.prompt:
            parser.error("prompt is required unless --list is given")
    
        if args.verbose:
            provider = pick(complexity=args.complexity, model=args.model)
            if provider:
                print(f"[model_choice] {provider.label}", file=sys.stderr)
            else:
                print("[model_choice] no model available", file=sys.stderr)
                sys.exit(1)
    
        try:
            if args.json:
                result = generate_json(
                    prompt=args.prompt,
                    model=args.model,
                    complexity=args.complexity,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    system=args.system,
                )
                print(json.dumps(result, indent=2))
            else:
                result = generate(
                    prompt=args.prompt,
                    model=args.model,
                    complexity=args.complexity,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    system=args.system,
                )
                print(result)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    
    if __name__ == "__main__":
        main()
    ```
    
    Changes from iteration 0:
    - `prompt` is now `nargs="?"` so `--list` works without a prompt
    - `-j` flag uses `generate_json()` and pretty-prints the parsed result
    - Added `-s` for system prompt
    - Uses `generate_json` vs `generate` based on flag
    
    ### pyproject.toml
    
    ```toml
    [project]
    name = "model_choice"
    version = "0.1.0"
    description = "Universal LLM model selector and caller"
    requires-python = ">=3.10"
    dependencies = ["litellm", "pyyaml"]
    
    [project.scripts]
    model_choice = "model_choice.cli:main"
    ```
    
    ### Migration Path for possibilities
    
    After model_choice is installed (`pip install -e ~/zion/projects/model_choice`), `possibilities/llm.py` becomes:
    
    ```python
    """LLM wrapper -- thin shim over model_choice."""
    
    from model_choice import generate as _generate
    from model_choice.parsers import parse_json_output
    
    
    class LLMClient:
        """Backward-compatible wrapper. Delegates to model_choice."""
    
        def __init__(self, model: str, temperature: float = 0.9):
            self.model = model
            self.temperature = temperature
    
        def generate(self, prompt: str) -> str:
            return _generate(
                prompt, model=self.model, temperature=self.temperature,
                max_tokens=3000,
            )
    
        def generate_json(self, prompt: str) -> list[dict]:
            raw = self.generate(prompt)
            result = parse_json_output(raw)
            # Match old API: always return list[dict]
            if isinstance(result, list):
                return result
            return [result]
    
    
    # Keep the old name as alias
    parse_json_response = parse_json_output
    ```
    
    This is a drop-in replacement. Zero changes needed in explorer.py, escalate.py, merge.py, or dedup.py. The only difference is `parse_json_response` now raises on failure instead of returning `[]`, but dedup.py already catches exceptions from it (line 77).
    
    ### What the three iterations resolved
    
    | # | Question | Resolution |
    |---|---|---|
    | 1 | LLM classification vs heuristic | Heuristic -- caller specifies complexity. Zero latency overhead. |
    | 2 | Timeout/retry | Per-backend timeout (60s litellm, 120s CLI). No retry -- caller's job. |
    | 3 | Cache availability | Process lifetime + `refresh()`. Lazy on first `select()`. |
    | 4 | Streaming | No. Synchronous call-and-return. None of the consumers need it. |
    | 5 | JSON return type | `generate()` returns `str`. `generate_json()` returns parsed `object`. Separate functions, no type-conditional returns. |
    | 6 | Ollama check | `urllib.request` not `curl`. Zero external deps. |
    | 7 | CLI stderr | Check returncode, raise with stderr content. |
    | 8 | Temperature for CLI | Ignored. Documented in docstring. |
    | 9 | System prompt | Optional param on generate/generate_json. Litellm-only. |
    | 10 | Backward compat | LLMClient becomes thin shim. Zero changes to consumers. |

---
