from __future__ import annotations

import json
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
PINNED_GAMES_PATH = _SRC_ROOT / "config" / "pinned_games.json"


def load_pinned_library_keys() -> set[str]:
    if not PINNED_GAMES_PATH.is_file():
        return set()
    try:
        raw = json.loads(PINNED_GAMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, dict):
        return set()
    keys = raw.get("library_keys")
    if not isinstance(keys, list):
        return set()
    return {str(k) for k in keys if isinstance(k, str) and k.strip()}


def save_pinned_library_keys(keys: set[str]) -> None:
    try:
        PINNED_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"library_keys": sorted(keys)}
        PINNED_GAMES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
