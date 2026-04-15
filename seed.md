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
