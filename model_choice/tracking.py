"""Cost tracking -- token counts and call counts per provider."""

import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderStats:
    """Running stats for a single provider."""
    calls: int = 0
    failures: int = 0
    # litellm providers report token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CostTracker:
    """Track LLM usage per provider for the process lifetime.

    Thread-safe. Call record() after each generate call.
    """

    def __init__(self):
        self._stats: dict[str, ProviderStats] = {}
        self._lock = threading.Lock()

    def record(self, provider_name: str, success: bool = True,
               prompt_tokens: int = 0, completion_tokens: int = 0,
               total_tokens: int = 0):
        with self._lock:
            if provider_name not in self._stats:
                self._stats[provider_name] = ProviderStats()
            s = self._stats[provider_name]
            s.calls += 1
            if not success:
                s.failures += 1
            s.prompt_tokens += prompt_tokens
            s.completion_tokens += completion_tokens
            s.total_tokens += total_tokens

    def summary(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {
                    "calls": s.calls,
                    "failures": s.failures,
                    "prompt_tokens": s.prompt_tokens,
                    "completion_tokens": s.completion_tokens,
                    "total_tokens": s.total_tokens,
                }
                for name, s in self._stats.items()
            }

    def totals(self) -> dict:
        with self._lock:
            total_calls = sum(s.calls for s in self._stats.values())
            total_failures = sum(s.failures for s in self._stats.values())
            total_prompt = sum(s.prompt_tokens for s in self._stats.values())
            total_completion = sum(s.completion_tokens for s in self._stats.values())
            total_all = sum(s.total_tokens for s in self._stats.values())
            return {
                "calls": total_calls,
                "failures": total_failures,
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_all,
                "providers": len(self._stats),
            }

    def reset(self):
        with self._lock:
            self._stats.clear()
