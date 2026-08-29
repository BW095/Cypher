"""Shared helpers for parsing and cleaning LLM output."""

import re


# Models may emit reasoning blocks under several tag names.
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
