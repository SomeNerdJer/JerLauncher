from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ThemePackage:
    id: str
    name: str
    version: str
    root: Path
    config: dict[str, Any]
    module: str
    source_zip: Path | None = None

    def asset(self, relative: str) -> Path:
        rel = relative.replace("\\", "/").lstrip("/")
        return self.root / rel


_active: ThemePackage | None = None


def set_active(theme: ThemePackage | None) -> None:
    global _active
    _active = theme


def get_active() -> ThemePackage | None:
    return _active


def resolve_asset(relative: str, *, project_root: Path) -> Path:
    if _active is not None:
        return _active.asset(relative)
    return project_root / relative.replace("\\", "/").lstrip("/")
