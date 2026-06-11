from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pygame

from services.game_library import GameLibraryLoader
from services.launcher import LaunchError, Launcher


class CoreScene:
    _MENU_ITEMS = ("Launch", "Refresh", "Choose Theme", "Quit")

    def __init__(
        self,
        *,
        launcher: Launcher,
        on_choose_theme: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.launcher = launcher
        self.on_choose_theme = on_choose_theme
        self.on_quit = on_quit
        self.status_text = ""
        self._status_timer = 0.0

        self._games: list[dict[str, Any]] = []
        self._selected_index = 0
        self._scroll_offset = 0
        self._menu_index = 2
        self._focus = "games"
        self._loading = True
        self._load_error = ""
        self._loader = GameLibraryLoader()
        self._load_generation = self._loader.start(fast=True)

        self._title_font = pygame.font.SysFont("Segoe UI", 42, bold=True)
        self._body_font = pygame.font.SysFont("Segoe UI", 24)
        self._small_font = pygame.font.SysFont("Segoe UI", 18)
        self._row_height = 44
        self._visible_rows = 14

    def refresh_games(self) -> None:
        self._loading = True
        self._load_error = ""
        self._load_generation = self._loader.start(fast=True)

    def handle_text_input(self, _event: pygame.event.Event) -> bool:
        return False

    def handle_keydown(self, event: pygame.event.Event) -> bool:
        if event.key == pygame.K_TAB:
            self._focus = "menu" if self._focus == "games" else "games"
            return True
        return False

    def handle_action(self, action: str) -> None:
        if action.startswith("MOUSE_CLICK:"):
            parts = action.split(":")
            if len(parts) >= 3:
                self._handle_click(int(parts[1]), int(parts[2]))
            return

        if action == "EXIT_TO_DESKTOP":
            self.on_quit()
            return

        if self._focus == "menu":
            self._handle_menu_action(action)
            return

        if action == "MOVE_UP":
            self._move_selection(-1)
        elif action == "MOVE_DOWN":
            self._move_selection(1)
        elif action == "SELECT":
            self._launch_selected()
        elif action == "DETAILS":
            self.on_choose_theme()
        elif action == "BACK":
            self._focus = "menu"
        elif action == "MOVE_LEFT":
            self._focus = "menu"
            self._menu_index = max(0, self._menu_index - 1)
        elif action == "MOVE_RIGHT":
            self._focus = "menu"
            self._menu_index = min(len(self._MENU_ITEMS) - 1, self._menu_index + 1)

    def _handle_menu_action(self, action: str) -> None:
        if action in ("MOVE_LEFT", "HUB_PREV"):
            self._menu_index = max(0, self._menu_index - 1)
        elif action in ("MOVE_RIGHT", "HUB_NEXT"):
            self._menu_index = min(len(self._MENU_ITEMS) - 1, self._menu_index + 1)
        elif action == "MOVE_UP":
            self._focus = "games"
        elif action == "SELECT":
            self._activate_menu_item(self._menu_index)
        elif action == "BACK":
            self._focus = "games"

    def _activate_menu_item(self, index: int) -> None:
        label = self._MENU_ITEMS[index]
        if label == "Launch":
            self._launch_selected()
        elif label == "Refresh":
            self.refresh_games()
        elif label == "Choose Theme":
            self.on_choose_theme()
        elif label == "Quit":
            self.on_quit()

    def _launch_selected(self) -> None:
        if not self._games:
            self._set_status("No games available.")
            return
        game = self._games[self._selected_index]
        try:
            self.launcher.launch(game)
            self._set_status(f"Launched {game.get('title', 'game')}.")
        except LaunchError as exc:
            self._set_status(str(exc))

    def _move_selection(self, delta: int) -> None:
        if not self._games:
            return
        self._selected_index = (self._selected_index + delta) % len(self._games)
        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + self._visible_rows:
            self._scroll_offset = self._selected_index - self._visible_rows + 1

    def _set_status(self, message: str) -> None:
        self.status_text = message
        self._status_timer = 3.0

    def update(self, dt: float) -> None:
        if self._status_timer > 0:
            self._status_timer = max(0.0, self._status_timer - dt)

        self._loader.poll(
            self._load_generation,
            on_ok=self._on_games_loaded,
            on_err=self._on_games_error,
        )

    def _on_games_loaded(self, entries: list[dict[str, Any]]) -> None:
        self._games = entries
        self._loading = False
        self._load_error = ""
        if self._games:
            self._selected_index = min(self._selected_index, len(self._games) - 1)
        else:
            self._selected_index = 0
        self._set_status(f"Loaded {len(self._games)} games.")

    def _on_games_error(self, message: str) -> None:
        self._loading = False
        self._load_error = message
        self._set_status(message)

    def _layout(self, screen: pygame.Surface) -> dict[str, pygame.Rect]:
        width, height = screen.get_size()
        margin = 48
        menu_h = 56
        return {
            "header": pygame.Rect(margin, 24, width - margin * 2, 56),
            "list": pygame.Rect(margin, 96, width - margin * 2, height - 96 - menu_h - 72),
            "menu": pygame.Rect(margin, height - menu_h - 48, width - margin * 2, menu_h),
            "footer": pygame.Rect(margin, height - 36, width - margin * 2, 24),
        }

    def _handle_click(self, x: int, y: int) -> None:
        if not hasattr(self, "_last_layout"):
            return
        layout = self._last_layout
        if layout["menu"].collidepoint(x, y):
            self._focus = "menu"
            button_w = layout["menu"].width // len(self._MENU_ITEMS)
            rel_x = x - layout["menu"].x
            self._menu_index = max(0, min(len(self._MENU_ITEMS) - 1, rel_x // max(1, button_w)))
            self._activate_menu_item(self._menu_index)
            return

        if layout["list"].collidepoint(x, y) and self._games:
            self._focus = "games"
            rel_y = y - layout["list"].y
            row = self._scroll_offset + rel_y // self._row_height
            if 0 <= row < len(self._games):
                self._selected_index = row
                self._launch_selected()

    def render(self, screen: pygame.Surface) -> None:
        screen.fill(pygame.Color("#12141c"))
        layout = self._layout(screen)
        self._last_layout = layout

        title = self._title_font.render("JerLauncher", True, pygame.Color("#eef2ff"))
        screen.blit(title, (layout["header"].x, layout["header"].y))

        list_rect = layout["list"]
        pygame.draw.rect(screen, pygame.Color("#1a1f2e"), list_rect, border_radius=8)
        pygame.draw.rect(screen, pygame.Color("#2a3145"), list_rect, width=1, border_radius=8)

        if self._loading:
            msg = self._body_font.render("Scanning installed games...", True, pygame.Color("#c7cde0"))
            screen.blit(msg, (list_rect.x + 20, list_rect.y + 20))
        elif self._load_error:
            msg = self._body_font.render(self._load_error, True, pygame.Color("#ff8f8f"))
            screen.blit(msg, (list_rect.x + 20, list_rect.y + 20))
        elif not self._games:
            msg = self._body_font.render("No installed games found.", True, pygame.Color("#c7cde0"))
            screen.blit(msg, (list_rect.x + 20, list_rect.y + 20))
        else:
            y = list_rect.y + 8
            for index in range(self._scroll_offset, min(len(self._games), self._scroll_offset + self._visible_rows)):
                game = self._games[index]
                row_rect = pygame.Rect(list_rect.x + 8, y, list_rect.width - 16, self._row_height - 4)
                selected = self._focus == "games" and index == self._selected_index
                if selected:
                    pygame.draw.rect(screen, pygame.Color("#2d6cdf"), row_rect, border_radius=6)
                title_text = str(game.get("title", "Unknown"))
                store = str(game.get("store", "")).upper()
                label = self._body_font.render(title_text, True, pygame.Color("#f3f6ff"))
                store_surf = self._small_font.render(store, True, pygame.Color("#9aa3ba"))
                screen.blit(label, (row_rect.x + 12, row_rect.y + 8))
                screen.blit(store_surf, (row_rect.right - store_surf.get_width() - 12, row_rect.y + 12))
                y += self._row_height

        menu_rect = layout["menu"]
        button_w = menu_rect.width // len(self._MENU_ITEMS)
        for index, label in enumerate(self._MENU_ITEMS):
            btn = pygame.Rect(menu_rect.x + index * button_w + 4, menu_rect.y, button_w - 8, menu_rect.height)
            selected = self._focus == "menu" and index == self._menu_index
            color = pygame.Color("#2d6cdf") if selected else pygame.Color("#242a3a")
            pygame.draw.rect(screen, color, btn, border_radius=8)
            text = self._body_font.render(label, True, pygame.Color("#f3f6ff"))
            screen.blit(text, text.get_rect(center=btn.center))

        footer = "Tab: switch focus  |  Enter: launch / activate  |  X: choose theme"
        if self.status_text and self._status_timer > 0:
            footer = self.status_text
        screen.blit(
            self._small_font.render(footer, True, pygame.Color("#8b93a7")),
            (layout["footer"].x, layout["footer"].y),
        )
