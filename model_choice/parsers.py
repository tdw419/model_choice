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
