from __future__ import annotations

import importlib
from typing import Any, Callable

from core.theme_context import ThemePackage


ThemeFactory = Callable[..., Any]


def load_theme_module(theme: ThemePackage) -> Any:
    try:
        return importlib.import_module(theme.module)
    except ImportError as exc:
        raise RuntimeError(
            f"Theme module '{theme.module}' is not installed for theme '{theme.name}'."
        ) from exc
