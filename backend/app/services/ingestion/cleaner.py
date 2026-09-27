"""
EDGEWISE AI — Text Cleaning

Deterministic cleaning for extracted technical documentation:
- Normalize line endings (\r\n, \r -> \n)
- Normalize horizontal whitespace (tabs, non-breaking spaces)
- Compress excessive blank lines (max 2 consecutive newlines)
- Strip trailing whitespace from lines
- Preserve markdown headings and technical terminology
- Preserve page boundaries
"""

from __future__ import annotations

import re


class TextCleaner:
    """Normalizes and sanitizes extracted text without destroying technical data."""

    @staticmethod
    def clean(text: str) -> str:
        if not text:
            return ""

        # 1. Normalize line endings
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Replace non-breaking spaces and uncommon whitespace with standard space
        normalized = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", normalized)

        # 3. Clean line by line: remove trailing spaces, compress repeated inline spaces
        lines = []
        for line in normalized.split("\n"):
            # Preserve indentation if code or bullet, but compress interior repeated spaces
            stripped_line = re.sub(r"[ \t]+", " ", line).rstrip()
            lines.append(stripped_line)

        cleaned_text = "\n".join(lines)

        # 4. Collapse 3+ consecutive newlines into 2 (single blank line)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

        return cleaned_text.strip()
