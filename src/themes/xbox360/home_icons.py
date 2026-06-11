"""
Hub tile icons — bundled under assets/dashboard_icons/ and assets/settings_icons/.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from themes.xbox360.assets import theme_asset

_ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp")

_ICON_CANDIDATES: dict[str, dict[str, tuple[str, ...]]] = {
    "home": {
        "my_pins": ("my_pins", "pin"),
        "browse_apps": ("browse_apps", "apps_marketplace"),
        "my_apps": ("my_apps", "myapps"),
        "my_games": ("my_games", "mygames"),
    },
    "settings": {
        "display": ("display", "preferences"),
        "sound": ("sound", "music"),
        "network": ("network", "account"),
        "system": ("system",),
        "personalization": ("personalization", "avatar_store", "transparent_avatars"),
        "power": ("power", "turnoff"),
    },
}


def _icon_directory(icon_set: str) -> Path:
    if icon_set == "home":
        return theme_asset("assets/dashboard_icons")
    return theme_asset("assets/settings_icons")

_CACHE: dict[str, pygame.Surface | None] = {}
_PATH_CACHE: dict[tuple[str, str], Path | None] = {}
_SCALED_CACHE: dict[tuple[str, str, int, int], pygame.Surface | None] = {}


def _search_icon_path(directory: Path, basename: str) -> Path | None:
    for ext in _ICON_EXTS:
        path = directory / f"{basename}{ext}"
        if path.is_file():
            return path
    return None


def resolve_icon_path(icon_id: str, icon_set: str = "home") -> Path | None:
    cache_key = (icon_set, icon_id)
    if cache_key in _PATH_CACHE:
        return _PATH_CACHE[cache_key]
    pack = _ICON_CANDIDATES.get(icon_set)
    if pack is None:
        _PATH_CACHE[cache_key] = None
        return None
    directory = _icon_directory(icon_set)
    names = pack.get(icon_id, (icon_id,))
    found: Path | None = None
    if directory.is_dir():
        for name in names:
            hit = _search_icon_path(directory, name)
            if hit is not None:
                found = hit
                break
    _PATH_CACHE[cache_key] = found
    return found


def load_tile_icon(icon_id: str, icon_set: str = "home") -> pygame.Surface | None:
    cache_key = f"{icon_set}:{icon_id}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    path = resolve_icon_path(icon_id, icon_set)
    if path is None:
        _CACHE[cache_key] = None
        return None
    try:
        surf = pygame.image.load(str(path)).convert_alpha()
    except (pygame.error, FileNotFoundError):
        surf = None
    _CACHE[cache_key] = surf
    return surf


def scaled_tile_icon(
    icon_id: str,
    max_w: int,
    max_h: int,
    *,
    icon_set: str = "home",
) -> pygame.Surface | None:
    if max_w <= 0 or max_h <= 0:
        return None
    key = (icon_set, icon_id, max_w, max_h)
    hit = _SCALED_CACHE.get(key)
    if hit is not None:
        return hit
    src = load_tile_icon(icon_id, icon_set)
    if src is None:
        _SCALED_CACHE[key] = None
        return None
    sw, sh = src.get_size()
    if sw <= 0 or sh <= 0:
        _SCALED_CACHE[key] = None
        return None
    scale = min(max_w / sw, max_h / sh)
    tw = max(1, int(sw * scale))
    th = max(1, int(sh * scale))
    if tw == sw and th == sh:
        scaled = src
    else:
        scaled = pygame.transform.smoothscale(src, (tw, th))
    _SCALED_CACHE[key] = scaled
    return scaled


def draw_tile_icon(
    screen: pygame.Surface,
    rect: pygame.Rect,
    icon_id: str | None,
    *,
    label_bottom_reserve: int,
    icon_set: str = "home",
    width_ratio: float = 0.58,
    top_ratio: float = 0.12,
) -> None:
    if not icon_id:
        return
    max_w = int(rect.w * width_ratio)
    max_h = max(24, rect.h - label_bottom_reserve - int(rect.h * 0.18))
    icon = scaled_tile_icon(icon_id, max_w, max_h, icon_set=icon_set)
    if icon is None:
        return
    ix = rect.centerx - icon.get_width() // 2
    iy = rect.y + int(rect.h * top_ratio)
    screen.blit(icon, (ix, iy))


def draw_home_tile_icon(
    screen: pygame.Surface,
    rect: pygame.Rect,
    icon_id: str | None,
    *,
    label_bottom_reserve: int,
) -> None:
    draw_tile_icon(
        screen,
        rect,
        icon_id,
        label_bottom_reserve=label_bottom_reserve,
        icon_set="home",
    )
