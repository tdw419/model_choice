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
    max_concurrent: 4
    min_interval: 1.0

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

# Templates -- named presets for different consumers
# Use via: generate(prompt, template="ai_daemon")
#   or:     configure(template="ai_daemon")
#   or:     MODEL_CHOICE_TEMPLATE=ai_daemon env var

templates:
  - name: ai_daemon
    providers:
      - ollama
    default_complexity: fast
    fallback: false

  - name: agent
    providers:
      - zai
      - ollama
      - gemini
      - claude
    default_complexity: balanced
"""


def generate_default_config(path: str):
    """Write default tiers.yaml if it doesn't exist."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(DEFAULT_YAML)
