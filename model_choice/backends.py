"""Backend dispatch -- litellm and CLI subprocess."""

import os
import subprocess
from dataclasses import dataclass
from typing import Generator, Optional

from .registry import Provider


@dataclass
class GenerateResult:
    """Result from a generate call, including usage stats."""
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


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
    usage = getattr(resp, 'usage', None)
    return GenerateResult(
        text=resp.choices[0].message.content,
        prompt_tokens=getattr(usage, 'prompt_tokens', 0) if usage else 0,
        completion_tokens=getattr(usage, 'completion_tokens', 0) if usage else 0,
        total_tokens=getattr(usage, 'total_tokens', 0) if usage else 0,
    )


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
        # Generic fallback
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
    # CLI backends don't report token counts
    return GenerateResult(text=result.stdout)


# ---- streaming backends ----

def stream_litellm(
    provider: Provider,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    system: str | None = None,
) -> Generator[str, None, None]:
    """Stream from litellm, yielding text chunks."""
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
        stream=True,
    )

    if provider.api_base:
        kwargs["api_base"] = provider.api_base
    if provider.env_key:
        api_key = os.environ.get(provider.env_key)
        if api_key:
            kwargs["api_key"] = api_key

    for chunk in litellm.completion(**kwargs):
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


def stream_cli(
    provider: Provider,
    prompt: str,
) -> Generator[str, None, None]:
    """Stream from CLI subprocess, yielding text chunks as they arrive."""
    if provider.cli_cmd == "gemini":
        cmd = ["gemini", "-p", prompt, "--sandbox"]
        env = dict(os.environ, TERM="dumb")
    elif provider.cli_cmd == "claude":
        cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
        env = None
    else:
        cmd = [provider.cli_cmd or "echo", prompt]
        env = None

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            yield chunk
        proc.wait(timeout=10)
    finally:
        # Ensure process is reaped even if consumer abandons the generator
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.returncode != 0:
            stderr = proc.stderr.read()
            raise RuntimeError(
                f"{provider.cli_cmd} exited {proc.returncode}: "
                f"{stderr[:500]}"
            )


def stream(
    provider: Provider,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    json_mode: bool = False,
    system: str | None = None,
) -> Generator[str, None, None]:
    """Unified streaming dispatch. Applies json_mode prompt suffix, then routes."""
    if json_mode:
        prompt += (
            "\n\nIMPORTANT: Respond with valid JSON only. "
            "No markdown fences, no explanation, just the JSON object."
        )

    if provider.backend == "litellm":
        yield from stream_litellm(provider, prompt, temperature, max_tokens, system)
    elif provider.backend == "cli":
        yield from stream_cli(provider, prompt)
    else:
        raise ValueError(f"Unknown backend: {provider.backend}")


# ---- unified dispatch ----

def call(
    provider: Provider,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    json_mode: bool = False,
    system: str | None = None,
) -> GenerateResult:
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
