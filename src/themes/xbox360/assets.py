from __future__ import annotations

from pathlib import Path

from core.theme_context import get_active


def theme_asset(relative: str) -> Path:
    theme = get_active()
    if theme is not None:
        return theme.asset(relative)
    project_root = Path(__file__).resolve().parents[2].parent
    rel = relative.replace("\\", "/").lstrip("/")
    return project_root / rel
