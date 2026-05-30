from __future__ import annotations

from typing import Any

import pygame

from ui.page_text import page_title


class TileRail:
    def __init__(self, tiles: list[dict[str, Any]], theme: dict[str, Any]) -> None:
        self.tiles = tiles
        self.theme = theme
        self.selected_index = 0
        self._animated_index = 0.0

    def move(self, direction: int) -> None:
        if not self.tiles:
            return
        self.selected_index = (self.selected_index + direction) % len(self.tiles)

    def update(self, dt: float) -> None:
        speed = float(self.theme["motion"]["focus_lerp_speed"])
        self._animated_index += (self.selected_index - self._animated_index) * min(1.0, dt * speed)

    def set_selected_index(self, index: int) -> None:
        if 0 <= index < len(self.tiles):
            self.selected_index = index

    def selected_tile(self) -> dict[str, Any]:
        return self.tiles[self.selected_index]

    def tile_rects(self, origin_x: int, origin_y: int) -> list[pygame.Rect]:
        tile_w = int(self.theme["tile"]["width"])
        tile_h = int(self.theme["tile"]["height"])
        gap = int(self.theme["tile"]["gap"])
        center_offset = int(self._animated_index * (tile_w + gap))
        rects: list[pygame.Rect] = []
        for idx, _tile in enumerate(self.tiles):
            x = origin_x + idx * (tile_w + gap) - center_offset
            rects.append(pygame.Rect(x, origin_y, tile_w, tile_h))
        return rects

    def index_at_pos(self, pos: tuple[int, int], origin_x: int, origin_y: int) -> int | None:
        for idx, rect in enumerate(self.tile_rects(origin_x, origin_y)):
            if rect.collidepoint(pos):
                return idx
        return None

    def draw(self, screen: pygame.Surface, origin_x: int, origin_y: int) -> None:
        tile_w = int(self.theme["tile"]["width"])
        tile_h = int(self.theme["tile"]["height"])
        gap = int(self.theme["tile"]["gap"])
        focus_border = int(self.theme["tile"]["focus_border"])

        normal_color = pygame.Color(self.theme["colors"]["tile"])
        focus_color = pygame.Color(self.theme["colors"]["tile_focus"])
        text_color = pygame.Color(self.theme["colors"]["text"])
        font = pygame.font.SysFont(
            self.theme["typography"]["font_family"],
            int(self.theme["typography"]["tile_size"]),
        )

        rects = self.tile_rects(origin_x, origin_y)
        for idx, tile in enumerate(self.tiles):
            rect = rects[idx]
            x = rect.x
            y = rect.y
            is_selected = idx == self.selected_index

            pygame.draw.rect(screen, focus_color if is_selected else normal_color, rect, border_radius=4)
            if is_selected:
                pygame.draw.rect(
                    screen,
                    pygame.Color(self.theme["colors"]["accent"]),
                    rect.inflate(focus_border * 2, focus_border * 2),
                    width=focus_border,
                    border_radius=6,
                )

            label = font.render(page_title(tile.get("title", "Untitled")), True, text_color)
            screen.blit(label, (x + 14, y + tile_h - label.get_height() - 14))
