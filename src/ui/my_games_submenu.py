"""
My Games library overlay — Xbox 360–style horizontal shelf (reference: IMG_4571).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pygame

from services.game_library_key import row_library_key, row_store

# Project-root `assets/` — My Games popup backdrops (blue.webp default shelf, night.jpg loading).
_MY_GAMES_BG_CACHE: dict[str, dict[str, Any]] = {}
_MY_GAMES_BG_TINT_CACHE: dict[tuple[int, int], pygame.Surface] = {}
_FONT_CACHE: dict[tuple[str, int], pygame.font.Font] = {}
_FOOTER_HINTS_CACHE: dict[int, pygame.Surface] = {}
_TILE_TITLE_CACHE: dict[str, pygame.Surface] = {}
_STORE_BANNER_CACHE: dict[tuple[str, bool], tuple[pygame.Surface, pygame.Surface]] = {}
_STAT_PLACEHOLDER_CACHE: dict[int, tuple[pygame.Surface, pygame.Surface]] = {}


def _stat_placeholders(font: pygame.font.Font) -> tuple[pygame.Surface, pygame.Surface]:
    key = font.get_height()
    cached = _STAT_PLACEHOLDER_CACHE.get(key)
    if cached is not None:
        return cached
    dim = pygame.Color(100, 104, 110)
    cached = (font.render("--/--", True, dim), font.render("--/--", True, dim))
    _STAT_PLACEHOLDER_CACHE[key] = cached
    return cached


def _sys_font(family: str, size: int) -> pygame.font.Font:
    key = (family, size)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = pygame.font.SysFont(family, size)
        _FONT_CACHE[key] = font
    return font


def scaled_tile_art(
    scaled_art_cache: dict[tuple[str, int, int], pygame.Surface],
    art_cache: dict[str, pygame.Surface | None],
    library_key: str,
    width: int,
    height: int,
) -> pygame.Surface | None:
    """Return art scaled to tile size; uses fast scale with per-size caching."""
    if width <= 0 or height <= 0:
        return None
    cache_key = (library_key, width, height)
    hit = scaled_art_cache.get(cache_key)
    if hit is not None:
        return hit
    src = art_cache.get(library_key)
    if src is None:
        return None
    if src.get_width() == width and src.get_height() == height:
        scaled = src
    else:
        scaled = pygame.transform.scale(src, (width, height))
    scaled_art_cache[cache_key] = scaled
    return scaled

# (filter_id, subtitle under "show me")
MY_GAMES_FILTERS: list[tuple[str, str]] = [
    ("all", "All games"),
    ("steam", "Steam"),
    ("epic", "Epic"),
    ("ea", "EA"),
    ("rockstar", "Rockstar"),
    ("controller", "Controller Supported"),
    ("keyboard", "Keyboard Only"),
    ("hidden", "Hidden"),
]

FILTER_ID_TO_INDEX: dict[str, int] = {fid: i for i, (fid, _) in enumerate(MY_GAMES_FILTERS)}


def filter_label_for_id(filter_id: str) -> str:
    for fid, lab in MY_GAMES_FILTERS:
        if fid == filter_id:
            return lab
    return "All games"


def _my_games_popup_bg_path(bg_filename: str = "blue.webp") -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / bg_filename


def _scaled_my_games_popup_background(
    w: int,
    h: int,
    *,
    bg_filename: str = "blue.webp",
) -> pygame.Surface | None:
    if w <= 0 or h <= 0:
        return None
    path = _my_games_popup_bg_path(bg_filename)
    if not path.is_file():
        _MY_GAMES_BG_CACHE.pop(bg_filename, None)
        return None
    cache = _MY_GAMES_BG_CACHE.setdefault(bg_filename, {})
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        _MY_GAMES_BG_CACHE.pop(bg_filename, None)
        return None
    if cache.get("mtime_ns") != mtime or cache.get("path") != str(path):
        try:
            cache["orig"] = pygame.image.load(str(path)).convert()
            cache["mtime_ns"] = mtime
            cache["path"] = str(path)
            cache["scaled_size"] = None
        except (pygame.error, OSError):
            _MY_GAMES_BG_CACHE.pop(bg_filename, None)
            return None
    orig: pygame.Surface = cache["orig"]
    if cache.get("scaled_size") != (w, h):
        cache["scaled"] = pygame.transform.smoothscale(orig, (w, h))
        cache["scaled_size"] = (w, h)
    return cache["scaled"]


def _blit_my_games_popup_background(
    screen: pygame.Surface,
    sw: int,
    sh: int,
    content_top: int,
    full_screen: bool,
    fallback_color: pygame.Color,
    *,
    bg_filename: str = "blue.webp",
    apply_tint: bool = True,
) -> None:
    if full_screen:
        bw, bh = sw, sh
        dest = pygame.Rect(0, 0, bw, bh)
    else:
        bw = sw
        bh = max(0, sh - content_top)
        dest = pygame.Rect(0, content_top, bw, bh)

    scaled = _scaled_my_games_popup_background(bw, bh, bg_filename=bg_filename)
    if scaled is not None:
        screen.blit(scaled, dest.topleft)
        if apply_tint:
            tint_key = (bw, bh)
            tint = _MY_GAMES_BG_TINT_CACHE.get(tint_key)
            if tint is None:
                tint = pygame.Surface((bw, bh), pygame.SRCALPHA)
                tint.fill((20, 22, 28, 168))
                _MY_GAMES_BG_TINT_CACHE[tint_key] = tint
            screen.blit(tint, dest.topleft)
    else:
        screen.fill(fallback_color, dest)


_LOADING_RING_CACHE: dict[tuple[int, int], pygame.Surface] = {}


def _draw_loading_spinner(
    screen: pygame.Surface,
    center: tuple[int, int],
    *,
    radius: int,
    spin_angle: float,
) -> None:
    """Single white circle ring, rotated as one piece."""
    cx, cy = center
    pad = 6
    size = radius * 2 + pad * 2
    ring = _LOADING_RING_CACHE.get((radius, size))
    if ring is None:
        ring = pygame.Surface((size, size), pygame.SRCALPHA)
        arc_rect = pygame.Rect(pad, pad, radius * 2, radius * 2)
        gap = 0.42
        start = gap / 2
        end = start + (2.0 * math.pi - gap)
        pygame.draw.arc(
            ring,
            pygame.Color(255, 255, 255),
            arc_rect,
            start,
            end,
            width=4,
        )
        _LOADING_RING_CACHE[(radius, size)] = ring
    rotated = pygame.transform.rotate(ring, math.degrees(-spin_angle))
    screen.blit(rotated, rotated.get_rect(center=(cx, cy)))


def draw_my_games_loading_panel(
    screen: pygame.Surface,
    theme: dict[str, Any],
    spin_angle: float,
    *,
    full_screen: bool = True,
) -> None:
    del theme  # loading screen is visual-only (no labels)
    sw, sh = screen.get_size()
    scale = max(0.72, min(sw / 1024.0, sh / 576.0))
    content_top = int(16 * scale) if full_screen else int(54 * scale + 56 * scale + 8 * scale)

    _blit_my_games_popup_background(
        screen,
        sw,
        sh,
        content_top,
        full_screen,
        pygame.Color(20, 22, 28),
        bg_filename="night.jpg",
        apply_tint=False,
    )

    cx, cy = sw // 2, sh // 2
    _draw_loading_spinner(screen, (cx, cy), radius=int(38 * scale), spin_angle=spin_angle)


@dataclass(frozen=True)
class MyGamesPanelLayout:
    """Geometry for the My Games overlay panel (local coordinates)."""

    scale: float
    margin_x: int
    content_top: int
    filter_button_rect: pygame.Rect
    filter_line2_y: int
    dropdown_item_rects: tuple[pygame.Rect, ...]
    dropdown_panel_rect: pygame.Rect
    strip_top: int
    tile_w: int
    tile_h: int
    gap: int
    pitch: int
    footer_reserve: int


def compute_my_games_panel_layout(
    panel_w: int,
    panel_h: int,
    *,
    filter_menu_open: bool,
    full_screen: bool = True,
) -> MyGamesPanelLayout:
    sw, sh = panel_w, panel_h
    scale = min(sw / 1024.0, sh / 576.0)
    scale = max(0.72, scale)

    margin_x = int((20 if full_screen else 40) * scale)
    content_top = int(16 * scale) if full_screen else int(54 * scale + 56 * scale + 8 * scale)

    filter_font_h = int(17 * scale)
    tiny_h = int(14 * scale)
    fy = content_top + int(12 * scale)
    filter_block_w = max(200, int(220 * scale))
    filter_block_h = filter_font_h + tiny_h + int(4 * scale)
    filter_button_rect = pygame.Rect(margin_x, fy, filter_block_w, filter_block_h)
    filter_line2_y = fy + filter_font_h

    rows = len(MY_GAMES_FILTERS)
    row_h = max(28, int(30 * scale))
    pad = int(6 * scale)
    dd_w = max(220, int(260 * scale))
    dd_h = pad * 2 + rows * row_h
    dropdown_panel_rect = pygame.Rect(margin_x, fy + filter_block_h + int(4 * scale), dd_w, dd_h)

    dropdown_item_rects: list[pygame.Rect] = []
    if filter_menu_open:
        for i in range(rows):
            dropdown_item_rects.append(
                pygame.Rect(
                    dropdown_panel_rect.x + pad,
                    dropdown_panel_rect.y + pad + i * row_h,
                    dropdown_panel_rect.w - 2 * pad,
                    row_h - 2,
                )
            )

    footer_reserve = int(46 * scale)
    base_strip_gap = int((88 if full_screen else 96) * scale)
    strip_top = content_top + base_strip_gap
    if filter_menu_open:
        strip_top = max(strip_top, dropdown_panel_rect.bottom + int(14 * scale))

    tile_h = int(max(212 * scale, min((sh - strip_top - footer_reserve) * 0.9, sh * 0.72)))
    tile_w = int(max(132 * scale, tile_h * 0.66))
    gap = int(11 * scale)
    pitch = tile_w + gap

    return MyGamesPanelLayout(
        scale=scale,
        margin_x=margin_x,
        content_top=content_top,
        filter_button_rect=filter_button_rect,
        filter_line2_y=filter_line2_y,
        dropdown_item_rects=tuple(dropdown_item_rects),
        dropdown_panel_rect=dropdown_panel_rect,
        strip_top=strip_top,
        tile_w=tile_w,
        tile_h=tile_h,
        gap=gap,
        pitch=pitch,
        footer_reserve=footer_reserve,
    )


def draw_my_games_submenu(
    screen: pygame.Surface,
    theme: dict[str, Any],
    games: list[dict[str, Any]],
    selected_index: int,
    art_cache: dict[str, pygame.Surface | None],
    load_header_fn: Callable[[str, str | None], None],
    *,
    scaled_art_cache: dict[tuple[str, int, int], pygame.Surface] | None = None,
    filter_id: str = "all",
    filter_menu_open: bool = False,
    filter_menu_selected_index: int = 0,
    filter_focused: bool = False,
    full_screen: bool = False,
) -> MyGamesPanelLayout:
    """Full-area overlay; loads header art via load_header_fn(library_key, path). Returns layout for hit-testing."""
    sw, sh = screen.get_size()
    layout = compute_my_games_panel_layout(
        sw,
        sh,
        filter_menu_open=filter_menu_open,
        full_screen=full_screen,
    )
    scale = layout.scale
    margin_x = layout.margin_x
    content_top = layout.content_top
    colors = theme["colors"]
    font_f = theme["typography"]["font_family"]

    bg = pygame.Color(46, 46, 48)
    _blit_my_games_popup_background(screen, sw, sh, content_top, full_screen, bg)

    title_font = _sys_font(font_f, int(34 * scale))
    small_font = _sys_font(font_f, int(18 * scale))
    tiny_font = _sys_font(font_f, int(14 * scale))
    tile_title_font = _sys_font(font_f, int(15 * scale))

    filter_font = _sys_font(font_f, int(17 * scale))
    scaled_cache = scaled_art_cache if scaled_art_cache is not None else {}
    fy = content_top + int(12 * scale)
    show1 = filter_font.render("show me", True, pygame.Color(colors["text_dim"]))
    filter_sub = filter_label_for_id(filter_id)
    show2 = tiny_font.render(filter_sub, True, pygame.Color(160, 164, 172))
    screen.blit(show1, (margin_x, fy))
    screen.blit(show2, (margin_x, layout.filter_line2_y))
    if filter_menu_open or filter_focused:
        fr = layout.filter_button_rect.inflate(6, 4)
        border = pygame.Color(72, 120, 196) if filter_menu_open else pygame.Color(100, 108, 120)
        pygame.draw.rect(screen, border, fr, width=2, border_radius=3)

    sort_x = margin_x + max(160, int(180 * scale))
    so1 = filter_font.render("sort", True, pygame.Color(colors["text_dim"]))
    so2 = tiny_font.render("titles", True, pygame.Color(160, 164, 172))
    screen.blit(so1, (sort_x, fy))
    screen.blit(so2, (sort_x, fy + so1.get_height()))

    header_title = title_font.render("My Games", True, pygame.Color(255, 255, 255))
    n = len(games)
    sel_display = min(selected_index + 1, max(1, n)) if n else 0
    counter = small_font.render(f"{sel_display} of {n}", True, pygame.Color(180, 184, 190))
    screen.blit(header_title, (sw - margin_x - header_title.get_width(), fy))
    screen.blit(counter, (sw - margin_x - counter.get_width(), fy + header_title.get_height() + 4))

    strip_top = layout.strip_top
    strip_h = sh - strip_top - layout.footer_reserve
    tile_h = layout.tile_h
    tile_w = layout.tile_w
    gap = layout.gap
    pitch = layout.pitch
    viewport_w = sw - 2 * margin_x

    if filter_menu_open:
        dd = layout.dropdown_panel_rect
        pygame.draw.rect(screen, pygame.Color(36, 38, 44), dd, border_radius=4)
        pygame.draw.rect(screen, pygame.Color(88, 92, 102), dd, width=1, border_radius=4)
        menu_font = _sys_font(font_f, int(16 * scale))
        for idx, rect in enumerate(layout.dropdown_item_rects):
            label = MY_GAMES_FILTERS[idx][1]
            is_sel = idx == filter_menu_selected_index
            if is_sel:
                pygame.draw.rect(screen, pygame.Color(72, 120, 196), rect.inflate(2, 2), border_radius=3)
            col = pygame.Color(235, 237, 242) if is_sel else pygame.Color(190, 194, 202)
            txt = menu_font.render(label, True, col)
            screen.blit(txt, (rect.x + 8, rect.y + (rect.h - txt.get_height()) // 2))

    if n == 0:
        msg = small_font.render(
            "No games match this filter.",
            True,
            pygame.Color(200, 200, 205),
        )
        screen.blit(msg, (margin_x, strip_top + strip_h // 2))
        _draw_footer_hints(screen, margin_x, sh, scale, tiny_font)
        return layout

    si = max(0, min(selected_index, n - 1))
    total_w = n * pitch - gap
    scroll = max(0, min(si * pitch + tile_w // 2 - viewport_w // 2, max(0, total_w - viewport_w)))

    sel_scale = 1.08
    for i in range(n):
        x = margin_x + i * pitch - scroll
        if x + tile_w < margin_x or x > sw - margin_x:
            continue
        is_sel = i == si
        tw = int(tile_w * (sel_scale if is_sel else 1.0))
        th = int(tile_h * (sel_scale if is_sel else 1.0))
        ty_offset = int((tile_h - th) * 0.35) if is_sel else 0
        rect = pygame.Rect(x, strip_top + ty_offset, tw, th)

        game = games[i]
        library_key = row_library_key(game)
        if art_cache.get(library_key) is None:
            load_header_fn(library_key, game.get("header_image"))

        store = row_store(game)
        banner_h = max(22, int(24 * scale))
        if store == "epic":
            ban_bg = pygame.Color(54, 58, 72) if not is_sel else pygame.Color(230, 232, 240)
            ban_fg = pygame.Color(230, 232, 255) if not is_sel else pygame.Color(60, 64, 82)
            ban_label = "EPIC"
            plat_text = "+ Epic Games"
        elif store == "ea":
            ban_bg = pygame.Color(42, 46, 54) if not is_sel else pygame.Color(236, 238, 242)
            ban_fg = pygame.Color(255, 235, 220) if not is_sel else pygame.Color(72, 52, 38)
            ban_label = "EA"
            plat_text = "+ EA app"
        elif store == "rockstar":
            ban_bg = pygame.Color(36, 32, 28) if not is_sel else pygame.Color(242, 238, 228)
            ban_fg = pygame.Color(240, 200, 72) if not is_sel else pygame.Color(52, 46, 38)
            ban_label = "R*"
            plat_text = "+ Rockstar"
        elif store == "steam":
            ban_bg = pygame.Color(210, 92, 58) if not is_sel else pygame.Color(245, 245, 248)
            ban_fg = pygame.Color(255, 255, 255) if not is_sel else pygame.Color(90, 94, 98)
            ban_label = "STEAM"
            plat_text = "+ Steam"
        else:
            ban_bg = pygame.Color(120, 122, 128) if not is_sel else pygame.Color(245, 245, 248)
            ban_fg = pygame.Color(255, 255, 255) if not is_sel else pygame.Color(70, 74, 78)
            ban_label = "GAME"
            plat_text = "+ Library"
        pygame.draw.rect(screen, ban_bg, pygame.Rect(rect.x, rect.y, rect.w, banner_h))
        banner_key = (store, is_sel)
        banner_cached = _STORE_BANNER_CACHE.get(banner_key)
        if banner_cached is None:
            ban_txt = tiny_font.render(ban_label, True, ban_fg)
            plat = tiny_font.render(plat_text, True, pygame.Color(80, 84, 90))
            _STORE_BANNER_CACHE[banner_key] = (ban_txt, plat)
        else:
            ban_txt, plat = banner_cached

        gtitle = game["title"]
        if len(gtitle) > 28:
            gtitle = gtitle[:25] + "…"
        name_s = _TILE_TITLE_CACHE.get(gtitle)
        if name_s is None:
            name_s = tile_title_font.render(gtitle, True, pygame.Color(28, 30, 34))
            _TILE_TITLE_CACHE[gtitle] = name_s
        ach, gs = _stat_placeholders(tiny_font)
        screen.blit(ban_txt, (rect.x + 8, rect.y + (banner_h - ban_txt.get_height()) // 2))

        foot_pad_x = int(8 * scale)
        foot_pad_top = int(8 * scale)
        foot_pad_bottom = int(8 * scale)
        gap_label = int(6 * scale)
        stat_row_h = max(ach.get_height(), gs.get_height())
        min_footer_h = (
            foot_pad_top + name_s.get_height() + gap_label + stat_row_h + gap_label + plat.get_height() + foot_pad_bottom
        )
        footer_h = int(max(min_footer_h, 72 * scale, rect.h * 0.2))
        foot_top = rect.bottom - footer_h

        art_rect = pygame.Rect(rect.x, rect.y + banner_h, rect.w, rect.h - banner_h - footer_h)
        scaled = scaled_tile_art(scaled_cache, art_cache, library_key, art_rect.w, art_rect.h)
        if scaled is not None:
            screen.blit(scaled, art_rect.topleft)
        else:
            pygame.draw.rect(screen, pygame.Color(120, 122, 128), art_rect)
            _draw_pad_glyph(screen, art_rect)

        pygame.draw.rect(screen, pygame.Color(248, 248, 250), pygame.Rect(rect.x, foot_top, rect.w, rect.bottom - foot_top))

        fy_line = foot_top + foot_pad_top
        screen.blit(name_s, (rect.x + foot_pad_x, fy_line))
        fy_line += name_s.get_height() + gap_label
        screen.blit(ach, (rect.x + foot_pad_x, fy_line))
        screen.blit(gs, (rect.x + foot_pad_x + ach.get_width() + int(10 * scale), fy_line))
        fy_line += ach.get_height() + gap_label
        screen.blit(plat, (rect.x + foot_pad_x, fy_line))

        _draw_mini_pad(screen, rect.right - int(28 * scale), rect.bottom - int(22 * scale), scale)

        if is_sel:
            pygame.draw.rect(screen, pygame.Color(255, 255, 255), rect.inflate(6, 6), width=3, border_radius=2)

    _draw_footer_hints(screen, margin_x, sh, scale, tiny_font)
    return layout


def hit_test_my_games_filter_button(mx: int, my: int, layout: MyGamesPanelLayout) -> bool:
    return layout.filter_button_rect.collidepoint(mx, my)


def hit_test_my_games_filter_dropdown(mx: int, my: int, layout: MyGamesPanelLayout) -> int | None:
    if not layout.dropdown_item_rects:
        return None
    for idx, rect in enumerate(layout.dropdown_item_rects):
        if rect.collidepoint(mx, my):
            return idx
    return None


def hit_test_my_games_tile(
    mx: int,
    my: int,
    panel_w: int,
    panel_h: int,
    games_count: int,
    selected_index: int,
    *,
    full_screen: bool = True,
) -> int | None:
    """Coordinates must be relative to the My Games panel surface (0..panel_w)."""
    if games_count <= 0:
        return None
    layout = compute_my_games_panel_layout(
        panel_w,
        panel_h,
        filter_menu_open=False,
        full_screen=full_screen,
    )
    margin_x = layout.margin_x
    strip_top = layout.strip_top
    tile_w = layout.tile_w
    tile_h = layout.tile_h
    gap = layout.gap
    pitch = layout.pitch
    viewport_w = panel_w - 2 * margin_x
    si = max(0, min(selected_index, games_count - 1))
    total_w = games_count * pitch - gap
    scroll = max(0, min(si * pitch + tile_w // 2 - viewport_w // 2, max(0, total_w - viewport_w)))

    for i in range(games_count):
        x = margin_x + i * pitch - scroll
        rect = pygame.Rect(x, strip_top, tile_w, tile_h)
        if rect.collidepoint(mx, my):
            return i
    return None


def _draw_pad_glyph(screen: pygame.Surface, rect: pygame.Rect) -> None:
    cx, cy = rect.center
    body = pygame.Rect(0, 0, int(rect.w * 0.36), int(rect.h * 0.22))
    body.center = (cx, cy)
    pygame.draw.rect(screen, pygame.Color(230, 232, 236), body, border_radius=5)
    pygame.draw.circle(screen, pygame.Color(230, 232, 236), (body.left + int(body.w * 0.28), cy), int(rect.h * 0.06))
    pygame.draw.circle(screen, pygame.Color(230, 232, 236), (body.right - int(body.w * 0.28), cy), int(rect.h * 0.06))


def _draw_mini_pad(screen: pygame.Surface, x: int, y: int, scale: float) -> None:
    s = int(18 * scale)
    pygame.draw.ellipse(screen, pygame.Color(72, 76, 82), pygame.Rect(x, y, s, int(s * 0.55)))


def _draw_footer_hints(
    screen: pygame.Surface,
    margin_x: int,
    sh: int,
    scale: float,
    font: pygame.font.Font,
) -> None:
    scale_key = int(scale * 100)
    cached = _FOOTER_HINTS_CACHE.get(scale_key)
    if cached is not None:
        screen.blit(cached, (margin_x, sh - cached.get_height()))
        return

    hy = int(26 * scale)
    layer_w = int(520 * scale)
    layer_h = hy + font.get_height()
    layer = pygame.Surface((layer_w, layer_h), pygame.SRCALPHA)
    draw_y = 0
    hx = int(28 * scale)
    radius = int(10 * scale)
    circle_cx = 10
    text_after_circle = circle_cx + radius + int(14 * scale)
    a_center = (hx + circle_cx, draw_y + hy)
    pygame.draw.circle(layer, pygame.Color(72, 168, 52), a_center, radius)
    a_label = font.render("A", True, (255, 255, 255))
    layer.blit(a_label, a_label.get_rect(center=a_center).topleft)
    launch = font.render("Launch", True, pygame.Color(220, 222, 228))
    layer.blit(launch, (hx + text_after_circle, draw_y + hy - launch.get_height() // 2))

    hx += int(128 * scale)
    b_center = (hx + circle_cx, draw_y + hy)
    pygame.draw.circle(layer, pygame.Color(196, 62, 62), b_center, radius)
    b_label = font.render("B", True, (255, 255, 255))
    layer.blit(b_label, b_label.get_rect(center=b_center).topleft)
    back = font.render("Back", True, pygame.Color(220, 222, 228))
    layer.blit(back, (hx + text_after_circle, draw_y + hy - back.get_height() // 2))

    hx += int(118 * scale)
    x_center = (hx + circle_cx, draw_y + hy)
    pygame.draw.circle(layer, pygame.Color(52, 106, 196), x_center, radius)
    x_label = font.render("X", True, (255, 255, 255))
    layer.blit(x_label, x_label.get_rect(center=x_center).topleft)
    details = font.render("Game Details", True, pygame.Color(220, 222, 228))
    layer.blit(details, (hx + text_after_circle, draw_y + hy - details.get_height() // 2))

    _FOOTER_HINTS_CACHE[scale_key] = layer
    screen.blit(layer, (margin_x, sh - layer_h))
