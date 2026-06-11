"""
Games hub layout (reference: games.png).
Left: 2×3 green tiles. Right: large hero on top, Forza + Cobalt on bottom.
"""

from __future__ import annotations

from typing import Any, Callable

import pygame

from themes.xbox360.page_text import page_title

# Slot order: 0-5 left grid (col0 then col1 per row), 6 hero, 7 Forza, 8 Cobalt
_GAMES_NAV: dict[int, dict[str, int | None]] = {
    0: {"left": None, "right": 1, "up": None, "down": 2},
    1: {"left": 0, "right": 6, "up": None, "down": 3},
    2: {"left": None, "right": 3, "up": 0, "down": 4},
    3: {"left": 2, "right": 6, "up": 1, "down": 5},
    4: {"left": None, "right": 5, "up": 2, "down": 7},
    5: {"left": 4, "right": 8, "up": 3, "down": None},
    6: {"left": 3, "right": None, "up": None, "down": 7},
    7: {"left": 4, "right": 8, "up": 6, "down": None},
    8: {"left": 7, "right": None, "up": 6, "down": None},
}

SLOT_LABELS = [
    "My Games",
    "Add Ons",
    "Browse Games",
    "Demos",
    "Search Games",
    "A - Z",
    "Minecraft: Story Mode",
    "Forza Horizon 2",
    "Cobalt",
]

# Placeholder tints for featured artwork (R,G,B)
FEATURE_ACCENTS = [
    (88, 58, 42),  # Minecraft / warm
    (180, 120, 35),  # Forza / golden
    (38, 82, 140),  # Cobalt / blue
]


def games_slot_count() -> int:
    return len(SLOT_LABELS)


def games_navigate(current: int, direction: str) -> int:
    if not 0 <= current < len(SLOT_LABELS):
        return 0
    nxt = _GAMES_NAV.get(current, {}).get(direction)
    return current if nxt is None else int(nxt)


def _lerp_color(a: pygame.Color, b: pygame.Color, t: float) -> pygame.Color:
    t = max(0.0, min(1.0, t))
    return pygame.Color(
        int(a.r + (b.r - a.r) * t),
        int(a.g + (b.g - a.g) * t),
        int(a.b + (b.b - a.b) * t),
    )


def _fill_vertical_gradient(
    surface: pygame.Surface, rect: pygame.Rect, top: pygame.Color, bottom: pygame.Color
) -> None:
    if rect.h <= 0:
        return
    for y in range(rect.h):
        t = y / max(1, rect.h - 1)
        c = _lerp_color(top, bottom, t)
        pygame.draw.line(surface, c, (rect.x, rect.y + y), (rect.right - 1, rect.y + y))


def build_slot_rects(screen_w: int, screen_h: int) -> list[pygame.Rect]:
    scale = min(screen_w / 1600.0, screen_h / 900.0)
    scale = max(0.65, scale)

    content_top = int(54 * scale + 56 * scale + 12 * scale)
    margin_x = int(48 * scale)
    gap = int(10 * scale)

    inner_w = screen_w - 2 * margin_x
    grid_h = max(160, screen_h - content_top - int(28 * scale))

    # Left block: 2 cols × 3 rows — reference proportions (~46% width)
    left_block_w = int(inner_w * 0.46)
    tile_w = (left_block_w - gap) // 2
    tile_h = (grid_h - 2 * gap) // 3

    x0 = margin_x
    x1 = x0 + tile_w + gap
    grid_top = content_top + gap

    rects: list[pygame.Rect] = []
    # Column-major slot order to match SLOT_LABELS 0-5: (0,0),(1,0),(0,1),(1,1),(0,2),(1,2)
    for row in range(3):
        rects.append(pygame.Rect(x0, grid_top + row * (tile_h + gap), tile_w, tile_h))
        rects.append(pygame.Rect(x1, grid_top + row * (tile_h + gap), tile_w, tile_h))

    # Right: hero full height of top two rows; bottom row split
    rx = x1 + tile_w + gap + int(8 * scale)
    rw = max(int(120 * scale), inner_w - (rx - margin_x))
    hero_h = 2 * tile_h + gap
    rects.append(pygame.Rect(rx, grid_top, rw, hero_h))

    bottom_y = grid_top + hero_h + gap
    bottom_h = max(int(48 * scale), grid_h - hero_h - gap)
    half = (rw - gap) // 2
    rects.append(pygame.Rect(rx, bottom_y, half, bottom_h))
    rects.append(pygame.Rect(rx + half + gap, bottom_y, rw - half - gap, bottom_h))

    return rects


def _draw_icon_controller(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    cx, cy = rect.centerx, rect.centery - int(rect.h * 0.08)
    body = pygame.Rect(0, 0, int(rect.w * 0.42), int(rect.h * 0.22))
    body.center = (cx, cy)
    pygame.draw.rect(surf, color, body, border_radius=6)
    pygame.draw.circle(surf, color, (body.left + int(body.w * 0.28), cy), int(rect.h * 0.055))
    pygame.draw.circle(surf, color, (body.right - int(body.w * 0.28), cy), int(rect.h * 0.055))


def _draw_icon_addons(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    _draw_icon_controller(surf, rect, color)
    cx = rect.centerx + int(rect.w * 0.22)
    cy = rect.centery - int(rect.h * 0.14)
    pygame.draw.line(surf, color, (cx - 6, cy), (cx + 6, cy), width=max(2, int(rect.h * 0.04)))
    pygame.draw.line(surf, color, (cx, cy - 6), (cx, cy + 6), width=max(2, int(rect.h * 0.04)))


def _draw_icon_bag(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    cx, cy = rect.centerx, rect.centery - int(rect.h * 0.08)
    w, h = int(rect.w * 0.28), int(rect.h * 0.22)
    points = [
        (cx - w // 2, cy + h // 4),
        (cx - w // 2, cy - h // 4),
        (cx - w // 4, cy - h // 2),
        (cx + w // 4, cy - h // 2),
        (cx + w // 2, cy - h // 4),
        (cx + w // 2, cy + h // 4),
    ]
    pygame.draw.polygon(surf, color, points)
    pygame.draw.line(
        surf,
        color,
        (cx - w // 2, cy - h // 4),
        (cx + w // 2, cy - h // 4),
        width=max(2, int(rect.h * 0.04)),
    )


def _draw_icon_search(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    cx, cy = rect.centerx - int(rect.w * 0.04), rect.centery - int(rect.h * 0.1)
    r = int(min(rect.w, rect.h) * 0.12)
    pygame.draw.circle(surf, color, (cx, cy), r, width=max(2, int(rect.h * 0.05)))
    pygame.draw.line(
        surf,
        color,
        (cx + int(r * 0.65), cy + int(r * 0.65)),
        (cx + int(r * 1.8), cy + int(r * 1.8)),
        width=max(3, int(rect.h * 0.06)),
    )


def _draw_icon_demos(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    cx, cy = rect.centerx, rect.centery - int(rect.h * 0.08)
    bw = int(rect.w * 0.44)
    bh = int(rect.h * 0.22)
    outline = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)
    dash = max(4, int(rect.h * 0.03))
    for x in range(outline.left, outline.right, dash * 2):
        pygame.draw.line(surf, color, (x, outline.top), (min(x + dash, outline.right), outline.top), 2)
        pygame.draw.line(surf, color, (x, outline.bottom), (min(x + dash, outline.right), outline.bottom), 2)
    for y in range(outline.top, outline.bottom, dash * 2):
        pygame.draw.line(surf, color, (outline.left, y), (outline.left, min(y + dash, outline.bottom)), 2)
        pygame.draw.line(surf, color, (outline.right, y), (outline.right, min(y + dash, outline.bottom)), 2)


def _draw_icon_list_az(surf: pygame.Surface, rect: pygame.Rect, color: pygame.Color) -> None:
    lx = rect.centerx - int(rect.w * 0.14)
    ly = rect.centery - int(rect.h * 0.1)
    line_h = max(3, int(rect.h * 0.055))
    gap_y = int(rect.h * 0.07)
    dot_r = max(2, int(rect.h * 0.025))
    for i in range(3):
        y = ly + i * gap_y
        pygame.draw.circle(surf, color, (lx, y + line_h // 2), dot_r)
        pygame.draw.line(surf, color, (lx + 10, y + line_h // 2), (lx + int(rect.w * 0.22), y + line_h // 2), 2)


def _draw_green_tile(
    surf: pygame.Surface,
    rect: pygame.Rect,
    title: str,
    font: pygame.font.Font,
    selected: bool,
    icon_draw: Callable[[pygame.Surface, pygame.Rect, pygame.Color], None],
    scale: float,
) -> None:
    green_dim = pygame.Color(72, 168, 52)
    green_hi = pygame.Color(106, 218, 68)
    white = pygame.Color(255, 255, 255)

    fill = green_hi if selected else green_dim
    pygame.draw.rect(surf, fill, rect, border_radius=3)
    icon_draw(surf, rect, white)
    lab = font.render(page_title(title), True, white)
    surf.blit(lab, (rect.x + int(10 * scale), rect.bottom - lab.get_height() - int(8 * scale)))
    if selected:
        border_w = max(2, int(3 * scale))
        pygame.draw.rect(surf, white, rect, width=border_w, border_radius=3)
        inner = rect.inflate(-border_w * 2, -border_w * 2)
        pygame.draw.rect(surf, pygame.Color(180, 240, 140), inner, width=1, border_radius=2)


def _draw_featured_tile(
    surf: pygame.Surface,
    rect: pygame.Rect,
    title: str,
    font: pygame.font.Font,
    accent: tuple[int, int, int],
    selected: bool,
) -> None:
    top_c = pygame.Color(accent[0] + 25, accent[1] + 25, accent[2] + 25)
    bot_c = pygame.Color(max(0, accent[0] - 30), max(0, accent[1] - 30), max(0, accent[2] - 30))
    _fill_vertical_gradient(surf, rect, top_c, bot_c)
    bar_h = max(32, int(rect.h * 0.18))
    bar = pygame.Rect(rect.x, rect.bottom - bar_h, rect.w, bar_h)
    overlay = pygame.Surface((bar.w, bar.h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 185))
    surf.blit(overlay, bar.topleft)
    label = font.render(page_title(title), True, pygame.Color(255, 255, 255))
    surf.blit(label, (rect.x + 10, bar.y + (bar_h - label.get_height()) // 2))
    if selected:
        pygame.draw.rect(surf, pygame.Color(255, 255, 255), rect, width=3, border_radius=2)


def draw_games_panel(
    screen: pygame.Surface,
    theme: dict[str, Any],
    selected_index: int,
    slot_rects: list[pygame.Rect],
) -> None:
    sw, sh = screen.get_size()
    scale = min(sw / 1600.0, sh / 900.0)
    scale = max(0.65, scale)

    font_family = theme["typography"]["font_family"]
    label_px = max(15, int(17 * scale))
    featured_px = max(14, int(15 * scale))
    font_label = pygame.font.SysFont(font_family, label_px)
    font_feat = pygame.font.SysFont(font_family, featured_px)

    green_icons = [
        _draw_icon_controller,
        _draw_icon_addons,
        _draw_icon_bag,
        _draw_icon_demos,
        _draw_icon_search,
        _draw_icon_list_az,
    ]

    for idx, rect in enumerate(slot_rects):
        if idx >= len(SLOT_LABELS):
            break
        sel = idx == selected_index
        title = SLOT_LABELS[idx]
        if idx <= 5:
            _draw_green_tile(screen, rect, title, font_label, sel, green_icons[idx], scale)
        else:
            accent = FEATURE_ACCENTS[idx - 6]
            _draw_featured_tile(screen, rect, title, font_feat, accent, sel)
