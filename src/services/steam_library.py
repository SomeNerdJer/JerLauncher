"""
Discover installed Steam library games from local manifests (Windows).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


# Bundled tools / runtimes often clutter the list
_SKIP_APPIDS: frozenset[int] = frozenset(
    {
        228980,  # Steamworks Common Redistributables
        250820,  # Steam Linux Runtime
        1070560,  # Steam Linux Runtime soldier
        1391110,  # Steam Linux Runtime sniper
        1628350,  # Steam Runtime
    }
)

_SKIP_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^proton\b", re.IGNORECASE),
    re.compile(r"^steam linux runtime\b", re.IGNORECASE),
    re.compile(r"^steamworks common redistributables\b", re.IGNORECASE),
)


def _steam_install_dir() -> Path | None:
    if winreg is None:
        return None
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as key:
                path, _ = winreg.QueryValueEx(key, "SteamPath")
                p = Path(str(path).strip())
                if p.is_dir():
                    return p
        except OSError:
            continue
    return None


def _library_steamapps_dirs(steam_root: Path) -> list[Path]:
    dirs: list[Path] = []
    main = steam_root / "steamapps"
    if main.is_dir():
        dirs.append(main)

    vdf = steam_root / "config" / "libraryfolders.vdf"
    if not vdf.is_file():
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return dirs

    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return dirs

    for m in re.finditer(r'"path"\s+"([^"]*)"', text):
        raw = m.group(1).replace("\\\\", "\\").strip()
        if not raw:
            continue
        lib = Path(raw)
        apps = lib / "steamapps"
        if apps.is_dir() and apps not in dirs:
            dirs.append(apps)
    return dirs


def _parse_appmanifest(text: str) -> tuple[int, str] | None:
    app_m = re.search(r'"appid"\s+"(\d+)"', text)
    name_m = re.search(r'"name"\s+"([^"]*)"', text)
    if not app_m or not name_m:
        return None
    appid = int(app_m.group(1))
    name = name_m.group(1).strip()
    if not name:
        return None
    return appid, name


def _find_library_header_jpeg(steam_root: Path, appid: int) -> Path | None:
    cache = steam_root / "appcache" / "librarycache"
    if not cache.is_dir():
        return None
    candidates = [
        cache / f"{appid}_library_600x900.jpg",
        cache / f"{appid}_library_600x900.webp",
        cache / str(appid) / "library_600x900.jpg",
        cache / str(appid) / "library_hero.jpg",
        cache / str(appid) / "library_hero_blur.jpg",
    ]
    for p in candidates:
        if p.is_file():
            return p
    sub = cache / str(appid)
    if sub.is_dir():
        for p in sorted(sub.glob("library_*.*")):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                return p
    return None


def _find_user_grid_image(steam_root: Path, appid: int) -> Path | None:
    userdata_root = steam_root / "userdata"
    if not userdata_root.is_dir():
        return None
    candidates = (
        f"{appid}p",
        f"{appid}_library_600x900",
        f"{appid}_hero",
        str(appid),
    )
    exts = (".jpg", ".jpeg", ".png", ".webp")
    for user_dir in userdata_root.iterdir():
        if not user_dir.is_dir():
            continue
        grid_dir = user_dir / "config" / "grid"
        if not grid_dir.is_dir():
            continue
        for stem in candidates:
            for ext in exts:
                p = grid_dir / f"{stem}{ext}"
                if p.is_file():
                    return p
        # Final sweep for any matching prefix (covers more naming variants).
        for p in sorted(grid_dir.glob(f"{appid}*")):
            if p.is_file() and p.suffix.lower() in exts:
                return p
    return None


def _steam_library_image_url(appid: int) -> str:
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"


def _is_hidden_tool_title(name: str) -> bool:
    cleaned = name.strip()
    if not cleaned:
        return True
    for pattern in _SKIP_NAME_PATTERNS:
        if pattern.search(cleaned):
            return True
    return False


def list_installed_steam_games(*, fast: bool = False) -> list[dict[str, Any]]:
    steam_root = _steam_install_dir()
    if steam_root is None:
        return []

    steam_exe = steam_root / "steam.exe"
    if not steam_exe.is_file():
        return []

    games_by_id: dict[int, dict[str, Any]] = {}
    for apps_dir in _library_steamapps_dirs(steam_root):
        for manifest in apps_dir.glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            parsed = _parse_appmanifest(text)
            if not parsed:
                continue
            appid, name = parsed
            if appid in _SKIP_APPIDS:
                continue
            if _is_hidden_tool_title(name):
                continue
            if appid in games_by_id:
                continue
            if fast:
                header = None
            else:
                header = _find_library_header_jpeg(steam_root, appid)
                if header is None:
                    header = _find_user_grid_image(steam_root, appid)
            games_by_id[appid] = {
                "title": name,
                "appid": appid,
                "store": "steam",
                "library_key": f"steam:{appid}",
                "command": str(steam_exe),
                "args": [f"steam://run/{appid}"],
                "cwd": str(steam_root),
                "header_image": str(header) if header else _steam_library_image_url(appid),
            }

    out = sorted(games_by_id.values(), key=lambda g: g["title"].casefold())
    return out


# Steam store category ids (appdetails) — controller support
_STEAM_CATEGORY_FULL_CONTROLLER = 28
_STEAM_CATEGORY_PARTIAL_CONTROLLER = 18


def fetch_steam_full_controller_support(appid: int) -> bool | None:
    """
    True if the store page lists full or partial controller support.
    False if the game is on the store but has neither.
    None if the API did not return usable category data.
    """
    if appid <= 0:
        return None
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
    try:
        with urllib.request.urlopen(url, timeout=4.0) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None
    try:
        parsed = json.loads(payload.decode("utf-8", errors="ignore"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    row = parsed.get(str(appid))
    if not isinstance(row, dict) or not row.get("success"):
        return None
    data = row.get("data")
    if not isinstance(data, dict):
        return None
    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        return False
    for c in categories:
        if not isinstance(c, dict):
            continue
        try:
            cid = int(c.get("id", 0))
        except (TypeError, ValueError):
            continue
        if cid in (_STEAM_CATEGORY_FULL_CONTROLLER, _STEAM_CATEGORY_PARTIAL_CONTROLLER):
            return True
    return False


def fetch_steam_game_description(appid: int) -> str | None:
    if appid <= 0:
        return None
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
    try:
        with urllib.request.urlopen(url, timeout=4.0) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None
    try:
        parsed = json.loads(payload.decode("utf-8", errors="ignore"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    row = parsed.get(str(appid))
    if not isinstance(row, dict) or not row.get("success"):
        return None
    data = row.get("data")
    if not isinstance(data, dict):
        return None
    detailed = str(data.get("short_description") or "").strip()
    if detailed:
        return detailed
    fallback = str(data.get("detailed_description") or "").strip()
    if fallback:
        return fallback
    return None
