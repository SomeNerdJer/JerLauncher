"""Display formatting for page and section headings."""

from __future__ import annotations


def page_title(text: str) -> str:
    """Page/section heading shown in the UI (always lowercase)."""
    return text.lower()
