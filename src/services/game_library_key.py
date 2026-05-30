"""Stable keys for merged store library rows (art cache, overrides)."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def steam_library_key(appid: int) -> str:
    return f"steam:{int(appid)}"


def row_library_key(game: dict[str, Any]) -> str:
    lk = str(game.get("library_key") or "").strip()
    if lk:
        return lk
    aid = int(game.get("appid", 0))
    return steam_library_key(aid) if aid > 0 else ""


def row_store(game: dict[str, Any]) -> str:
    s = str(game.get("store") or "").strip().lower()
    if s in ("steam", "epic", "ea", "rockstar"):
        return s
    return "steam" if int(game.get("appid", 0)) > 0 else "unknown"


def parse_steam_appid(library_key: str) -> int | None:
    if library_key.startswith("steam:"):
        try:
            return int(library_key.split(":", 1)[1])
        except ValueError:
            return None
    return None


def epic_header_slug(library_key: str) -> str:
    """Filesystem-safe short name for Epic header assets (no raw colons in paths)."""
    h = hashlib.sha256(library_key.encode("utf-8")).hexdigest()[:20]
    return f"e_{h}"


def sanitize_override_key(library_key: str) -> str:
    """JSON override key: epic keys use slug; steam uses legacy numeric or steam:id."""
    if library_key.startswith("steam:"):
        aid = parse_steam_appid(library_key)
        if aid is not None:
            return str(aid)
    return re.sub(r"[^\w.\-]", "_", library_key)[:120]
