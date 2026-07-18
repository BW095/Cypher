"""Shared helpers for parsing and cleaning LLM subprocess output."""

import json
import re


# Qwen3 models may emit reasoning blocks under several tag names.
_THINKING_TAG_PATTERNS = [
    r"<\s*think\s*>.*?<\s*/\s*think\s*>",
    r"<\s*thinking\s*>.*?<\s*/\s*thinking\s*>",
    r"<\s*redacted_thinking\s*>.*?<\s*/\s*redacted_thinking\s*>",
]


def strip_thinking_tags(text: str) -> str:
    """Remove model reasoning blocks and return the visible answer."""
    if not text:
        return ""

    cleaned = text
    for pattern in _THINKING_TAG_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    return cleaned.strip()


def parse_subprocess_json(stdout: str, stderr: str = "") -> dict | None:
    """Parse the worker's JSON payload from subprocess stdout.

    Scans stdout from the last line upward so llama.cpp load logs do not
    break parsing when they appear on stdout.
    """
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and "ok" in payload:
                return payload
        except json.JSONDecodeError:
            continue

    if stderr:
        for line in reversed(stderr.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict) and payload.get("ok") is False:
                    return payload
            except json.JSONDecodeError:
                continue

    return None


def extract_result(payload: dict | None) -> str:
    """Return the text result from a worker payload, normalizing null/None."""
    if not payload or not payload.get("ok"):
        return ""

    result = payload.get("result")
    if result is None:
        return ""

    return str(result).strip()
