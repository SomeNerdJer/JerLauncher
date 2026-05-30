from __future__ import annotations

import json
import shutil
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = _SRC_ROOT / "config" / "profile_state.json"
ASSETS_DIR = _SRC_ROOT / "assets"
GAMERPICS_DIR = ASSETS_DIR / "gamerpics"
CUSTOM_GAMERPIC_REL = "gamerpics/custom.png"
DEFAULT_GAMERTAG = "Player1"
MAX_GAMERTAG_LEN = 15
GAMERPIC_GRID_COLS = 6
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _default_profile() -> dict[str, str]:
    return {"gamertag": DEFAULT_GAMERTAG, "gamerpic": ""}


def load_profile() -> dict[str, str]:
    data = _default_profile()
    if not PROFILE_PATH.exists():
        return data
    try:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return data
    if isinstance(raw, dict):
        tag = str(raw.get("gamertag", data["gamertag"])).strip()
        data["gamertag"] = tag[:MAX_GAMERTAG_LEN] if tag else DEFAULT_GAMERTAG
        data["gamerpic"] = str(raw.get("gamerpic", "")).strip()
    return data


def save_profile(gamertag: str, gamerpic: str = "") -> None:
    tag = (gamertag or DEFAULT_GAMERTAG).strip()[:MAX_GAMERTAG_LEN] or DEFAULT_GAMERTAG
    payload = {"gamertag": tag, "gamerpic": gamerpic.strip()}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_gamerpic_path(relative_name: str) -> Path | None:
    name = relative_name.strip()
    if not name:
        return None
    direct = ASSETS_DIR / name
    if direct.is_file():
        return direct
    # Legacy: gamerpic.png at assets root
    if "/" not in name and "\\" not in name:
        legacy = ASSETS_DIR / name
        if legacy.is_file():
            return legacy
    return None


def gamerpic_absolute(relative_name: str | None = None) -> Path | None:
    return _resolve_gamerpic_path(relative_name or load_profile().get("gamerpic", ""))


def list_preset_gamerpics() -> list[str]:
    """Relative paths (gamerpics/foo.png) for built-in tiles, excluding custom."""
    if not GAMERPICS_DIR.is_dir():
        return []
    presets: list[str] = []
    for path in sorted(GAMERPICS_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if path.name.lower() == "custom.png":
            continue
        presets.append(f"gamerpics/{path.name}")
    return presets


def gamerpic_grid_slots() -> list[dict[str, str | bool]]:
    """First slot is Custom; remaining slots are preset images."""
    slots: list[dict[str, str | bool]] = [{"rel": CUSTOM_GAMERPIC_REL, "custom": True, "label": "Custom"}]
    for rel in list_preset_gamerpics():
        name = Path(rel).stem
        slots.append({"rel": rel, "custom": False, "label": name})
    return slots


def copy_gamerpic_file(source: Path) -> str:
    """Copy image into gamerpics/custom.png; return path stored in profile."""
    GAMERPICS_DIR.mkdir(parents=True, exist_ok=True)
    dest = GAMERPICS_DIR / "custom.png"
    shutil.copy2(source, dest)
    return CUSTOM_GAMERPIC_REL
