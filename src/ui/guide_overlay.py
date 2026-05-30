from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any

import pygame

from ui.page_text import page_title

# Xbox 360 Metro Guide (2011) — from reference UI
_C_DIM = (0, 0, 0, 165)
_C_TAB_IDLE_TOP = (118, 142, 162)
_C_TAB_IDLE_BOT = (96, 118, 138)
_C_TAB_ACTIVE_TOP = (188, 204, 218)
_C_TAB_ACTIVE_BOT = (162, 180, 198)
_C_CONTENT = (236, 240, 244)
_C_CONTENT_LINE = (210, 218, 226)
_C_ROW_TEXT = (48, 56, 62)
_C_SELECT = (94, 168, 38)
_C_SELECT_TOP = (118, 198, 58)
_C_HEADER_TEXT = (255, 255, 255)

_BTN_COLORS = {
    "A": (94, 168, 38),
    "B": (198, 48, 48),
    "X": (58, 118, 198),
    "Y": (208, 188, 48),
}


@dataclass(frozen=True)
class GuideMenuItem:
    label: str
    action: str
    trailing_icon: str | None = None


@dataclass(frozen=True)
class GuideSection:
    tab_id: str
    label: str
    side: str  # "left" | "right"
    items: tuple[GuideMenuItem, ...]


GUIDE_SECTIONS: tuple[GuideSection, ...] = (
    GuideSection(
        "games_apps",
        "Games & Apps",
        "left",
        (
            GuideMenuItem("Games", "hub:Games"),
            GuideMenuItem("My Games", "my_games"),
            GuideMenuItem("Apps", "hub:Apps"),
            GuideMenuItem("Recent", "noop"),
        ),
    ),
    GuideSection(
        "player",
        "Player1",
        "left",
        (
            GuideMenuItem("Xbox Home", "close"),
            GuideMenuItem("Join Xbox Live", "noop"),
            GuideMenuItem("Open Tray", "noop", "disc"),
        ),
    ),
    GuideSection(
        "media",
        "Media",
        "right",
        (
            GuideMenuItem("Music", "noop"),
            GuideMenuItem("Video", "noop"),
            GuideMenuItem("Netflix", "noop"),
        ),
    ),
    GuideSection(
        "settings",
        "Settings",
        "right",
        (
            GuideMenuItem("Preferences", "hub:Settings"),
            GuideMenuItem("Display", "switch_display"),
            GuideMenuItem("Power", "power_menu"),
            GuideMenuItem("Sign Out", "exit_app"),
        ),
    ),
)

DEFAULT_TAB_INDEX = 1  # Player1


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> pygame.Surface:
    w, h = size
    surf = pygame.Surface((w, h))
    for y in range(h):
        t = y / max(1, h - 1)
        color = (_lerp(top[0], bottom[0], t), _lerp(top[1], bottom[1], t), _lerp(top[2], bottom[2], t))
        pygame.draw.line(surf, color, (0, y), (w, y))
    return surf


def _content_texture(size: tuple[int, int]) -> pygame.Surface:
    w, h = size
    surf = pygame.Surface((w, h))
    surf.fill(_C_CONTENT)
    for y in range(0, h, 3):
        pygame.draw.line(surf, (228, 232, 236), (0, y), (w, y))
    return surf


def _vertical_text(font: pygame.font.Font, text: str, color: pygame.Color) -> pygame.Surface:
    line = font.render(text, True, color)
    return pygame.transform.rotate(line, 90)


class GuideOverlay:
    """Xbox 360 Metro Guide — centered popup, side tabs, green list selection."""

    def __init__(
        self,
        theme: dict[str, Any],
        gamertag: str | None = None,
        gamerpic_path: str | Path | None = None,
    ) -> None:
        self.theme = theme
        self.gamertag = (gamertag or "Player1").strip() or "Player1"
        self._gamerpic_path: Path | None = None
        self._gamerpic_surface: pygame.Surface | None = None
        if gamerpic_path:
            self.set_gamerpic_path(gamerpic_path)
        self.open = False
        self.transition_progress = 0.0
        self.transition_target = 0.0
        self.transition_duration_s = 0.1
        self.tab_index = DEFAULT_TAB_INDEX
        self.item_index = 0
        self._tab_hitboxes: list[tuple[int, pygame.Rect]] = []
        self._item_rects: list[pygame.Rect] = []
        self._content_rect = pygame.Rect(0, 0, 0, 0)
        self._content_tex_cache: pygame.Surface | None = None
        self._content_tex_size: tuple[int, int] | None = None

    @property
    def visible(self) -> bool:
        return self.open or self.transition_progress > 0.0

    def set_profile(self, gamertag: str, gamerpic_path: str | Path | None = None) -> None:
        self.gamertag = (gamertag or "Player1").strip() or "Player1"
        self.set_gamerpic_path(gamerpic_path)

    def set_gamerpic_path(self, path: str | Path | None) -> None:
        self._gamerpic_path = Path(path) if path else None
        self._gamerpic_surface = None

    def _player_tab_label(self) -> str:
        name = (self.gamertag or "Player1").strip() or "Player1"
        return name[:15] if len(name) > 15 else name

    def _tab_label(self, section_index: int) -> str:
        if GUIDE_SECTIONS[section_index].tab_id == "player":
            return self._player_tab_label()
        return page_title(GUIDE_SECTIONS[section_index].label)

    def _gamerpic_image(self) -> pygame.Surface | None:
        if self._gamerpic_path is None or not self._gamerpic_path.is_file():
            return None
        if self._gamerpic_surface is None:
            try:
                self._gamerpic_surface = pygame.image.load(str(self._gamerpic_path)).convert_alpha()
            except (pygame.error, FileNotFoundError):
                self._gamerpic_surface = None
        return self._gamerpic_surface

    def toggle(self) -> None:
        if self.open:
            self.close()
        else:
            self.open = True
            self.transition_target = 1.0
            self.tab_index = DEFAULT_TAB_INDEX
            self.item_index = 0

    def close(self) -> None:
        self.open = False
        self.transition_target = 0.0

    def update(self, dt: float) -> None:
        if self.transition_progress == self.transition_target:
            return
        step = dt / max(0.001, self.transition_duration_s)
        if self.transition_progress < self.transition_target:
            self.transition_progress = min(self.transition_target, self.transition_progress + step)
        else:
            self.transition_progress = max(self.transition_target, self.transition_progress - step)

    def _items(self) -> tuple[GuideMenuItem, ...]:
        return GUIDE_SECTIONS[self.tab_index].items

    def handle_action(self, action: str) -> str | None:
        if action == "TOGGLE_GUIDE":
            self.toggle()
            return None
        if not self.visible:
            return None

        if action == "BACK":
            self.close()
            return None
        if action == "GUIDE_SIGN_OUT":
            self.close()
            return "exit_app"
        if action == "GUIDE_Y":
            self.close()
            return "hub:Home"
        if action in ("HUB_PREV", "MOVE_LEFT"):
            self.tab_index = (self.tab_index - 1) % len(GUIDE_SECTIONS)
            self.item_index = 0
            return None
        if action in ("HUB_NEXT", "MOVE_RIGHT"):
            self.tab_index = (self.tab_index + 1) % len(GUIDE_SECTIONS)
            self.item_index = 0
            return None

        items = self._items()
        if action == "MOVE_UP":
            self.item_index = (self.item_index - 1) % len(items)
        elif action == "MOVE_DOWN":
            self.item_index = (self.item_index + 1) % len(items)
        elif action == "SELECT":
            item = items[self.item_index]
            if item.action == "close":
                self.close()
                return None
            if item.action == "noop":
                return "status:Not available yet."
            self.close()
            return item.action
        return None

    def apply_mouse_hover(self, pos: tuple[int, int]) -> None:
        for tab_idx, rect in self._tab_hitboxes:
            if rect.collidepoint(pos):
                self.tab_index = tab_idx
                self.item_index = 0
                return
        for idx, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                self.item_index = idx

    def apply_mouse_click(self, pos: tuple[int, int]) -> str | None:
        self.apply_mouse_hover(pos)
        for rect in self._item_rects:
            if rect.collidepoint(pos):
                return self.handle_action("SELECT")
        return None

    def _guide_config(self) -> dict[str, Any]:
        cfg = self.theme.get("guide_panel")
        return cfg if isinstance(cfg, dict) else {}

    def _ui_scale(self, screen_w: int, screen_h: int) -> float:
        cfg = self._guide_config()
        base_w = int(cfg.get("base_width", 1920))
        base_h = int(cfg.get("base_height", 1080))
        scale = min(screen_w / max(1, base_w), screen_h / max(1, base_h))
        return max(float(cfg.get("min_scale", 0.8)), scale)

    def _metrics(self, screen_w: int, screen_h: int, mix: float) -> dict[str, Any]:
        cfg = self._guide_config()
        ui = self._ui_scale(screen_w, screen_h) * float(cfg.get("panel_scale", 1.0))
        anim = 0.9 + 0.1 * mix

        def scaled(key: str, default: int | float) -> int:
            return max(1, int(float(cfg.get(key, default)) * ui))

        panel_w = int(scaled("panel_width", 1480) * anim)
        panel_h = int(scaled("panel_height", 720) * anim)
        panel_w = min(panel_w, screen_w - scaled("screen_margin_x", 24))
        panel_h = min(panel_h, screen_h - scaled("screen_margin_y", 80))
        return {
            "ui_scale": ui,
            "panel_w": panel_w,
            "panel_h": panel_h,
            "header_h": scaled("header_height", 42),
            "tab_w": scaled("tab_width", 40),
            "row_h": scaled("row_height", 44),
            "footer_btn_r": scaled("footer_button_radius", 9),
            "footer_font": scaled("footer_font_size", 15),
            "footer_letter": scaled("footer_btn_letter_size", 12),
            "title_font": scaled("title_font_size", 24),
            "item_font": scaled("item_font_size", 26),
            "tab_font": scaled("tab_font_size", 15),
            "time_font": scaled("time_font_size", 19),
            "footer_gap": scaled("footer_gap_below", 10),
            "offset_y": int(screen_h * float(cfg.get("vertical_offset_ratio", 0.01))),
            "pad": scaled("content_pad", 14),
            "row_pad": scaled("row_pad", 3),
            "ring_inset": scaled("header_ring_inset", 100),
            "orb_half": scaled("orb_half_size", 26),
            "orb_glow_pad": scaled("orb_glow_pad", 12),
            "header_content_gap": scaled("header_content_gap", 18),
        }

    def _layout(self, screen_w: int, screen_h: int, mix: float) -> dict[str, Any]:
        m = self._metrics(screen_w, screen_h, mix)
        block_w = m["panel_w"]
        block_h = m["panel_h"]
        block_x = (screen_w - block_w) // 2
        block_y = (screen_h - block_h) // 2 - m["offset_y"]
        header_h = m["header_h"]
        header_gap = m["header_content_gap"]
        tab_w = m["tab_w"]
        body_h = block_h - header_h - header_gap
        left_tabs = [i for i, s in enumerate(GUIDE_SECTIONS) if s.side == "left"]
        right_tabs = [i for i, s in enumerate(GUIDE_SECTIONS) if s.side == "right"]
        left_w = tab_w * len(left_tabs)
        right_w = tab_w * len(right_tabs)
        content_x = block_x + left_w
        content_w = block_w - left_w - right_w
        content_y = block_y + header_h + header_gap
        content_rect = pygame.Rect(content_x, content_y, content_w, body_h)
        tab_rects: list[pygame.Rect] = []
        x = block_x
        for idx in left_tabs:
            tab_rects.append(pygame.Rect(x, content_y, tab_w, body_h))
            x += tab_w
        x = content_x + content_w
        for idx in right_tabs:
            tab_rects.append(pygame.Rect(x, content_y, tab_w, body_h))
            x += tab_w
        return {
            "block": pygame.Rect(block_x, block_y, block_w, block_h),
            "header_h": header_h,
            "tab_w": tab_w,
            "content": content_rect,
            "tab_rects": tab_rects,
            "left_tabs": left_tabs,
            "right_tabs": right_tabs,
            "metrics": m,
        }

    def _draw_header_emblem(
        self,
        screen: pygame.Surface,
        center: tuple[int, int],
        ui_scale: float,
        orb_half: int,
        orb_glow_pad: int,
    ) -> None:
        pic = self._gamerpic_image()
        if pic is not None:
            self._draw_gamerpic_emblem(screen, center, ui_scale, orb_half, orb_glow_pad, pic)
            return
        self._draw_xbox_orb(screen, center, ui_scale, orb_half, orb_glow_pad)

    @staticmethod
    def _draw_gamerpic_emblem(
        screen: pygame.Surface,
        center: tuple[int, int],
        ui_scale: float,
        orb_half: int,
        orb_glow_pad: int,
        image: pygame.Surface,
    ) -> None:
        cx, cy = center
        half = orb_half + orb_glow_pad // 2
        emblem = pygame.Rect(cx - half, cy - half, half * 2, half * 2)
        scaled = pygame.transform.smoothscale(image, emblem.size)
        screen.blit(scaled, emblem.topleft)

    @staticmethod
    def _draw_xbox_orb(
        screen: pygame.Surface,
        center: tuple[int, int],
        ui_scale: float,
        orb_half: int,
        orb_glow_pad: int,
    ) -> None:
        cx, cy = center
        half = orb_half
        glow_pad = orb_glow_pad
        emblem = pygame.Rect(cx - half, cy - half, half * 2, half * 2)
        glow_rect = emblem.inflate(glow_pad, glow_pad)
        glow = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(glow, (100, 200, 60, 110), glow.get_rect())
        screen.blit(glow, glow_rect.topleft)
        pygame.draw.rect(screen, pygame.Color(245, 248, 250), emblem)
        border = max(2, int(3 * ui_scale))
        pygame.draw.rect(screen, pygame.Color(88, 168, 42), emblem, border)
        arc_inset = max(5, int(7 * ui_scale))
        arc_rect = emblem.inflate(-arc_inset, -arc_inset)
        lw = max(2, int(3 * ui_scale))
        pygame.draw.arc(screen, pygame.Color(72, 150, 36), arc_rect, 0.5, 2.6, lw)
        pygame.draw.arc(screen, pygame.Color(72, 150, 36), arc_rect, 3.6, 5.8, lw)

    @staticmethod
    def _draw_player_ring(
        screen: pygame.Surface,
        center: tuple[int, int],
        ui_scale: float,
        active_color: pygame.Color,
    ) -> None:
        """Ring of light: four arc chunks on a circle at diagonal corners; top-left = player 1."""
        cx, cy = center
        r = max(8, int(11 * ui_scale))
        lw = max(2, int(3 * ui_scale))
        idle = pygame.Color(128, 136, 144)
        chunk = 1.12
        # Chunk centers: top-left, top-right, bottom-left, bottom-right (pygame arc angles)
        chunks: tuple[tuple[float, bool], ...] = (
            (3 * math.pi / 4, True),  # top-left (player 1)
            (math.pi / 4, False),  # top-right
            (5 * math.pi / 4, False),  # bottom-left
            (7 * math.pi / 4, False),  # bottom-right
        )
        arc_box = (cx - r, cy - r, r * 2, r * 2)
        half = chunk / 2
        for angle, is_active in chunks:
            color = active_color if is_active else idle
            pygame.draw.arc(screen, color, arc_box, angle - half, angle + half, lw)

    @staticmethod
    def _draw_disc_icon(screen: pygame.Surface, center: tuple[int, int], ui_scale: float) -> None:
        cx, cy = center
        outer = max(7, int(9 * ui_scale))
        inner = max(2, int(3 * ui_scale))
        pygame.draw.circle(screen, pygame.Color(120, 130, 140), (cx, cy), outer, max(1, int(2 * ui_scale)))
        pygame.draw.circle(screen, pygame.Color(170, 180, 190), (cx, cy), inner)

    @staticmethod
    def _draw_footer_prompts(
        screen: pygame.Surface,
        y: int,
        center_x: int,
        font_family: str,
        metrics: dict[str, Any],
    ) -> None:
        ui = float(metrics["ui_scale"])
        footer_font = pygame.font.SysFont(font_family, metrics["footer_font"])
        btn_font = pygame.font.SysFont(font_family, metrics["footer_letter"], bold=True)
        r = metrics["footer_btn_r"]
        diameter = r * 2
        prompts = (("A", "Select"), ("B", "Back"), ("X", "Sign Out"), ("Y", "Xbox Home"))
        segments: list[tuple[pygame.Surface, pygame.Surface]] = []
        gap_after_btn = max(4, int(6 * ui))
        gap_between = max(16, int(22 * ui))
        total_w = 0
        for btn, label in prompts:
            circle = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
            pygame.draw.circle(circle, pygame.Color(*_BTN_COLORS[btn]), (r, r), r)
            letter = btn_font.render(btn, True, pygame.Color(255, 255, 255))
            circle.blit(letter, letter.get_rect(center=(r, r)).topleft)
            text = footer_font.render(label, True, pygame.Color(*_C_HEADER_TEXT))
            segments.append((circle, text))
            total_w += diameter + gap_after_btn + text.get_width() + gap_between
        total_w -= gap_between
        x = center_x - total_w // 2
        for circle, text in segments:
            screen.blit(circle, (x, y))
            x += diameter + gap_after_btn
            screen.blit(text, (x, y + max(0, (diameter - text.get_height()) // 2)))
            x += text.get_width() + gap_between

    def _content_surface(self, size: tuple[int, int]) -> pygame.Surface:
        if self._content_tex_cache is not None and self._content_tex_size == size:
            return self._content_tex_cache
        self._content_tex_cache = _content_texture(size)
        self._content_tex_size = size
        return self._content_tex_cache

    def draw(self, screen: pygame.Surface) -> None:
        mix = max(0.0, min(1.0, self.transition_progress))
        if mix <= 0.0:
            self._tab_hitboxes = []
            self._item_rects = []
            return

        sw, sh = screen.get_size()
        font_family = self.theme["typography"]["font_family"]
        layout = self._layout(sw, sh, mix)
        block: pygame.Rect = layout["block"]
        content: pygame.Rect = layout["content"]
        metrics: dict[str, Any] = layout["metrics"]
        ui_scale: float = metrics["ui_scale"]
        self._content_rect = content

        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, int(_C_DIM[3] * mix)))
        screen.blit(dim, (0, 0))

        header_h: int = layout["header_h"]
        tab_w: int = layout["tab_w"]
        pad = metrics["pad"]
        tab_font = pygame.font.SysFont(font_family, metrics["tab_font"], bold=True)
        title_font = pygame.font.SysFont(font_family, metrics["title_font"], bold=True)
        item_font = pygame.font.SysFont(font_family, metrics["item_font"])
        time_font = pygame.font.SysFont(font_family, metrics["time_font"])

        title = title_font.render(page_title("Xbox Guide"), True, pygame.Color(*_C_HEADER_TEXT))
        screen.blit(title, (block.x + pad, block.y + pad // 2))
        self._draw_header_emblem(
            screen,
            (block.centerx, block.y + header_h // 2),
            ui_scale,
            metrics["orb_half"],
            metrics["orb_glow_pad"],
        )

        ring_x = block.right - metrics["ring_inset"]
        settings_colors = (self.theme.get("settings_panel") or {}).get("colors") or {}
        player_light = pygame.Color(settings_colors.get("tile", self.theme["colors"]["tile"]))
        self._draw_player_ring(screen, (ring_x, block.y + pad), ui_scale, player_light)
        clock = datetime.now().strftime("%H:%M")
        clock_surf = time_font.render(clock, True, pygame.Color(*_C_HEADER_TEXT))
        screen.blit(clock_surf, (block.right - clock_surf.get_width() - pad, block.y + pad + 4))

        body_y = content.y
        body_h = content.height

        self._tab_hitboxes = []
        tab_positions: list[tuple[int, pygame.Rect]] = []
        x = block.x
        for idx in layout["left_tabs"]:
            rect = pygame.Rect(x, body_y, tab_w, body_h)
            tab_positions.append((idx, rect))
            x += tab_w
        x = content.right
        for idx in layout["right_tabs"]:
            rect = pygame.Rect(x, body_y, tab_w, body_h)
            tab_positions.append((idx, rect))
            x += tab_w

        for idx, rect in tab_positions:
            self._tab_hitboxes.append((idx, rect))
            active = idx == self.tab_index
            grad = _vertical_gradient(
                rect.size,
                _C_TAB_ACTIVE_TOP if active else _C_TAB_IDLE_TOP,
                _C_TAB_ACTIVE_BOT if active else _C_TAB_IDLE_BOT,
            )
            screen.blit(grad, rect.topleft)
            pygame.draw.line(screen, pygame.Color(72, 92, 108), rect.topright, rect.bottomright, 1)
            label = _vertical_text(
                tab_font,
                self._tab_label(idx),
                pygame.Color(28, 36, 44) if active else pygame.Color(42, 52, 60),
            )
            lr = label.get_rect(center=rect.center)
            screen.blit(label, lr.topleft)

        tex = self._content_surface(content.size)
        screen.blit(tex, content.topleft)
        pygame.draw.rect(screen, pygame.Color(72, 92, 108), content, 1)

        items = self._items()
        row_h = metrics["row_h"]
        row_pad = metrics["row_pad"]
        self._item_rects = []
        for i, item in enumerate(items):
            row = pygame.Rect(content.x, content.y + i * row_h, content.width, row_h)
            if row.bottom > content.bottom:
                break
            self._item_rects.append(row)
            if i > 0:
                pygame.draw.line(
                    screen,
                    pygame.Color(*_C_CONTENT_LINE),
                    (row.x + pad, row.y),
                    (row.right - pad, row.y),
                    1,
                )
            selected = i == self.item_index
            if selected:
                sel = pygame.Rect(row.x + row_pad, row.y + row_pad, row.width - row_pad * 2, row.height - row_pad * 2)
                sel_bg = _vertical_gradient(sel.size, _C_SELECT_TOP, _C_SELECT)
                screen.blit(sel_bg, sel.topleft)
                text_color = pygame.Color(255, 255, 255)
                text_x = sel.x + pad
            else:
                text_color = pygame.Color(*_C_ROW_TEXT)
                text_x = row.x + pad + 2
            label = item_font.render(page_title(item.label), True, text_color)
            screen.blit(label, (text_x, row.centery - label.get_height() // 2))
            if item.trailing_icon == "disc":
                self._draw_disc_icon(screen, (row.right - pad * 2, row.centery), ui_scale)

        self._draw_footer_prompts(screen, block.bottom + metrics["footer_gap"], sw // 2, font_family, metrics)
