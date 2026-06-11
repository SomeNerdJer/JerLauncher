from __future__ import annotations

import math
import ctypes
import json
import os
import platform
import queue
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import winreg
from pathlib import Path
from typing import Any, Callable

import pygame

from core.pinned_games import load_pinned_library_keys, save_pinned_library_keys
from themes.xbox360.page_sounds import play_hub_page_sound
from themes.xbox360.profile_state import (
    CUSTOM_GAMERPIC_REL,
    DEFAULT_GAMERTAG,
    GAMERPIC_GRID_COLS,
    MAX_GAMERTAG_LEN,
    copy_gamerpic_file,
    gamerpic_absolute,
    gamerpic_grid_slots,
    load_profile,
    save_profile,
)
from services.ea_library import list_installed_ea_games
from services.epic_library import list_installed_epic_games
from services.rockstar_library import list_installed_rockstar_games
from services.game_library_key import (
    epic_header_slug,
    parse_steam_appid,
    row_library_key,
    row_store,
    sanitize_override_key,
)
from services.launcher import LaunchError, Launcher
from services.steam_library import (
    fetch_steam_full_controller_support,
    fetch_steam_game_description,
    list_installed_steam_games,
)
from themes.xbox360.assets import theme_asset
from themes.xbox360.guide_overlay import GuideOverlay
from themes.xbox360.games_panel import build_slot_rects, draw_games_panel, games_navigate
from themes.xbox360.home_icons import draw_home_tile_icon, draw_tile_icon
from themes.xbox360.page_text import page_title
from themes.xbox360.my_games_submenu import (
    FILTER_ID_TO_INDEX,
    MY_GAMES_FILTERS,
    compute_my_games_panel_layout,
    draw_my_games_loading_panel,
    draw_my_games_submenu,
    hit_test_my_games_filter_button,
    hit_test_my_games_filter_dropdown,
    hit_test_my_games_tile,
)
from themes.xbox360.tile_rail import TileRail


class DashboardScene:
    @staticmethod
    def _game_library_key(game: dict[str, Any]) -> str:
        return row_library_key(game)

    @staticmethod
    def _game_store(game: dict[str, Any]) -> str:
        return row_store(game)

    def _game_by_library_key(self, library_key: str) -> dict[str, Any] | None:
        for g in self._my_pins_entries:
            if DashboardScene._game_library_key(g) == library_key:
                return g
        for g in self._my_games_entries:
            if DashboardScene._game_library_key(g) == library_key:
                return g
        for g in self._my_games_master_entries:
            if DashboardScene._game_library_key(g) == library_key:
                return g
        return None

    def _library_shelf_active(self) -> bool:
        return self._library_shelf_kind in ("games", "pins")

    def _shelf_entries(self) -> list[dict[str, Any]]:
        if self._library_shelf_kind == "pins":
            return self._my_pins_entries
        return self._my_games_entries

    def _shelf_selected_index(self) -> int:
        if self._library_shelf_kind == "pins":
            return self._my_pins_selected_index
        return self._my_games_selected_index

    def _set_shelf_selected_index(self, value: int) -> None:
        if self._library_shelf_kind == "pins":
            self._my_pins_selected_index = value
        else:
            self._my_games_selected_index = value

    def __init__(
        self,
        theme: dict[str, Any],
        games: list[dict[str, Any]],
        launcher: Launcher,
        on_switch_display: Callable[[], None] | None = None,
    ) -> None:
        self.theme = theme
        self.hubs = ["Home", "Games", "Apps", "Settings"]
        self.hub_index = 0
        self._hub_tiles = self._build_hub_tiles(games)
        self.rail = TileRail(self._hub_tiles[self.hubs[self.hub_index]], theme)
        self.launcher = launcher
        self.on_switch_display = on_switch_display
        self.on_back_to_core: Callable[[], None] | None = None
        self.on_choose_theme: Callable[[], None] | None = None
        self.status_text = ""
        self._status_timer = 0.0
        self._tile_origin_x = 64
        self._tile_origin_y = 170
        self._games_selected_index = 0
        self._games_tile_rects: list[pygame.Rect] = []
        self._library_shelf_kind: str | None = None
        self._my_games_entries: list[dict[str, Any]] = []
        self._my_pins_entries: list[dict[str, Any]] = []
        self._my_pins_selected_index = 0
        self._my_games_titles: dict[str, str] = {}
        self._my_games_selected_index = 0
        self._my_games_art_cache: dict[str, pygame.Surface | None] = {}
        self._my_games_tile_art_scaled: dict[tuple[str, int, int], pygame.Surface] = {}
        self._my_games_popup_surface: pygame.Surface | None = None
        self._my_games_popup_surface_size: tuple[int, int] | None = None
        self._my_games_dim_surface: pygame.Surface | None = None
        self._my_games_dim_surface_size: tuple[int, int] | None = None
        self._my_games_art_download_inflight: set[str] = set()
        self._my_games_art_download_failed: set[str] = set()
        self._my_games_art_download_results: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()
        self._game_art_scan_in_progress = False
        self._game_art_scan_total = 0
        self._game_art_scan_completed = 0
        self._game_art_scan_applied = 0
        self._game_art_scan_new = 0
        self._game_art_scan_failed = 0
        self._game_art_scan_ids: set[str] = set()
        self._game_art_scan_resolved_ids: set[str] = set()
        self._in_my_game_details_submenu = False
        self._my_game_details_library_key: str | None = None
        self._my_game_details_selected_index = 0
        self._my_game_details_option_rects: list[pygame.Rect] = []
        self._my_game_details_description = "Press X to view game details."
        self._my_game_details_loading = False
        self._my_game_details_cache: dict[str, str] = {}
        self._my_games_transition_progress = 0.0
        self._my_games_transition_target = 0.0
        self._my_games_transition_duration_s = 0.12
        self._my_games_loading = False
        self._my_games_loading_spin = 0.0
        self._my_games_library_load_results: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._my_games_library_load_generation = 0
        self._my_games_master_entries: list[dict[str, Any]] = []
        self._my_games_filter_id: str = "all"
        self._my_games_filter_menu_open: bool = False
        self._my_games_filter_menu_index: int = 0
        self._my_games_filter_focused: bool = False
        self._hidden_library_keys = self._load_hidden_library_keys()
        self._pinned_library_keys = load_pinned_library_keys()
        self._steam_input_cache = self._load_steam_input_cache()
        self._steam_input_refresh_pending = False
        self._hub_rects: list[pygame.Rect] = []
        self._hub_transition_active = False
        self._hub_transition_from_index = 0
        self._hub_transition_to_index = 0
        self._hub_transition_progress = 0.0
        self._hub_transition_direction = 1
        self._hub_transition_duration_s = 0.32
        self._home_tile_rects: list[pygame.Rect] = []
        self._home_selected_index = 0
        self._home_tiles = self._build_home_tiles()
        self._settings_tile_rects: list[pygame.Rect] = []
        self._settings_selected_index = 0
        self._in_display_submenu = False
        self._in_system_info_submenu = False
        self._in_art_submenu = False
        self._in_jerlauncher_theme_submenu = False
        self._profile_edit_mode: str | None = None
        self._profile_edit_buffer = ""
        self._gamerpic_grid_index = 0
        self._gamerpic_grid_rects: list[pygame.Rect] = []
        self._gamerpic_thumb_cache: dict[str, pygame.Surface] = {}
        # "sidebar" = left list; "panel" = right content (gamertag edit, etc.)
        self._settings_submenu_focus: str = "sidebar"
        self._gamerpic_grid_engaged = False
        self._last_settings_submenu: str | None = None
        self._settings_submenu_return_index = 0
        self._display_selected_index = 0
        self._display_option_rects: list[pygame.Rect] = []
        self._display_transition_progress = 0.0
        self._display_transition_target = 0.0
        self._display_transition_duration_s = 0.35
        self._system_info_rows = self._collect_system_info_rows()
        self._in_power_menu = False
        self._power_options = ["Shutdown", "Restart", "Sleep", "Lock", "Exit"]
        self._power_selected_index = 0
        self._power_option_rects: list[pygame.Rect] = []
        self._power_transition_progress = 0.0
        self._power_transition_target = 0.0
        self._power_transition_duration_s = 0.12
        profile = load_profile()
        pic_path = gamerpic_absolute(profile.get("gamerpic"))
        self.guide = GuideOverlay(
            theme,
            gamertag=profile.get("gamertag", DEFAULT_GAMERTAG),
            gamerpic_path=pic_path,
        )
        self._exit_rect = pygame.Rect(0, 0, 0, 0)
        self._bg_image: pygame.Surface | None = None
        self._bg_scaled: pygame.Surface | None = None
        self._bg_scaled_size: tuple[int, int] | None = None
        self._display_bg_image: pygame.Surface | None = None
        self._display_bg_scaled: pygame.Surface | None = None
        self._display_bg_scaled_size: tuple[int, int] | None = None
        self._load_background_image()

    def handle_text_input(self, event: pygame.event.Event) -> bool:
        if (
            not self._in_art_submenu
            or self._settings_submenu_focus != "panel"
            or self._profile_edit_mode != "gamertag"
        ):
            return False
        text = event.text
        if not text:
            return True
        room = MAX_GAMERTAG_LEN - len(self._profile_edit_buffer)
        if room <= 0:
            return True
        self._profile_edit_buffer += text[:room]
        return True

    def handle_keydown(self, event: pygame.event.Event) -> bool:
        if (
            not self._in_art_submenu
            or self._settings_submenu_focus != "panel"
            or self._profile_edit_mode != "gamertag"
        ):
            return False
        if event.key == pygame.K_RETURN:
            self._save_gamertag_edit()
            return True
        if event.key == pygame.K_ESCAPE:
            self._profile_edit_mode = None
            return True
        if event.key == pygame.K_BACKSPACE:
            self._profile_edit_buffer = self._profile_edit_buffer[:-1]
            return True
        return False

    def handle_action(self, action: str) -> None:
        if action == "TOGGLE_GUIDE":
            self.guide.toggle()
            return

        if self.guide.visible:
            if action == "EXIT_TO_DESKTOP":
                pygame.event.post(pygame.event.Event(pygame.QUIT))
                return
            if action == "DETAILS":
                self._apply_guide_command(self.guide.handle_action("GUIDE_SIGN_OUT"))
                return
            if action.startswith("MOUSE_HOVER:"):
                _, sx, sy = action.split(":")
                self.guide.apply_mouse_hover((int(sx), int(sy)))
                return
            if action.startswith("MOUSE_CLICK:"):
                _, sx, sy = action.split(":")
                self._apply_guide_command(self.guide.apply_mouse_click((int(sx), int(sy))))
                return
            self._apply_guide_command(self.guide.handle_action(action))
            return

        if self._hub_transition_active:
            return
        if self._settings_submenu_transitioning():
            if action in {
                "MOVE_LEFT",
                "MOVE_RIGHT",
                "MOVE_UP",
                "MOVE_DOWN",
                "SELECT",
                "DETAILS",
                "HUB_PREV",
                "HUB_NEXT",
            } or action.startswith("MOUSE_"):
                return
        if action.startswith("MOUSE_HOVER:"):
            _, sx, sy = action.split(":")
            hover_pos = (int(sx), int(sy))
            if self._in_power_menu:
                hover_index = self._power_option_index_at_pos(hover_pos)
                if hover_index is not None:
                    self._power_selected_index = hover_index
                return
            if self._library_shelf_active():
                self._shelf_mouse_hover(hover_pos)
                return
            if self._active_hub() == "Home":
                hover_index = self._home_index_at_pos(hover_pos)
                if hover_index is not None:
                    self._home_selected_index = hover_index
            elif self._active_hub() == "Settings":
                if self._in_display_submenu or self._in_art_submenu:
                    if self._gamerpic_grid_is_active():
                        grid_index = self._gamerpic_grid_index_at_pos(hover_pos)
                        if grid_index is not None:
                            self._gamerpic_grid_index = grid_index
                            return
                    hover_index = self._display_option_index_at_pos(hover_pos)
                    if hover_index is not None:
                        self._display_selected_index = hover_index
                        self._leave_gamerpic_grid_if_needed()
                elif self._in_system_info_submenu:
                    return
                else:
                    hover_index = self._settings_index_at_pos(hover_pos)
                    if hover_index is not None:
                        self._settings_selected_index = hover_index
            elif self._active_hub() == "Games":
                hover_index = self._games_index_at_pos(hover_pos)
                if hover_index is not None:
                    self._games_selected_index = hover_index
            else:
                hover_index = self.rail.index_at_pos(hover_pos, self._tile_origin_x, self._tile_origin_y)
                if hover_index is not None:
                    self.rail.set_selected_index(hover_index)
            return

        if action.startswith("MOUSE_CLICK:"):
            _, sx, sy = action.split(":")
            click_pos = (int(sx), int(sy))

            if self._in_power_menu:
                clicked_index = self._power_option_index_at_pos(click_pos)
                if clicked_index is not None:
                    self._power_selected_index = clicked_index
                    self._apply_power_action(self._power_options[self._power_selected_index])
                return

            if self._library_shelf_active():
                self._shelf_mouse_click(click_pos)
                return

            clicked_hub = self._hub_index_at_pos(click_pos)
            if clicked_hub is not None:
                self._set_hub(clicked_hub)
                return
            if self._active_hub() == "Home":
                clicked_index = self._home_index_at_pos(click_pos)
                if clicked_index is not None:
                    self._home_selected_index = clicked_index
                    self._launch_selected()
            elif self._active_hub() == "Settings":
                if self._in_display_submenu or self._in_art_submenu:
                    grid_index = self._gamerpic_grid_index_at_pos(click_pos)
                    if grid_index is not None and self._gamerpic_grid_engaged:
                        self._gamerpic_grid_index = grid_index
                        self._apply_gamerpic_grid_selection()
                        return
                    clicked_index = self._display_option_index_at_pos(click_pos)
                    if clicked_index is not None:
                        self._settings_submenu_focus = "sidebar"
                        self._display_selected_index = clicked_index
                        self._leave_gamerpic_grid_if_needed()
                        self._handle_settings_submenu_select()
                        return
                elif self._in_system_info_submenu:
                    return
                else:
                    clicked_index = self._settings_index_at_pos(click_pos)
                    if clicked_index is not None:
                        self._settings_selected_index = clicked_index
                        self._launch_selected()
            elif self._active_hub() == "Games":
                clicked_index = self._games_index_at_pos(click_pos)
                if clicked_index is not None:
                    self._games_selected_index = clicked_index
                    self._launch_selected()
            else:
                clicked_index = self.rail.index_at_pos(click_pos, self._tile_origin_x, self._tile_origin_y)
                if clicked_index is not None:
                    self.rail.set_selected_index(clicked_index)
                    self._launch_selected()
            return

        if self._in_power_menu and action not in {"MOVE_UP", "MOVE_DOWN", "SELECT", "BACK"}:
            return

        if self._library_shelf_active() and self._my_games_loading:
            if action == "BACK":
                pass
            elif action.startswith("MOUSE_HOVER:"):
                pass
            else:
                return

        if (
            action == "DETAILS"
            and self._library_shelf_kind == "games"
            and not self._my_games_filter_menu_open
            and not self._in_my_game_details_submenu
            and self._my_games_entries
        ):
            self._open_my_game_details_submenu()
            return

        if action == "HUB_PREV":
            if self.hub_index <= 0:
                return
            self._set_hub(self.hub_index - 1)
        elif action == "HUB_NEXT":
            if self.hub_index >= len(self.hubs) - 1:
                return
            self._set_hub(self.hub_index + 1)
        elif action == "MOVE_LEFT":
            if self._in_power_menu:
                return
            if self._handle_library_shelf_navigation(action):
                return
            if self._active_hub() == "Home":
                self._home_move(-1, 0)
            elif self._active_hub() == "Settings":
                if self._gamerpic_grid_is_active() and self._gamerpic_grid_nav(-1, 0):
                    return
                if self._in_display_submenu or self._in_art_submenu:
                    return
                if self._in_system_info_submenu:
                    return
                self._settings_selected_index = max(0, self._settings_selected_index - 1)
            elif self._active_hub() == "Games":
                self._games_selected_index = games_navigate(self._games_selected_index, "left")
            else:
                self.rail.move(-1)
        elif action == "MOVE_RIGHT":
            if self._in_power_menu:
                return
            if self._handle_library_shelf_navigation(action):
                return
            if self._active_hub() == "Home":
                self._home_move(1, 0)
            elif self._active_hub() == "Settings":
                if self._gamerpic_grid_is_active() and self._gamerpic_grid_nav(1, 0):
                    return
                if self._in_display_submenu or self._in_art_submenu:
                    return
                if self._in_system_info_submenu:
                    return
                max_index = self._settings_slot_count() - 1
                self._settings_selected_index = min(max_index, self._settings_selected_index + 1)
            elif self._active_hub() == "Games":
                self._games_selected_index = games_navigate(self._games_selected_index, "right")
            else:
                self.rail.move(1)
        elif action == "MOVE_UP":
            if self._in_power_menu:
                if self._power_transition_target < 1.0:
                    return
                self._power_selected_index = (self._power_selected_index - 1) % len(self._power_options)
                return
            if self._handle_library_shelf_navigation(action):
                return
            if self._active_hub() == "Home":
                self._home_move(0, -1)
            elif self._active_hub() == "Settings":
                if self._in_display_submenu or self._in_art_submenu:
                    if self._profile_edit_mode:
                        return
                    if self._gamerpic_grid_is_active() and self._gamerpic_grid_nav(0, -1):
                        return
                    self._move_settings_submenu_selection(-1)
                elif self._in_system_info_submenu:
                    return
                else:
                    self._settings_selected_index = max(0, self._settings_selected_index - 4)
            elif self._active_hub() == "Games":
                self._games_selected_index = games_navigate(self._games_selected_index, "up")
            else:
                self._set_hub((self.hub_index - 1) % len(self.hubs))
        elif action == "MOVE_DOWN":
            if self._in_power_menu:
                if self._power_transition_target < 1.0:
                    return
                self._power_selected_index = (self._power_selected_index + 1) % len(self._power_options)
                return
            if self._handle_library_shelf_navigation(action):
                return
            if self._active_hub() == "Home":
                self._home_move(0, 1)
            elif self._active_hub() == "Settings":
                if self._in_display_submenu or self._in_art_submenu:
                    if self._profile_edit_mode:
                        return
                    if self._gamerpic_grid_is_active() and self._gamerpic_grid_nav(0, 1):
                        return
                    self._move_settings_submenu_selection(1)
                elif self._in_system_info_submenu:
                    return
                else:
                    max_index = self._settings_slot_count() - 1
                    self._settings_selected_index = min(max_index, self._settings_selected_index + 4)
            elif self._active_hub() == "Games":
                self._games_selected_index = games_navigate(self._games_selected_index, "down")
            else:
                self._set_hub((self.hub_index + 1) % len(self.hubs))
        elif action == "EXIT_TO_DESKTOP":
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        elif action == "SELECT":
            if self._in_power_menu:
                if self._power_transition_target < 1.0:
                    return
                self._apply_power_action(self._power_options[self._power_selected_index])
                return
            if self._library_shelf_active() and self._library_shelf_show_filter_ui() and self._my_games_filter_menu_open:
                idx = max(0, min(self._my_games_filter_menu_index, len(MY_GAMES_FILTERS) - 1))
                self._my_games_filter_id = MY_GAMES_FILTERS[idx][0]
                self._my_games_filter_menu_open = False
                self._apply_my_games_filter()
                self._my_games_selected_index = min(
                    self._my_games_selected_index,
                    max(0, len(self._my_games_entries) - 1),
                )
                return
            if (
                self._library_shelf_active()
                and self._library_shelf_show_filter_ui()
                and not self._in_my_game_details_submenu
                and self._my_games_filter_focused
                and not self._my_games_filter_menu_open
            ):
                self._open_my_games_filter_menu()
                return
            if self._library_shelf_active() and self._in_my_game_details_submenu:
                self._apply_my_game_details_action()
                return
            self._launch_selected()
        elif action == "BACK":
            if self._in_power_menu:
                self._power_transition_target = 0.0
                return
            if self._library_shelf_active():
                if self._my_games_loading:
                    self._cancel_my_games_library_load()
                    self._close_library_shelf()
                    return
                if self._my_games_filter_menu_open:
                    self._my_games_filter_menu_open = False
                    return
                if self._my_games_filter_focused:
                    self._my_games_filter_focused = False
                    return
                if self._in_my_game_details_submenu:
                    self._close_my_game_details_submenu()
                    return
                self._close_library_shelf()
                return
            if self._active_hub() == "Settings" and self._active_settings_submenu_kind() is not None:
                if self._in_display_submenu or self._in_art_submenu:
                    if self._profile_edit_mode:
                        self._profile_edit_mode = None
                        self._settings_submenu_focus = "sidebar"
                        return
                    if self._gamerpic_grid_engaged:
                        self._gamerpic_grid_engaged = False
                        self._settings_submenu_focus = "sidebar"
                        return
                    if self._settings_submenu_focus == "panel":
                        self._settings_submenu_focus = "sidebar"
                        return
                    if self._in_jerlauncher_theme_submenu:
                        self._in_jerlauncher_theme_submenu = False
                        for idx, option in enumerate(self._art_submenu_options()):
                            if option.get("action") == "open_jerlauncher_theme_submenu":
                                self._display_selected_index = idx
                                break
                        self._settings_submenu_focus = "sidebar"
                        return
                self._close_settings_list_submenu()
            else:
                self.status_text = "At dashboard root."
                self._status_timer = 1.5

    def update(self, dt: float) -> None:
        self.rail.update(dt)
        if self._steam_input_refresh_pending and self._library_shelf_active():
            self._steam_input_refresh_pending = False
            if self._library_shelf_kind == "pins":
                self._apply_my_pins_entries()
            else:
                self._apply_my_games_filter()
        if self._display_transition_progress != self._display_transition_target:
            step = dt / max(0.001, self._display_transition_duration_s)
            if self._display_transition_progress < self._display_transition_target:
                self._display_transition_progress = min(
                    self._display_transition_target,
                    self._display_transition_progress + step,
                )
            else:
                self._display_transition_progress = max(
                    self._display_transition_target,
                    self._display_transition_progress - step,
                )
            if (
                self._display_transition_progress <= 0.0
                and self._display_transition_target <= 0.0
            ):
                self._last_settings_submenu = None
        if self._status_timer > 0:
            self._status_timer = max(0.0, self._status_timer - dt)
        elif not self.launcher.is_running():
            self.status_text = ""
        if self._hub_transition_active:
            step = dt / max(0.001, self._hub_transition_duration_s)
            self._hub_transition_progress = min(1.0, self._hub_transition_progress + step)
            if self._hub_transition_progress >= 1.0:
                self._apply_hub_state(self._hub_transition_to_index)
                self._hub_transition_active = False
                self._hub_transition_progress = 0.0
        self.guide.update(dt)
        if self._power_transition_progress != self._power_transition_target:
            step = dt / max(0.001, self._power_transition_duration_s)
            if self._power_transition_progress < self._power_transition_target:
                self._power_transition_progress = min(
                    self._power_transition_target,
                    self._power_transition_progress + step,
                )
            else:
                self._power_transition_progress = max(
                    self._power_transition_target,
                    self._power_transition_progress - step,
                )
            if self._power_transition_progress <= 0.0 and self._power_transition_target <= 0.0:
                self._in_power_menu = False
                self._power_option_rects = []
        self._drain_my_games_art_downloads()
        self._drain_my_games_library_load()
        if self._my_games_loading:
            self._my_games_loading_spin += dt * 3.4
        if self._my_games_transition_progress != self._my_games_transition_target:
            step = dt / max(0.001, self._my_games_transition_duration_s)
            if self._my_games_transition_progress < self._my_games_transition_target:
                self._my_games_transition_progress = min(
                    self._my_games_transition_target,
                    self._my_games_transition_progress + step,
                )
            else:
                self._my_games_transition_progress = max(
                    self._my_games_transition_target,
                    self._my_games_transition_progress - step,
                )
            if self._my_games_transition_progress <= 0.0 and self._my_games_transition_target <= 0.0:
                self._library_shelf_kind = None
                self._clear_my_games_art_caches()

    def render(self, screen: pygame.Surface) -> None:
        colors = self.theme["colors"]
        display_mix = self._display_transition_progress
        self._draw_transitioned_background(screen, display_mix)

        if display_mix > 0.0:
            self._hub_rects = []
            self._exit_rect = pygame.Rect(0, 0, 0, 0)
            self._draw_settings_submenu(screen, alpha=max(1, int(255 * display_mix)))
            return

        hub_font = pygame.font.SysFont(
            self.theme["typography"]["font_family"],
            int(self.theme["typography"]["hub_size"]),
        )
        text_font = pygame.font.SysFont(
            self.theme["typography"]["font_family"],
            int(self.theme["typography"]["body_size"]),
        )

        x = 64
        y = 56
        self._hub_rects = []
        for idx, hub in enumerate(self.hubs):
            color = colors["accent"] if idx == self.hub_index else colors["text_dim"]
            hub_surface = hub_font.render(page_title(hub), True, pygame.Color(color))
            hub_rect = hub_surface.get_rect(topleft=(x, y))
            self._hub_rects.append(hub_rect.inflate(20, 12))
            screen.blit(hub_surface, hub_rect.topleft)
            x += hub_surface.get_width() + 42

        if self._hub_transition_active:
            screen_size = screen.get_size()
            from_layer = pygame.Surface(screen_size, pygame.SRCALPHA)
            to_layer = pygame.Surface(screen_size, pygame.SRCALPHA)
            from_hub = self.hubs[self._hub_transition_from_index]
            to_hub = self.hubs[self._hub_transition_to_index]
            self._draw_hub_content(from_layer, from_hub, use_active_rail=True)
            self._draw_hub_content(to_layer, to_hub, use_active_rail=False)
            travel = screen_size[0]
            progress = self._hub_transition_progress
            direction = self._hub_transition_direction
            from_x = int(-direction * progress * travel)
            to_x = int(direction * (1.0 - progress) * travel)
            screen.blit(from_layer, (from_x, 0))
            screen.blit(to_layer, (to_x, 0))
        else:
            shelf_overlay = (
                (self._library_shelf_active() or self._my_games_transition_progress > 0.0)
                and not self._hub_transition_active
            )
            skip_hub_under_overlay = (
                shelf_overlay
                and self._library_shelf_active()
                and self._my_games_transition_progress >= 0.999
            )
            if not skip_hub_under_overlay:
                self._draw_hub_content(screen, self._active_hub(), use_active_rail=True)

        if (
            (self._library_shelf_active() or self._my_games_transition_progress > 0.0)
            and not self._hub_transition_active
        ):
            self._draw_my_games_submenu_overlay(screen)
            if self._in_my_game_details_submenu:
                self._draw_my_game_details_submenu_overlay(screen)

        self._exit_rect = pygame.Rect(0, 0, 0, 0)
        if self.guide.visible:
            self.guide.draw(screen)
        if self._in_power_menu or self._power_transition_progress > 0.0:
            self._draw_power_menu(screen)

    def _launch_selected(self) -> None:
        if self._library_shelf_active():
            entries = self._shelf_entries()
            if not entries:
                return
            idx = max(0, min(self._shelf_selected_index(), len(entries) - 1))
            tile = entries[idx]
            try:
                self.launcher.launch(tile)
                self.status_text = f"Launching: {tile.get('title', 'Unknown')}"
            except LaunchError as exc:
                self.status_text = str(exc)
            self._status_timer = 2.5
            return
        if self._active_hub() == "Games":
            if self._games_selected_index == 0:
                self._open_my_games_submenu()
                return
            return
        if self._active_hub() == "Home":
            tile = self._home_tiles[self._home_selected_index]
            tile_action = tile.get("action")
            if tile_action == "open_my_pins":
                self._open_my_pins_submenu()
                return
            if not tile.get("action") and not tile.get("command"):
                self.status_text = "Home shortcuts are disabled."
                self._status_timer = 1.2
                return
        elif self._active_hub() == "Settings":
            if self._in_display_submenu or self._in_art_submenu:
                self._handle_settings_submenu_select()
                return
            elif self._in_system_info_submenu:
                tile = {"title": "System Information", "action": "open_system_info_submenu"}
            else:
                settings_tiles = self._hub_tiles["Settings"]
                if self._settings_selected_index < len(settings_tiles):
                    tile = settings_tiles[self._settings_selected_index]
                else:
                    tile = {"title": "Coming Soon"}
        else:
            tile = self.rail.selected_tile()

        tile_action = tile.get("action")
        if tile_action == "open_display_submenu":
            self._enter_settings_submenu("display")
            self._in_display_submenu = True
            self._in_system_info_submenu = False
            self._in_art_submenu = False
            self._in_jerlauncher_theme_submenu = False
            self._display_selected_index = 0
            self._settings_submenu_focus = "sidebar"
            self._gamerpic_grid_engaged = False
            return
        if tile_action == "open_art_submenu":
            self._enter_settings_submenu("personalization")
            self._in_display_submenu = False
            self._in_system_info_submenu = False
            self._in_art_submenu = True
            self._in_jerlauncher_theme_submenu = False
            self._display_selected_index = 0
            self._settings_submenu_focus = "sidebar"
            self._gamerpic_grid_engaged = False
            self._profile_edit_mode = None
            return
        if tile_action == "switch_hub":
            target_hub = str(tile.get("hub", "")).strip()
            if target_hub in self.hubs:
                self._set_hub(self.hubs.index(target_hub))
            return
        if tile_action == "open_system_info_submenu":
            self._enter_settings_submenu("system")
            self._in_display_submenu = False
            self._in_system_info_submenu = True
            self._in_art_submenu = False
            self._in_jerlauncher_theme_submenu = False
            return
        if tile_action == "switch_display":
            if self.on_switch_display is not None:
                self.on_switch_display()
                self.status_text = "Switched display."
                self._status_timer = 2.0
            return
        if tile_action == "open_power_menu":
            self._in_power_menu = True
            self._power_selected_index = len(self._power_options) - 1
            self._power_transition_progress = 0.0
            self._power_transition_target = 1.0
            return
        if not tile_action and not tile.get("command"):
            self.status_text = "Not configured yet."
            self._status_timer = 1.5
            return

        try:
            self.launcher.launch(tile)
            self.status_text = f"Launching: {tile.get('title', 'Unknown')}"
        except LaunchError as exc:
            self.status_text = str(exc)
        self._status_timer = 2.5

    def _load_background_image(self) -> None:
        image_path = self.theme.get("background_image")
        self._bg_image = self._load_image_from_theme_path(image_path)
        display_submenu_path = self.theme.get("display_submenu_background_image")
        self._display_bg_image = self._load_image_from_theme_path(display_submenu_path)

    @staticmethod
    def _load_image_from_theme_path(image_path: str | None) -> pygame.Surface | None:
        if not image_path:
            return None
        path = Path(image_path)
        if path.is_absolute():
            resolved = path
        else:
            resolved = theme_asset(str(path).replace("\\", "/"))
        try:
            return pygame.image.load(str(resolved)).convert()
        except (pygame.error, FileNotFoundError):
            return None

    def _draw_background(self, screen: pygame.Surface) -> None:
        colors = self.theme["colors"]
        if self._bg_image is None:
            screen.fill(pygame.Color(colors["background"]))
            return

        size = screen.get_size()
        if self._bg_scaled is None or self._bg_scaled_size != size:
            self._bg_scaled = pygame.transform.smoothscale(self._bg_image, size)
            self._bg_scaled_size = size
        screen.blit(self._bg_scaled, (0, 0))

        overlay_alpha = int(self.theme.get("background_overlay_alpha", 115))
        overlay = pygame.Surface(size, pygame.SRCALPHA)
        overlay.fill((8, 12, 24, overlay_alpha))
        screen.blit(overlay, (0, 0))

    def _draw_display_background(self, screen: pygame.Surface) -> None:
        if self._display_bg_image is None:
            self._draw_background(screen)
            return

        size = screen.get_size()
        if self._display_bg_scaled is None or self._display_bg_scaled_size != size:
            self._display_bg_scaled = pygame.transform.smoothscale(self._display_bg_image, size)
            self._display_bg_scaled_size = size
        screen.blit(self._display_bg_scaled, (0, 0))

        overlay_alpha = int(self.theme.get("background_overlay_alpha", 120))
        overlay = pygame.Surface(size, pygame.SRCALPHA)
        overlay.fill((24, 10, 36, max(40, overlay_alpha - 30)))
        screen.blit(overlay, (0, 0))

    def _draw_transitioned_background(self, screen: pygame.Surface, display_mix: float) -> None:
        self._draw_background(screen)
        if display_mix <= 0.0 or self._display_bg_image is None:
            return

        size = screen.get_size()
        if self._display_bg_scaled is None or self._display_bg_scaled_size != size:
            self._display_bg_scaled = pygame.transform.smoothscale(self._display_bg_image, size)
            self._display_bg_scaled_size = size

        layer = pygame.Surface(size, pygame.SRCALPHA)
        layer.blit(self._display_bg_scaled, (0, 0))
        overlay_alpha = int(self.theme.get("background_overlay_alpha", 120))
        overlay = pygame.Surface(size, pygame.SRCALPHA)
        overlay.fill((24, 10, 36, max(40, overlay_alpha - 30)))
        layer.blit(overlay, (0, 0))
        layer.set_alpha(max(0, min(255, int(255 * display_mix))))
        screen.blit(layer, (0, 0))

    def _draw_exit_button(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        label = "Exit to Desktop Mode"
        text_surface = font.render(label, True, pygame.Color(self.theme["colors"]["text"]))
        padding_x = 16
        padding_y = 10
        width = text_surface.get_width() + padding_x * 2
        height = text_surface.get_height() + padding_y * 2
        x = screen.get_width() - width - 24
        y = 24

        self._exit_rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(screen, pygame.Color(self.theme["colors"]["tile"]), self._exit_rect, border_radius=6)
        pygame.draw.rect(
            screen,
            pygame.Color(self.theme["colors"]["accent"]),
            self._exit_rect,
            width=2,
            border_radius=6,
        )
        screen.blit(text_surface, (x + padding_x, y + padding_y))

    def _draw_hub_content(self, screen: pygame.Surface, hub_name: str, use_active_rail: bool) -> None:
        if hub_name == "Settings":
            if self._active_settings_submenu_kind() is not None:
                self._draw_settings_submenu(screen)
            else:
                self._draw_settings_panel(screen)
        elif hub_name == "Home":
            self._draw_home_panel(screen)
        elif hub_name == "Games":
            self._draw_games_panel(screen)
        else:
            if use_active_rail and hub_name == self._active_hub():
                rail = self.rail
            else:
                rail = TileRail(self._hub_tiles[hub_name], self.theme)
            rail.draw(
                screen,
                origin_x=self._tile_origin_x,
                origin_y=self._tile_origin_y,
            )

    def _apply_hub_state(self, index: int) -> None:
        self.hub_index = index
        active_hub = self.hubs[self.hub_index]
        rail_tiles = [] if active_hub == "Games" else self._hub_tiles[active_hub]
        self.rail = TileRail(rail_tiles, self.theme)
        self._home_selected_index = 0
        self._settings_selected_index = 0
        self._in_display_submenu = False
        self._in_system_info_submenu = False
        self._in_art_submenu = False
        self._in_jerlauncher_theme_submenu = False
        self._last_settings_submenu = None
        self._settings_submenu_return_index = 0
        self._in_power_menu = False
        self._power_selected_index = 0
        self._power_transition_progress = 0.0
        self._power_transition_target = 0.0
        self._display_selected_index = 0
        self._settings_submenu_focus = "sidebar"
        self._gamerpic_grid_engaged = False
        self._profile_edit_mode = None
        self._display_transition_progress = 0.0
        self._display_transition_target = 0.0
        self._games_selected_index = 0
        self._library_shelf_kind = None
        self._my_games_entries = []
        self._my_pins_entries = []
        self._my_pins_selected_index = 0
        self._my_games_selected_index = 0
        self._my_games_filter_menu_open = False
        self._my_games_filter_focused = False
        self._my_games_filter_id = "all"
        self._in_my_game_details_submenu = False
        self._my_game_details_library_key = None
        self._my_game_details_option_rects = []
        self._my_games_transition_progress = 0.0
        self._my_games_transition_target = 0.0
        self._my_games_loading = False
        self._my_games_loading_spin = 0.0
        self._cancel_my_games_library_load()
        self._clear_my_games_art_caches()
        self._my_games_art_download_inflight.clear()
        self._my_games_art_download_failed.clear()
        self._my_games_art_download_results = queue.SimpleQueue()

    def _clear_my_games_art_caches(self) -> None:
        self._my_games_art_cache.clear()
        self._my_games_tile_art_scaled.clear()

    def _invalidate_my_games_tile_scaled(self, library_key: str | None = None) -> None:
        if library_key is None:
            self._my_games_tile_art_scaled.clear()
            return
        self._my_games_tile_art_scaled = {
            key: surf for key, surf in self._my_games_tile_art_scaled.items() if key[0] != library_key
        }

    def _open_my_games_filter_menu(self) -> None:
        self._my_games_filter_menu_open = True
        self._my_games_filter_menu_index = FILTER_ID_TO_INDEX.get(self._my_games_filter_id, 0)

    def _open_my_games_submenu(self) -> None:
        self._close_my_game_details_submenu()
        self._library_shelf_kind = "games"
        self._my_games_filter_menu_open = False
        self._my_games_filter_focused = False
        self._my_games_selected_index = 0
        if self._my_games_transition_progress <= 0.0:
            self._my_games_transition_progress = 0.0
        self._my_games_transition_target = 1.0
        self._my_games_art_download_inflight.clear()
        self._my_games_art_download_failed.clear()
        self._my_games_art_download_results = queue.SimpleQueue()

        if self._my_games_master_entries:
            self._my_games_loading = False
            self._apply_my_games_filter()
            return

        self._begin_my_games_library_load()

    def _begin_my_games_library_load(self) -> None:
        self._clear_my_games_art_caches()
        self._my_games_entries = []
        self._my_games_loading = True
        self._my_games_loading_spin = 0.0
        self._my_games_library_load_generation += 1
        generation = self._my_games_library_load_generation
        threading.Thread(
            target=self._my_games_library_load_worker,
            args=(generation,),
            daemon=True,
        ).start()

    def _cancel_my_games_library_load(self) -> None:
        self._my_games_library_load_generation += 1
        self._my_games_loading = False

    def _my_games_library_load_worker(self, generation: int) -> None:
        try:
            steam = list_installed_steam_games(fast=True)
            epic = list_installed_epic_games(fast=True)
            ea = list_installed_ea_games(fast=True)
            rockstar = list_installed_rockstar_games(fast=True)
            entries = sorted(
                steam + epic + ea + rockstar,
                key=lambda g: str(g.get("title", "")).casefold(),
            )
            self._my_games_library_load_results.put(("ok", generation, entries))
        except Exception as exc:  # pragma: no cover
            self._my_games_library_load_results.put(("err", generation, str(exc)))

    def _drain_my_games_library_load(self) -> None:
        while True:
            try:
                msg = self._my_games_library_load_results.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            generation = msg[1]
            if generation != self._my_games_library_load_generation:
                continue
            if not self._library_shelf_active():
                self._my_games_loading = False
                continue
            if kind == "err":
                self._my_games_loading = False
                self.status_text = f"Could not load games: {msg[2]}"
                self._status_timer = 3.0
                self._close_library_shelf()
                continue
            entries = msg[2]
            self._my_games_master_entries = entries
            self._attach_steam_input_tags(self._my_games_master_entries)
            self._apply_saved_custom_covers_to_entries_list(self._my_games_master_entries)
            self._my_games_titles = {
                DashboardScene._game_library_key(game): str(game.get("title", "")).strip()
                for game in self._my_games_master_entries
                if DashboardScene._game_library_key(game)
            }
            self._my_games_loading = False
            if self._library_shelf_kind == "pins":
                self._apply_my_pins_entries()
            else:
                self._apply_my_games_filter()
            threading.Thread(target=self._steam_input_backfill_worker, daemon=True).start()

    def _close_my_games_submenu(self) -> None:
        self._close_library_shelf()

    def _close_library_shelf(self) -> None:
        self._close_my_game_details_submenu()
        self._my_games_transition_target = 0.0

    def _open_my_pins_submenu(self) -> None:
        self._close_my_game_details_submenu()
        self._library_shelf_kind = "pins"
        self._my_games_filter_menu_open = False
        self._my_games_filter_focused = False
        self._my_pins_selected_index = 0
        if self._my_games_transition_progress <= 0.0:
            self._my_games_transition_progress = 0.0
        self._my_games_transition_target = 1.0
        self._my_games_art_download_inflight.clear()
        self._my_games_art_download_failed.clear()
        self._my_games_art_download_results = queue.SimpleQueue()

        if self._my_games_master_entries:
            self._my_games_loading = False
            self._apply_my_pins_entries()
            return

        self._begin_my_games_library_load()

    def _apply_my_pins_entries(self) -> None:
        keys = self._pinned_library_keys
        out: list[dict[str, Any]] = []
        for g in self._my_games_master_entries:
            lk = DashboardScene._game_library_key(g)
            if lk and lk in keys:
                out.append(g)
        self._my_pins_entries = out
        if self._my_pins_selected_index >= len(self._my_pins_entries):
            self._my_pins_selected_index = max(0, len(self._my_pins_entries) - 1)

    def _library_shelf_show_filter_ui(self) -> bool:
        return self._library_shelf_kind == "games"

    def _shelf_move_horizontal(self, delta: int) -> None:
        if self._my_games_filter_menu_open or (
            self._library_shelf_show_filter_ui() and self._my_games_filter_focused
        ):
            return
        entries = self._shelf_entries()
        if not entries:
            return
        idx = self._shelf_selected_index()
        self._set_shelf_selected_index(max(0, min(len(entries) - 1, idx + delta)))

    def _handle_library_shelf_navigation(self, action: str) -> bool:
        """Consume directional input while My Games / My Pins shelf is open."""
        if not self._library_shelf_active():
            return False

        if self._in_my_game_details_submenu:
            if action == "MOVE_UP":
                self._my_game_details_selected_index = max(0, self._my_game_details_selected_index - 1)
            elif action == "MOVE_DOWN":
                max_index = len(self._my_game_details_options()) - 1
                self._my_game_details_selected_index = min(
                    max_index, self._my_game_details_selected_index + 1
                )
            return True

        show_filter = self._library_shelf_show_filter_ui()

        if action == "MOVE_UP":
            if show_filter and self._my_games_filter_menu_open:
                self._my_games_filter_menu_index = (self._my_games_filter_menu_index - 1) % len(
                    MY_GAMES_FILTERS
                )
            elif show_filter:
                self._my_games_filter_focused = True
            else:
                self._shelf_move_horizontal(-1)
            return True

        if action == "MOVE_DOWN":
            if show_filter and self._my_games_filter_menu_open:
                self._my_games_filter_menu_index = (self._my_games_filter_menu_index + 1) % len(
                    MY_GAMES_FILTERS
                )
            elif show_filter and self._my_games_filter_focused:
                self._my_games_filter_focused = False
            elif not show_filter:
                self._shelf_move_horizontal(1)
            return True

        if action == "MOVE_LEFT":
            self._shelf_move_horizontal(-1)
            return True

        if action == "MOVE_RIGHT":
            self._shelf_move_horizontal(1)
            return True

        return False

    def _shelf_mouse_hover(self, hover_pos: tuple[int, int]) -> None:
        if self._in_my_game_details_submenu:
            return
        surf = pygame.display.get_surface()
        if surf is None:
            return
        sw, sh = surf.get_size()
        px, py, pw, ph = self._my_games_popup_screen_rect(sw, sh)
        lx = hover_pos[0] - px
        ly = hover_pos[1] - py
        if not (0 <= lx < pw and 0 <= ly < ph):
            return
        show_filter = self._library_shelf_show_filter_ui()
        layout = compute_my_games_panel_layout(
            pw,
            ph,
            filter_menu_open=self._my_games_filter_menu_open,
            full_screen=True,
            show_filter_ui=show_filter,
        )
        if show_filter and self._my_games_filter_menu_open:
            hi_dd = hit_test_my_games_filter_dropdown(lx, ly, layout)
            if hi_dd is not None:
                self._my_games_filter_menu_index = hi_dd
        if show_filter and not self._my_games_filter_menu_open:
            entries = self._shelf_entries()
            hi = hit_test_my_games_tile(
                lx,
                ly,
                pw,
                ph,
                len(entries),
                self._shelf_selected_index(),
                full_screen=True,
                show_filter_ui=show_filter,
            )
            if hi is not None and hi != self._shelf_selected_index():
                self._set_shelf_selected_index(hi)
                self._my_games_filter_focused = False
        elif not show_filter:
            entries = self._shelf_entries()
            hi = hit_test_my_games_tile(
                lx,
                ly,
                pw,
                ph,
                len(entries),
                self._shelf_selected_index(),
                full_screen=True,
                show_filter_ui=show_filter,
            )
            if hi is not None and hi != self._shelf_selected_index():
                self._set_shelf_selected_index(hi)
                self._my_games_filter_focused = False

    def _shelf_mouse_click(self, click_pos: tuple[int, int]) -> None:
        if self._in_my_game_details_submenu:
            for idx, rect in enumerate(self._my_game_details_option_rects):
                if rect.collidepoint(click_pos):
                    self._my_game_details_selected_index = idx
                    self._apply_my_game_details_action()
                    break
            return
        surf = pygame.display.get_surface()
        if surf is None:
            return
        sw, sh = surf.get_size()
        px, py, pw, ph = self._my_games_popup_screen_rect(sw, sh)
        lx = click_pos[0] - px
        ly = click_pos[1] - py
        if not (0 <= lx < pw and 0 <= ly < ph):
            return
        show_filter = self._library_shelf_show_filter_ui()
        layout = compute_my_games_panel_layout(
            pw,
            ph,
            filter_menu_open=self._my_games_filter_menu_open,
            full_screen=True,
            show_filter_ui=show_filter,
        )
        if show_filter and self._my_games_filter_menu_open:
            dd_idx = hit_test_my_games_filter_dropdown(lx, ly, layout)
            if dd_idx is not None:
                self._my_games_filter_id = MY_GAMES_FILTERS[dd_idx][0]
                self._my_games_filter_menu_open = False
                self._apply_my_games_filter()
                self._my_games_selected_index = min(
                    self._my_games_selected_index,
                    max(0, len(self._my_games_entries) - 1),
                )
                return
            if hit_test_my_games_filter_button(lx, ly, layout):
                self._my_games_filter_menu_open = False
                return
            self._my_games_filter_menu_open = False
            self._my_games_filter_focused = False
            return
        if show_filter and hit_test_my_games_filter_button(lx, ly, layout):
            self._my_games_filter_focused = True
            self._open_my_games_filter_menu()
            return
        entries = self._shelf_entries()
        ci = hit_test_my_games_tile(
            lx,
            ly,
            pw,
            ph,
            len(entries),
            self._shelf_selected_index(),
            full_screen=True,
            show_filter_ui=show_filter,
        )
        if ci is not None:
            self._set_shelf_selected_index(ci)
            self._my_games_filter_focused = False
            self._launch_selected()

    def _my_game_details_options(self) -> list[dict[str, str]]:
        lk = self._my_game_details_library_key or ""
        opts: list[dict[str, str]] = [{"title": "Replace image from local file", "action": "replace_image"}]
        if lk and lk in self._hidden_library_keys:
            opts.append({"title": "Show in My Games", "action": "unhide"})
        else:
            opts.append({"title": "Hide from My Games", "action": "hide"})
        if lk:
            if lk in self._pinned_library_keys:
                opts.append({"title": "Unpin from My Pins", "action": "unpin"})
            else:
                opts.append({"title": "Pin to My Pins", "action": "pin"})
        opts.append({"title": "Back", "action": "close"})
        return opts

    def _open_my_game_details_submenu(self) -> None:
        entries = self._shelf_entries()
        if not entries:
            return
        idx = max(0, min(self._shelf_selected_index(), len(entries) - 1))
        game = entries[idx]
        lk = DashboardScene._game_library_key(game)
        if not lk:
            return
        self._my_game_details_library_key = lk
        self._my_game_details_selected_index = 0
        self._in_my_game_details_submenu = True
        cached = self._my_game_details_cache.get(lk)
        if cached:
            self._my_game_details_description = cached
            self._my_game_details_loading = False
            return
        if DashboardScene._game_store(game) == "epic":
            desc = (
                "This title is installed via the Epic Games Store. "
                "Open the Epic Launcher for the full store page and patch notes."
            )
            self._my_game_details_cache[lk] = desc
            self._my_game_details_description = desc
            self._my_game_details_loading = False
            return
        if DashboardScene._game_store(game) == "ea":
            desc = (
                "This title is linked from EA registry data. "
                "Use the EA app for updates, cloud saves, and the store page."
            )
            self._my_game_details_cache[lk] = desc
            self._my_game_details_description = desc
            self._my_game_details_loading = False
            return
        if DashboardScene._game_store(game) == "rockstar":
            desc = (
                "This title is linked from Rockstar Games registry data. "
                "Use the Rockstar Games Launcher for updates and Rockstar account features."
            )
            self._my_game_details_cache[lk] = desc
            self._my_game_details_description = desc
            self._my_game_details_loading = False
            return
        self._my_game_details_description = "Loading Steam description..."
        self._my_game_details_loading = True
        steam_id = parse_steam_appid(lk)
        if steam_id is None:
            self._my_game_details_description = "No description available."
            self._my_game_details_loading = False
            return
        threading.Thread(target=self._load_my_game_description_worker, args=(lk, steam_id), daemon=True).start()

    def _close_my_game_details_submenu(self) -> None:
        self._in_my_game_details_submenu = False
        self._my_game_details_library_key = None
        self._my_game_details_selected_index = 0
        self._my_game_details_option_rects = []
        self._my_game_details_loading = False

    def _load_my_game_description_worker(self, library_key: str, appid: int) -> None:
        desc = fetch_steam_game_description(appid)
        if not desc:
            desc = "No Steam description available for this title."
        self._my_game_details_cache[library_key] = desc
        if self._my_game_details_library_key == library_key:
            self._my_game_details_description = desc
            self._my_game_details_loading = False

    def _apply_my_game_details_action(self) -> None:
        options = self._my_game_details_options()
        if not options:
            return
        idx = max(0, min(self._my_game_details_selected_index, len(options) - 1))
        action = options[idx]["action"]
        if action == "replace_image":
            self._replace_my_game_image_from_file()
            return
        if action == "hide":
            lk = self._my_game_details_library_key
            if lk:
                self._hidden_library_keys.add(lk)
                self._save_hidden_library_keys()
                self._apply_my_games_filter()
                self._close_my_game_details_submenu()
                self._my_games_selected_index = min(
                    self._my_games_selected_index,
                    max(0, len(self._my_games_entries) - 1),
                )
                self.status_text = "Game hidden from My Games."
                self._status_timer = 2.0
            return
        if action == "unhide":
            lk = self._my_game_details_library_key
            if lk:
                self._hidden_library_keys.discard(lk)
                self._save_hidden_library_keys()
                self._apply_my_games_filter()
                self._close_my_game_details_submenu()
                self._my_games_selected_index = min(
                    self._my_games_selected_index,
                    max(0, len(self._my_games_entries) - 1),
                )
                self.status_text = "Game restored to My Games."
                self._status_timer = 2.0
            return
        if action == "pin":
            lk = self._my_game_details_library_key
            if lk:
                self._pinned_library_keys.add(lk)
                save_pinned_library_keys(self._pinned_library_keys)
                self._apply_my_pins_entries()
                self.status_text = "Pinned to My Pins."
                self._status_timer = 2.0
            return
        if action == "unpin":
            lk = self._my_game_details_library_key
            if lk:
                self._pinned_library_keys.discard(lk)
                save_pinned_library_keys(self._pinned_library_keys)
                self._apply_my_pins_entries()
                self.status_text = "Unpinned from My Pins."
                self._status_timer = 2.0
            return
        self._close_my_game_details_submenu()

    def _replace_my_game_image_from_file(self) -> None:
        lk = self._my_game_details_library_key
        if not lk:
            return
        game = self._game_by_library_key(lk)
        if not game:
            return
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            self.status_text = "File picker unavailable."
            self._status_timer = 2.0
            return
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Choose cover image",
            filetypes=[
                ("Image Files", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"),
                ("All Files", "*.*"),
            ],
        )
        root.destroy()
        if not path:
            return
        source = Path(path)
        if not source.is_file():
            self.status_text = "Selected file not found."
            self._status_timer = 2.0
            return
        project_root = Path(__file__).resolve().parents[2]
        store = DashboardScene._game_store(game)
        if store == "epic":
            cache_dir = project_root / "assets" / "cache" / "epic_headers"
            slug = epic_header_slug(lk)
        elif store == "ea":
            cache_dir = project_root / "assets" / "cache" / "ea_headers"
            slug = epic_header_slug(lk)
        elif store == "rockstar":
            cache_dir = project_root / "assets" / "cache" / "rockstar_headers"
            slug = epic_header_slug(lk)
        else:
            cache_dir = project_root / "assets" / "cache" / "steam_headers"
            slug = str(parse_steam_appid(lk) or int(game.get("appid", 0)))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.status_text = "Unable to create cache directory."
            self._status_timer = 2.0
            return
        ext = source.suffix.lower() if source.suffix else ".png"
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            ext = ".png"
        dest = cache_dir / f"{slug}{ext}"
        for old in [
            cache_dir / f"{slug}.jpg",
            cache_dir / f"{slug}.jpeg",
            cache_dir / f"{slug}.png",
            cache_dir / f"{slug}.webp",
            cache_dir / f"{slug}.bmp",
        ]:
            if old != dest and old.exists():
                try:
                    old.unlink()
                except OSError:
                    pass
        try:
            shutil.copyfile(source, dest)
            self._my_games_art_cache.pop(lk, None)
            self._invalidate_my_games_tile_scaled(lk)
            self._my_games_art_download_failed.discard(lk)
            self._set_game_header_override(lk, dest)
            game["header_image"] = str(dest.resolve())
            self._ensure_my_games_header(lk, str(dest))
            self.status_text = "Custom image applied."
            self._status_timer = 2.0
        except OSError:
            self.status_text = "Could not apply image."
            self._status_timer = 2.0

    @staticmethod
    def _app_project_root() -> Path:
        return Path(__file__).resolve().parents[2].parent

    def _hidden_games_path(self) -> Path:
        return self._app_project_root() / "config" / "hidden_games.json"

    def _load_hidden_library_keys(self) -> set[str]:
        path = self._hidden_games_path()
        if not path.is_file():
            return set()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(raw, dict):
            return set()
        keys = raw.get("library_keys")
        if not isinstance(keys, list):
            return set()
        return {str(k) for k in keys if isinstance(k, str) and k.strip()}

    def _save_hidden_library_keys(self) -> None:
        path = self._hidden_games_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            data = {"library_keys": sorted(self._hidden_library_keys)}
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _steam_input_cache_path(self) -> Path:
        return self._app_project_root() / "config" / "steam_input_cache.json"

    def _load_steam_input_cache(self) -> dict[str, str]:
        path = self._steam_input_cache_path()
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v in ("controller", "keyboard"):
                out[k] = v
        return out

    def _save_steam_input_cache(self) -> None:
        path = self._steam_input_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            path.write_text(
                json.dumps(dict(sorted(self._steam_input_cache.items())), indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _attach_steam_input_tags(self, entries: list[dict[str, Any]]) -> None:
        cache = self._steam_input_cache
        for g in entries:
            lk = DashboardScene._game_library_key(g)
            if not lk:
                g["input_kind"] = None
                continue
            aid = parse_steam_appid(lk)
            if aid is None:
                g["input_kind"] = None
                continue
            tag = cache.get(lk)
            if tag == "controller":
                g["input_kind"] = "controller"
            elif tag == "keyboard":
                g["input_kind"] = "keyboard"
            else:
                g["input_kind"] = None

    def _apply_my_games_filter(self) -> None:
        fid = self._my_games_filter_id
        hidden = self._hidden_library_keys
        master = self._my_games_master_entries
        out: list[dict[str, Any]] = []
        for g in master:
            lk = DashboardScene._game_library_key(g)
            if not lk:
                continue
            is_hidden = lk in hidden
            if fid == "hidden":
                if not is_hidden:
                    continue
            elif is_hidden:
                continue

            st = DashboardScene._game_store(g)
            ik = g.get("input_kind")

            if fid == "all":
                pass
            elif fid == "steam" and st != "steam":
                continue
            elif fid == "epic" and st != "epic":
                continue
            elif fid == "ea" and st != "ea":
                continue
            elif fid == "rockstar" and st != "rockstar":
                continue
            elif fid == "controller":
                if ik != "controller":
                    continue
            elif fid == "keyboard":
                if ik != "keyboard":
                    continue
            out.append(g)

        self._my_games_entries = out
        if self._my_games_selected_index >= len(self._my_games_entries):
            self._my_games_selected_index = max(0, len(self._my_games_entries) - 1)

    def _my_games_popup_screen_rect(self, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
        mix = max(0.0, min(1.0, self._my_games_transition_progress))
        base_panel_w = int(screen_w * 1.03)
        base_panel_h = screen_h
        scale_blend = 0.88 + (0.12 * mix)
        panel_w = max(520, int(base_panel_w * scale_blend))
        panel_h = max(420, int(base_panel_h * scale_blend))
        panel_x = (screen_w - panel_w) // 2
        panel_y = (screen_h - panel_h) // 2
        return panel_x, panel_y, panel_w, panel_h

    def _steam_input_backfill_worker(self) -> None:
        updated = False
        try:
            for g in list(self._my_games_master_entries):
                lk = DashboardScene._game_library_key(g)
                if not lk:
                    continue
                aid = parse_steam_appid(lk)
                if aid is None:
                    continue
                if lk in self._steam_input_cache:
                    continue
                supported = fetch_steam_full_controller_support(aid)
                if supported is None:
                    continue
                tag: str = "controller" if supported else "keyboard"
                self._steam_input_cache[lk] = tag
                g["input_kind"] = tag
                updated = True
            if updated:
                self._save_steam_input_cache()
                self._steam_input_refresh_pending = True
        finally:
            pass

    def _steam_header_overrides_path(self) -> Path:
        return self._app_project_root() / "config" / "steam_header_overrides.json"

    def _load_raw_steam_header_overrides(self) -> dict[str, str]:
        path = self._steam_header_overrides_path()
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k] = v.strip()
        return out

    def _write_raw_steam_header_overrides(self, data: dict[str, str]) -> None:
        path = self._steam_header_overrides_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            path.write_text(json.dumps(dict(sorted(data.items())), indent=2), encoding="utf-8")
        except OSError:
            pass

    def _normalize_header_override_storage(self, absolute_file: Path) -> str:
        root = self._app_project_root()
        try:
            return absolute_file.resolve().relative_to(root).as_posix()
        except ValueError:
            return str(absolute_file.resolve())

    def _set_game_header_override(self, library_key: str, dest: Path) -> None:
        data = self._load_raw_steam_header_overrides()
        data[sanitize_override_key(library_key)] = self._normalize_header_override_storage(dest)
        self._write_raw_steam_header_overrides(data)

    def _apply_saved_custom_covers_to_entries_list(self, entries: list[dict[str, Any]]) -> None:
        raw = self._load_raw_steam_header_overrides()
        if not raw:
            return
        root = self._app_project_root()
        installed_lk = {DashboardScene._game_library_key(g) for g in entries if DashboardScene._game_library_key(g)}
        cleaned: dict[str, str] = {}
        for key, stored in raw.items():
            if not isinstance(key, str) or not isinstance(stored, str) or not stored.strip():
                continue
            p = Path(stored)
            if not p.is_absolute():
                p = (root / p).resolve()
            else:
                p = p.resolve()
            if not p.is_file():
                continue
            cleaned[key] = self._normalize_header_override_storage(p)
            lk: str | None = None
            if key.isdigit():
                lk = f"steam:{int(key)}"
            else:
                for game in entries:
                    if sanitize_override_key(DashboardScene._game_library_key(game)) == key:
                        lk = DashboardScene._game_library_key(game)
                        break
            if lk and lk in installed_lk:
                for game in entries:
                    if DashboardScene._game_library_key(game) == lk:
                        game["header_image"] = str(p)
                        break
        if cleaned != raw:
            self._write_raw_steam_header_overrides(cleaned)

    @staticmethod
    def _prepare_my_games_header_surface(surf: pygame.Surface, max_height: int = 720) -> pygame.Surface:
        w, h = surf.get_size()
        if h <= max_height:
            return surf
        new_w = max(1, int(w * max_height / h))
        return pygame.transform.smoothscale(surf, (new_w, max_height))

    def _store_my_games_header_art(self, library_key: str, surf: pygame.Surface) -> None:
        self._my_games_art_cache[library_key] = self._prepare_my_games_header_surface(surf)
        self._invalidate_my_games_tile_scaled(library_key)

    def _ensure_my_games_header(self, library_key: str, path: str | None) -> None:
        if library_key in self._my_games_art_cache and self._my_games_art_cache[library_key] is not None:
            return
        if not path:
            if library_key.startswith(("epic:", "ea:", "rockstar:")):
                fb = self._ensure_my_games_fallback_art(library_key)
                if fb and Path(fb).is_file():
                    try:
                        self._store_my_games_header_art(library_key, pygame.image.load(str(fb)).convert())
                    except (pygame.error, OSError):
                        self._my_games_art_cache[library_key] = None
                else:
                    self._my_games_art_cache[library_key] = None
            else:
                self._my_games_art_cache[library_key] = None
            return
        image_path = path
        if path.startswith("http://") or path.startswith("https://"):
            if not library_key.startswith("steam:"):
                self._my_games_art_cache[library_key] = None
                return
            cached = DashboardScene._cached_my_games_header_path(library_key)
            if cached:
                image_path = cached
            else:
                self._my_games_art_cache[library_key] = None
                if library_key in self._my_games_art_download_failed or library_key in self._my_games_art_download_inflight:
                    return
                self._my_games_art_download_inflight.add(library_key)
                threading.Thread(
                    target=self._download_my_games_header_worker,
                    args=(library_key, path),
                    daemon=True,
                ).start()
                return
        p = Path(image_path)
        try:
            if p.is_file():
                self._store_my_games_header_art(library_key, pygame.image.load(str(p)).convert())
            else:
                fallback = self._ensure_my_games_fallback_art(library_key)
                if fallback and Path(fallback).is_file():
                    self._store_my_games_header_art(library_key, pygame.image.load(str(fallback)).convert())
                else:
                    self._my_games_art_cache[library_key] = None
        except (pygame.error, OSError):
            fallback = self._ensure_my_games_fallback_art(library_key)
            if fallback and Path(fallback).is_file():
                try:
                    self._store_my_games_header_art(library_key, pygame.image.load(str(fallback)).convert())
                except (pygame.error, OSError):
                    self._my_games_art_cache[library_key] = None
            else:
                self._my_games_art_cache[library_key] = None

    @staticmethod
    def _cached_my_games_header_path(library_key: str) -> str | None:
        project_root = Path(__file__).resolve().parents[2]
        exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        if library_key.startswith("steam:"):
            aid = parse_steam_appid(library_key)
            if aid is None:
                return None
            cache_dir = project_root / "assets" / "cache" / "steam_headers"
            candidates = [cache_dir / f"{aid}{ext}" for ext in exts]
        elif library_key.startswith("epic:"):
            slug = epic_header_slug(library_key)
            cache_dir = project_root / "assets" / "cache" / "epic_headers"
            candidates = [cache_dir / f"{slug}{ext}" for ext in exts]
        elif library_key.startswith("ea:"):
            slug = epic_header_slug(library_key)
            cache_dir = project_root / "assets" / "cache" / "ea_headers"
            candidates = [cache_dir / f"{slug}{ext}" for ext in exts]
        elif library_key.startswith("rockstar:"):
            slug = epic_header_slug(library_key)
            cache_dir = project_root / "assets" / "cache" / "rockstar_headers"
            candidates = [cache_dir / f"{slug}{ext}" for ext in exts]
        else:
            return None
        for dest in candidates:
            if dest.is_file() and DashboardScene._is_likely_image_file(dest):
                return str(dest)
        return None

    @staticmethod
    def _is_likely_image_file(path: Path) -> bool:
        try:
            data = path.read_bytes()[:16]
        except OSError:
            return False
        if len(data) < 8:
            return False
        if data.startswith(b"\xFF\xD8\xFF"):  # JPEG
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
            return True
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP
            return True
        return False

    @staticmethod
    def _download_my_games_header(library_key: str, url: str, title: str | None = None) -> str | None:
        appid = parse_steam_appid(library_key)
        if appid is None:
            return None
        project_root = Path(__file__).resolve().parents[2]
        cache_dir = project_root / "assets" / "cache" / "steam_headers"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        dest = cache_dir / f"{appid}.jpg"
        if dest.is_file():
            return str(dest)
        alt_urls = [
            url,
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_hero.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_616x353.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_231x87.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/capsule_616x353.jpg",
            f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/capsule_231x87.jpg",
        ]
        seen: set[str] = set()
        for candidate in alt_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                with urllib.request.urlopen(candidate, timeout=2.0) as response:
                    data = response.read()
                if not data:
                    continue
                dest.write_bytes(data)
                return str(dest)
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                continue
        if DashboardScene._download_from_steamgriddb(appid, dest, title):
            return str(dest)
        return None

    @staticmethod
    def _download_from_steamgriddb(appid: int, dest: Path, title: str | None = None) -> bool:
        api_key = os.environ.get("STEAMGRIDDB_API_KEY", "").strip()
        if not api_key:
            return False
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        def _read_rows(api_url: str) -> list[dict[str, Any]]:
            req = urllib.request.Request(api_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    payload = response.read()
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                return []
            try:
                parsed = json.loads(payload.decode("utf-8", errors="ignore"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return []
            rows = parsed.get("data")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
            return []

        def _download_first_image(rows: list[dict[str, Any]]) -> bool:
            for row in rows:
                image_url = row.get("url")
                if not isinstance(image_url, str) or not image_url:
                    continue
                try:
                    with urllib.request.urlopen(image_url, timeout=3.0) as response:
                        image_data = response.read()
                    if not image_data:
                        continue
                    dest.write_bytes(image_data)
                    return True
                except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                    continue
            return False

        rows = _read_rows(
            f"https://www.steamgriddb.com/api/v2/grids/steam/{appid}"
            "?types=static&dimensions=600x900,660x930,342x482"
        )
        if _download_first_image(rows):
            return True

        # Some titles are missing steam-appid mappings on SGDB; fallback to name lookup.
        cleaned = (title or "").strip()
        if cleaned:
            variants = DashboardScene._steamgriddb_title_variants(cleaned)
            seen_queries: set[str] = set()
            for query in variants:
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                q = urllib.parse.quote(query)
                games = _read_rows(f"https://www.steamgriddb.com/api/v2/search/autocomplete/{q}")
                for game in games:
                    gid = game.get("id")
                    if not isinstance(gid, int):
                        continue
                    game_rows = _read_rows(
                        f"https://www.steamgriddb.com/api/v2/grids/game/{gid}"
                        "?types=static&dimensions=600x900,660x930,342x482"
                    )
                    if _download_first_image(game_rows):
                        return True
        return False

    @staticmethod
    def _steamgriddb_title_variants(title: str) -> list[str]:
        variants = [title.strip()]
        lowered = title.strip()
        # Remove parenthetical qualifiers like "(Demo)", "(Open Beta)", etc.
        no_paren = lowered
        while "(" in no_paren and ")" in no_paren:
            start = no_paren.rfind("(")
            end = no_paren.find(")", start)
            if end == -1:
                break
            no_paren = (no_paren[:start] + no_paren[end + 1 :]).strip()
        if no_paren and no_paren not in variants:
            variants.append(no_paren)

        # Trim common suffix tokens that hurt matches.
        tokens = [" demo", " open beta", " beta", " playtest", " trial"]
        compact = no_paren or lowered
        for token in tokens:
            if compact.casefold().endswith(token):
                trimmed = compact[: -len(token)].strip(" -:_")
                if trimmed and trimmed not in variants:
                    variants.append(trimmed)
        return variants

    def _download_my_games_header_worker(self, library_key: str, url: str) -> None:
        title = self._my_games_titles.get(library_key, "").strip()
        if not title:
            for game in self._my_games_master_entries:
                if DashboardScene._game_library_key(game) == library_key:
                    title = str(game.get("title", "")).strip()
                    break
        if not title:
            for game in self._my_games_entries:
                if DashboardScene._game_library_key(game) == library_key:
                    title = str(game.get("title", "")).strip()
                    break
        result = self._download_my_games_header(library_key, url, title=title or None)
        self._my_games_art_download_results.put((library_key, result))

    def _drain_my_games_art_downloads(self) -> None:
        while True:
            try:
                library_key, path = self._my_games_art_download_results.get_nowait()
            except queue.Empty:
                break
            self._my_games_art_download_inflight.discard(library_key)
            if not path:
                fallback = self._ensure_my_games_fallback_art(library_key)
                if fallback:
                    path = fallback
                else:
                    self._my_games_art_download_failed.add(library_key)
                    continue
            p = Path(path)
            try:
                if p.is_file():
                    self._store_my_games_header_art(library_key, pygame.image.load(str(p)).convert())
                    self._my_games_art_download_failed.discard(library_key)
                    self._game_art_scan_applied += 1
                    self._game_art_scan_resolved_ids.add(library_key)
                else:
                    fallback = self._ensure_my_games_fallback_art(library_key)
                    if fallback and Path(fallback).is_file():
                        self._store_my_games_header_art(library_key, pygame.image.load(str(fallback)).convert())
                        self._my_games_art_download_failed.discard(library_key)
                        self._game_art_scan_applied += 1
                        self._game_art_scan_resolved_ids.add(library_key)
                    else:
                        self._my_games_art_download_failed.add(library_key)
            except (pygame.error, OSError):
                fallback = self._ensure_my_games_fallback_art(library_key)
                if fallback and Path(fallback).is_file():
                    try:
                        self._store_my_games_header_art(library_key, pygame.image.load(str(fallback)).convert())
                        self._my_games_art_download_failed.discard(library_key)
                        self._game_art_scan_applied += 1
                        self._game_art_scan_resolved_ids.add(library_key)
                    except (pygame.error, OSError):
                        self._my_games_art_download_failed.add(library_key)
                else:
                    self._my_games_art_download_failed.add(library_key)
        if (
            not self._game_art_scan_in_progress
            and self._game_art_scan_total > 0
            and self._game_art_scan_completed >= self._game_art_scan_total
        ):
            unresolved_ids = self._game_art_scan_ids - self._game_art_scan_resolved_ids
            self._game_art_scan_failed = len(unresolved_ids)

    def _ensure_my_games_fallback_art(self, library_key: str) -> str | None:
        project_root = Path(__file__).resolve().parents[2]
        if library_key.startswith("epic:"):
            cache_dir = project_root / "assets" / "cache" / "epic_headers"
            slug = epic_header_slug(library_key)
        elif library_key.startswith("ea:"):
            cache_dir = project_root / "assets" / "cache" / "ea_headers"
            slug = epic_header_slug(library_key)
        elif library_key.startswith("rockstar:"):
            cache_dir = project_root / "assets" / "cache" / "rockstar_headers"
            slug = epic_header_slug(library_key)
        else:
            cache_dir = project_root / "assets" / "cache" / "steam_headers"
            aid = parse_steam_appid(library_key)
            slug = str(aid) if aid is not None else "0"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        dest = cache_dir / f"{slug}.png"
        if dest.is_file():
            return str(dest)

        surf = pygame.Surface((600, 900))
        font_family = self.theme["typography"]["font_family"]
        title_font = pygame.font.SysFont(font_family, 42, bold=True)
        small_font = pygame.font.SysFont(font_family, 28)
        title = self._title_for_library_key(library_key) or "Unknown Game"
        wrapped = self._wrap_text_lines(title, title_font, 540, max_lines=4)
        if library_key.startswith("epic:"):
            surf.fill(pygame.Color(22, 24, 32))
            pygame.draw.rect(surf, pygame.Color(44, 52, 88), pygame.Rect(0, 0, 600, 220))
            pygame.draw.rect(surf, pygame.Color(130, 70, 200), pygame.Rect(0, 848, 600, 52))
            y = 290
            for line in wrapped:
                line_s = title_font.render(line, True, pygame.Color(240, 246, 255))
                rect = line_s.get_rect(center=(300, y))
                surf.blit(line_s, rect.topleft)
                y += 56
            sub = small_font.render("Epic Games", True, pygame.Color(220, 229, 238))
            surf.blit(sub, sub.get_rect(center=(300, 790)).topleft)
        elif library_key.startswith("ea:"):
            surf.fill(pygame.Color(18, 22, 28))
            pygame.draw.rect(surf, pygame.Color(28, 36, 48), pygame.Rect(0, 0, 600, 220))
            pygame.draw.rect(surf, pygame.Color(220, 92, 52), pygame.Rect(0, 848, 600, 52))
            y = 290
            for line in wrapped:
                line_s = title_font.render(line, True, pygame.Color(248, 248, 252))
                rect = line_s.get_rect(center=(300, y))
                surf.blit(line_s, rect.topleft)
                y += 56
            sub = small_font.render("EA app", True, pygame.Color(220, 225, 232))
            surf.blit(sub, sub.get_rect(center=(300, 790)).topleft)
        elif library_key.startswith("rockstar:"):
            surf.fill(pygame.Color(16, 14, 12))
            pygame.draw.rect(surf, pygame.Color(42, 38, 32), pygame.Rect(0, 0, 600, 220))
            pygame.draw.rect(surf, pygame.Color(230, 186, 48), pygame.Rect(0, 848, 600, 52))
            y = 290
            for line in wrapped:
                line_s = title_font.render(line, True, pygame.Color(250, 246, 238))
                rect = line_s.get_rect(center=(300, y))
                surf.blit(line_s, rect.topleft)
                y += 56
            sub = small_font.render("Rockstar Games", True, pygame.Color(210, 208, 200))
            surf.blit(sub, sub.get_rect(center=(300, 790)).topleft)
        else:
            surf.fill(pygame.Color(32, 44, 62))
            pygame.draw.rect(surf, pygame.Color(68, 99, 136), pygame.Rect(0, 0, 600, 220))
            pygame.draw.rect(surf, pygame.Color(86, 202, 96), pygame.Rect(0, 848, 600, 52))
            y = 290
            for line in wrapped:
                line_s = title_font.render(line, True, pygame.Color(240, 246, 255))
                rect = line_s.get_rect(center=(300, y))
                surf.blit(line_s, rect.topleft)
                y += 56
            aid_num = parse_steam_appid(library_key) or 0
            aid = small_font.render(f"Steam App {aid_num}", True, pygame.Color(220, 229, 238))
            surf.blit(aid, aid.get_rect(center=(300, 790)).topleft)
        try:
            pygame.image.save(surf, str(dest))
        except (pygame.error, OSError):
            return None
        return str(dest)

    def _title_for_library_key(self, library_key: str) -> str:
        title = self._my_games_titles.get(library_key, "").strip()
        if title:
            return title
        for game in self._my_games_master_entries:
            if DashboardScene._game_library_key(game) == library_key:
                return str(game.get("title", "")).strip()
        for game in self._my_games_entries:
            if DashboardScene._game_library_key(game) == library_key:
                return str(game.get("title", "")).strip()
        return ""

    @staticmethod
    def _wrap_text_lines(text: str, font: pygame.font.Font, max_width: int, max_lines: int) -> list[str]:
        words = [w for w in text.split() if w]
        if not words:
            return [text[:24] or "Untitled"]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if font.size(trial)[0] <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
                if len(lines) >= max_lines - 1:
                    break
        if len(lines) < max_lines:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        if len(lines) == max_lines and len(words) > 1:
            last = lines[-1]
            if font.size(last)[0] > max_width:
                while last and font.size(last + "...")[0] > max_width:
                    last = last[:-1]
                lines[-1] = (last + "...").rstrip()
        return lines

    def _start_scan_for_game_art(self) -> None:
        if self._game_art_scan_in_progress:
            self.status_text = "Artwork scan already running."
            self._status_timer = 1.6
            return
        self._game_art_scan_in_progress = True
        self._game_art_scan_total = 0
        self._game_art_scan_completed = 0
        self._game_art_scan_applied = 0
        self._game_art_scan_new = 0
        self._game_art_scan_failed = 0
        self._game_art_scan_ids.clear()
        self._game_art_scan_resolved_ids.clear()
        self.status_text = "Scanning game art..."
        self._status_timer = 2.0
        threading.Thread(target=self._scan_for_game_art_worker, daemon=True).start()

    def _scan_for_game_art_worker(self) -> None:
        downloaded = 0
        games: list[dict[str, Any]] = []
        try:
            steam = list_installed_steam_games()
            epic = list_installed_epic_games()
            ea = list_installed_ea_games()
            rockstar = list_installed_rockstar_games()
            games = sorted(
                steam + epic + ea + rockstar,
                key=lambda g: str(g.get("title", "")).casefold(),
            )
            self._apply_saved_custom_covers_to_entries_list(games)
            new_titles = {
                DashboardScene._game_library_key(game): str(game.get("title", "")).strip()
                for game in games
                if DashboardScene._game_library_key(game)
            }
            self._my_games_titles.update(new_titles)
            self._game_art_scan_total = len(games)
            for game in games:
                lk = DashboardScene._game_library_key(game)
                self._game_art_scan_completed += 1
                if not lk:
                    self._game_art_scan_failed += 1
                    continue
                self._game_art_scan_ids.add(lk)
                if DashboardScene._game_store(game) in ("epic", "ea", "rockstar"):
                    header = str(game.get("header_image") or "").strip()
                    if header and Path(header).is_file():
                        self._my_games_art_download_results.put((lk, header))
                    else:
                        self._my_games_art_download_results.put((lk, None))
                    continue
                cached = DashboardScene._cached_my_games_header_path(lk)
                if cached:
                    self._my_games_art_download_results.put((lk, cached))
                    continue
                header = str(game.get("header_image") or "").strip()
                if header and not (header.startswith("http://") or header.startswith("https://")):
                    p = Path(header)
                    if p.is_file():
                        self._my_games_art_download_results.put((lk, str(p)))
                        continue
                    header = ""
                appid = parse_steam_appid(lk) or int(game.get("appid", 0))
                if not header:
                    header = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
                result = self._download_my_games_header(
                    lk,
                    header,
                    title=str(game.get("title", "")).strip() or None,
                )
                if result:
                    downloaded += 1
                    self._my_games_art_download_results.put((lk, result))
                else:
                    self._my_games_art_download_results.put((lk, None))
            self._game_art_scan_new = downloaded
        finally:
            self._game_art_scan_in_progress = False
            self.status_text = (
                f"Artwork scan complete ({downloaded} new)."
                if downloaded > 0
                else "Artwork scan complete."
            )
            self._status_timer = 2.5

    def _draw_my_games_submenu_overlay(self, screen: pygame.Surface) -> None:
        mix = max(0.0, min(1.0, self._my_games_transition_progress))
        if mix <= 0.0 and not self._library_shelf_active():
            return
        if mix <= 0.0 and self._library_shelf_active():
            mix = 1.0

        width = screen.get_width()
        height = screen.get_height()
        screen_size = (width, height)
        if self._my_games_dim_surface_size != screen_size:
            self._my_games_dim_surface = pygame.Surface(screen_size, pygame.SRCALPHA)
            self._my_games_dim_surface_size = screen_size
        dim = self._my_games_dim_surface
        if dim is not None:
            dim.fill((0, 0, 0, 0))
            dim.fill((0, 0, 0, int(175 * mix)))
            screen.blit(dim, (0, 0))

        base_panel_w = int(width * 1.03)
        base_panel_h = height
        scale = 0.88 + (0.12 * mix)
        panel_w = max(520, int(base_panel_w * scale))
        panel_h = max(420, int(base_panel_h * scale))
        panel_x = (width - panel_w) // 2
        panel_y = (height - panel_h) // 2

        panel_size = (panel_w, panel_h)
        if self._my_games_popup_surface_size != panel_size:
            self._my_games_popup_surface = pygame.Surface(panel_size)
            self._my_games_popup_surface_size = panel_size
        popup_layer = self._my_games_popup_surface
        if popup_layer is None:
            return
        if self._my_games_loading:
            draw_my_games_loading_panel(
                popup_layer,
                self.theme,
                self._my_games_loading_spin,
                full_screen=True,
            )
        else:
            entries = self._shelf_entries()
            sel = self._shelf_selected_index()
            is_pins = self._library_shelf_kind == "pins"
            draw_my_games_submenu(
                popup_layer,
                self.theme,
                entries,
                sel,
                self._my_games_art_cache,
                self._ensure_my_games_header,
                scaled_art_cache=self._my_games_tile_art_scaled,
                filter_id=self._my_games_filter_id,
                filter_menu_open=self._my_games_filter_menu_open,
                filter_menu_selected_index=self._my_games_filter_menu_index,
                filter_focused=self._my_games_filter_focused,
                full_screen=True,
                shelf_title="my pins" if is_pins else "my games",
                show_filter_ui=not is_pins,
                empty_message=(
                    "Pin games from My Games — press X on a title."
                    if is_pins
                    else "No games match this filter."
                ),
            )
        screen.blit(popup_layer, (panel_x, panel_y))

    def _draw_my_game_details_submenu_overlay(self, screen: pygame.Surface) -> None:
        lk = self._my_game_details_library_key
        if not lk:
            return
        game = self._game_by_library_key(lk)
        store = DashboardScene._game_store(game or {})
        game_title = self._title_for_library_key(lk)
        if not game_title:
            if store == "epic":
                game_title = "Epic Game"
            elif store == "ea":
                game_title = "EA Game"
            elif store == "rockstar":
                game_title = "Rockstar Game"
            else:
                game_title = f"Steam App {parse_steam_appid(lk) or 0}"
        options = self._my_game_details_options()
        self._my_game_details_option_rects = []

        width = screen.get_width()
        height = screen.get_height()
        panel_w = min(1180, int(width * 0.82))
        panel_h = min(760, int(height * 0.84))
        panel_x = (width - panel_w) // 2
        panel_y = (height - panel_h) // 2

        dim = pygame.Surface((width, height), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 165))
        screen.blit(dim, (0, 0))

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((245, 248, 249, 245))
        screen.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(screen, pygame.Color("#bfc9cc"), pygame.Rect(panel_x, panel_y, panel_w, panel_h), width=2)

        header_h = 56
        header_rect = pygame.Rect(panel_x, panel_y, panel_w, header_h)
        pygame.draw.rect(screen, pygame.Color("#9fb2b7"), header_rect)
        title_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 30)
        body_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 24)

        title = title_font.render(game_title, True, pygame.Color("#ffffff"))
        screen.blit(title, (panel_x + 18, panel_y + (header_h - title.get_height()) // 2))

        pad_x = 20
        pad_bottom = 16
        content_x = panel_x + pad_x
        content_w = panel_w - 2 * pad_x
        body_top = panel_y + header_h + 14

        desc_heading = "steam description" if store == "steam" else "description"
        desc_label = body_font.render(desc_heading, True, pygame.Color("#44505a"))
        screen.blit(desc_label, (content_x, body_top))

        option_count = len(options)
        option_gap = 4
        list_gap_above = 14
        min_row_h = 38
        max_row_h = 50
        preferred_row_h = 46 if option_count <= 4 else 40
        options_block_h = option_count * preferred_row_h + max(0, option_count - 1) * option_gap
        list_bottom = panel_y + panel_h - pad_bottom
        list_top = list_bottom - options_block_h
        row_h = preferred_row_h
        if list_top < body_top + desc_label.get_height() + 48:
            list_top = body_top + desc_label.get_height() + 48
            available = list_bottom - list_top
            if option_count > 0:
                row_h = max(
                    min_row_h,
                    min(max_row_h, (available - max(0, option_count - 1) * option_gap) // option_count),
                )
                options_block_h = option_count * row_h + max(0, option_count - 1) * option_gap
                list_top = list_bottom - options_block_h

        desc_rect = pygame.Rect(
            content_x,
            body_top + desc_label.get_height() + 8,
            content_w,
            max(60, list_top - list_gap_above - (body_top + desc_label.get_height() + 8)),
        )
        pygame.draw.rect(screen, pygame.Color("#e9eef0"), desc_rect)
        pygame.draw.rect(screen, pygame.Color("#ccd5d9"), desc_rect, width=1)
        desc_text = self._my_game_details_description
        if self._my_game_details_loading:
            desc_text = "Loading Steam description..." if store == "steam" else "Loading..."
        line_h = body_font.get_linesize()
        max_desc_lines = max(1, (desc_rect.h - 16) // line_h)
        lines = self._wrap_text_lines(desc_text, body_font, desc_rect.w - 24, max_lines=max_desc_lines)
        ty = desc_rect.y + 12
        for line in lines:
            if ty + line_h > desc_rect.bottom - 6:
                break
            surf = body_font.render(line, True, pygame.Color("#2e373d"))
            screen.blit(surf, (desc_rect.x + 12, ty))
            ty += surf.get_height() + 6

        item_font_size = 26 if row_h >= 44 else 22
        item_font = pygame.font.SysFont(self.theme["typography"]["font_family"], item_font_size)
        label_pad_x = 14
        max_label_w = content_w - 2 * label_pad_x

        for idx, opt in enumerate(options):
            row_y = list_top + idx * (row_h + option_gap)
            row = pygame.Rect(content_x, row_y, content_w, row_h)
            self._my_game_details_option_rects.append(row)
            is_sel = idx == self._my_game_details_selected_index
            fill = pygame.Color("#52c425") if is_sel else pygame.Color("#eef2f3")
            fg = pygame.Color("#ffffff") if is_sel else pygame.Color("#465156")
            pygame.draw.rect(screen, fill, row)
            label_text = opt["title"]
            label = item_font.render(label_text, True, fg)
            while label_text and label.get_width() > max_label_w:
                label_text = label_text[:-1]
                label = item_font.render(label_text + "…", True, fg)
            screen.blit(label, (row.x + label_pad_x, row.y + (row.height - label.get_height()) // 2))

    def _draw_games_panel(self, screen: pygame.Surface) -> None:
        self._games_tile_rects = build_slot_rects(screen.get_width(), screen.get_height())
        draw_games_panel(screen, self.theme, self._games_selected_index, self._games_tile_rects)

    def _games_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._games_tile_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _apply_guide_command(self, command: str | None) -> None:
        if not command:
            return
        if command.startswith("status:"):
            self.status_text = command[7:]
            self._status_timer = 2.0
            return
        if command.startswith("hub:"):
            hub_name = command[4:]
            if hub_name in self.hubs:
                self._set_hub(self.hubs.index(hub_name))
            return
        if command == "my_games":
            if "Games" in self.hubs:
                self._set_hub(self.hubs.index("Games"))
            self._open_my_games_submenu()
            return
        if command == "switch_display":
            if self.on_switch_display is not None:
                self.on_switch_display()
                self.status_text = "Switched display."
                self._status_timer = 2.0
            return
        if command == "power_menu":
            self._in_power_menu = True
            self._power_selected_index = len(self._power_options) - 1
            self._power_transition_progress = 0.0
            self._power_transition_target = 1.0
            return
        if command == "exit_app":
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _set_hub(self, index: int) -> None:
        if not 0 <= index < len(self.hubs):
            return
        if self._hub_transition_active or index == self.hub_index:
            return
        # Match top bar left → right: moving to a tab further right slides the new hub in
        # from the right; moving left slides it in from the left (no ring “shortest path”).
        self._hub_transition_direction = 1 if index > self.hub_index else -1
        play_hub_page_sound(self._hub_transition_direction)
        self._hub_transition_from_index = self.hub_index
        self._hub_transition_to_index = index
        self._hub_transition_progress = 0.0
        self._hub_transition_active = True

    def _hub_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._hub_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _build_hub_tiles(self, games: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        first = games[0] if games else {}
        return {
            "Home": [],
            "Games": games,
            "Apps": [
                {
                    "title": "Calculator",
                    "command": "calc.exe",
                    "args": [],
                    "cwd": "",
                },
                {
                    "title": "Notepad",
                    "command": "notepad.exe",
                    "args": [],
                    "cwd": "",
                },
                first or {
                    "title": "Command Prompt",
                    "command": "cmd.exe",
                    "args": ["/c", "start"],
                    "cwd": "",
                },
            ],
            "Settings": [
                {
                    "title": "Display",
                    "icon": "display",
                    "action": "open_display_submenu",
                },
                {
                    "title": "Bluetooth",
                    "command": "cmd.exe",
                    "args": ["/c", "start ms-settings:bluetooth"],
                    "cwd": "",
                },
                {
                    "title": "Sound",
                    "icon": "sound",
                    "command": "cmd.exe",
                    "args": ["/c", "start ms-settings:sound"],
                    "cwd": "",
                },
                {
                    "title": "Network",
                    "icon": "network",
                    "command": "cmd.exe",
                    "args": ["/c", "start ms-settings:network"],
                    "cwd": "",
                },
                {
                    "title": "System",
                    "icon": "system",
                    "action": "open_system_info_submenu",
                },
                {
                    "title": "Personalization",
                    "icon": "personalization",
                    "action": "open_art_submenu",
                },
                {
                    "title": "Coming Soon",
                },
                {
                    "title": "Power",
                    "icon": "power",
                    "action": "open_power_menu",
                },
            ],
        }

    def _active_hub(self) -> str:
        return self.hubs[self.hub_index]

    @staticmethod
    def _settings_slot_count() -> int:
        return 8

    @staticmethod
    def _display_submenu_options() -> list[dict[str, Any]]:
        return [
            {
                "title": "Switch Display",
                "action": "switch_display",
                "description": "Cycle to the next monitor.",
            },
            {
                "title": "Change Display Options",
                "command": "cmd.exe",
                "args": ["/c", "start ms-settings:display"],
                "cwd": "",
                "description": "Open Windows display settings.",
            },
        ]

    def _art_submenu_options(self) -> list[dict[str, Any]]:
        return [
            {
                "title": "Change Gamertag",
                "action": "edit_gamertag",
                "description": "Updates your name on the Xbox Guide player tab.",
            },
            {
                "title": "Change Gamerpic",
                "action": "pick_gamerpic",
                "description": "Choose an image for the emblem in the Xbox Guide header.",
            },
            {
                "title": "Scan for game art",
                "action": "scan_game_art",
                "description": "Check Steam first, then SteamGridDB fallback.",
            },
            {
                "title": "JerLauncher Theme",
                "action": "open_jerlauncher_theme_submenu",
                "description": "Choose a dashboard theme or return to JerLauncher core.",
            },
        ]

    @staticmethod
    def _jerlauncher_theme_submenu_options() -> list[dict[str, Any]]:
        return [
            {
                "title": "Pick a New Theme",
                "action": "pick_theme",
                "description": "Select a theme package (.zip) to use on startup.",
            },
            {
                "title": "Reset to Core",
                "action": "reset_to_core",
                "description": "Return to the JerLauncher core launcher on next boot.",
            },
        ]

    def _personalization_submenu_options(self) -> list[dict[str, Any]]:
        if self._in_jerlauncher_theme_submenu:
            return self._jerlauncher_theme_submenu_options()
        return self._art_submenu_options()

    def _apply_profile_to_guide(self) -> None:
        profile = load_profile()
        pic = gamerpic_absolute(profile.get("gamerpic"))
        self.guide.set_profile(profile.get("gamertag", DEFAULT_GAMERTAG), pic)

    def _save_gamertag_edit(self) -> None:
        tag = self._profile_edit_buffer.strip() or DEFAULT_GAMERTAG
        profile = load_profile()
        save_profile(tag, profile.get("gamerpic", ""))
        self._apply_profile_to_guide()
        self._profile_edit_mode = None
        self.status_text = f"Gamertag set to {tag}."
        self._status_timer = 2.0

    def _pick_gamerpic_file(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            self.status_text = "File picker is not available."
            self._status_timer = 2.0
            return

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        chosen = filedialog.askopenfilename(
            title="Choose Gamerpic",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        if not chosen:
            return
        try:
            filename = copy_gamerpic_file(Path(chosen))
        except OSError as exc:
            self.status_text = f"Could not save gamerpic: {exc}"
            self._status_timer = 2.5
            return
        profile = load_profile()
        save_profile(profile.get("gamertag", DEFAULT_GAMERTAG), filename)
        self._apply_profile_to_guide()
        self._gamerpic_grid_index = 0
        self.status_text = "Gamerpic updated."
        self._status_timer = 2.0

    def _enter_settings_submenu(self, kind: str) -> None:
        self._settings_submenu_return_index = self._settings_selected_index
        self._last_settings_submenu = kind
        self._display_transition_target = 1.0

    def _close_settings_list_submenu(self) -> None:
        self._in_display_submenu = False
        self._in_system_info_submenu = False
        self._in_art_submenu = False
        self._in_jerlauncher_theme_submenu = False
        self._profile_edit_mode = None
        self._settings_submenu_focus = "sidebar"
        self._gamerpic_grid_engaged = False
        self._display_selected_index = 0
        self._settings_selected_index = self._settings_submenu_return_index
        self._display_transition_target = 0.0

    def _settings_submenu_transitioning(self) -> bool:
        if self._active_hub() != "Settings":
            return False
        return abs(self._display_transition_progress - self._display_transition_target) > 0.02

    def _active_settings_submenu_kind(self) -> str | None:
        if self._in_system_info_submenu:
            return "system"
        if self._in_art_submenu:
            return "personalization"
        if self._in_display_submenu:
            return "display"
        if self._display_transition_progress > 0.0 and self._last_settings_submenu:
            return self._last_settings_submenu
        return None

    def _move_settings_submenu_selection(self, delta: int) -> None:
        if self._in_display_submenu:
            options = self._display_submenu_options()
        elif self._in_art_submenu:
            options = self._personalization_submenu_options()
        else:
            return
        if not options:
            return
        max_index = len(options) - 1
        next_index = max(0, min(max_index, self._display_selected_index + delta))
        if next_index == self._display_selected_index:
            return
        self._display_selected_index = next_index
        self._leave_gamerpic_grid_if_needed()

    def _leave_gamerpic_grid_if_needed(self) -> None:
        if self._current_settings_submenu_tile().get("action") == "pick_gamerpic":
            return
        self._gamerpic_grid_engaged = False
        if self._profile_edit_mode != "gamertag":
            self._settings_submenu_focus = "sidebar"

    def _engage_gamerpic_grid(self) -> None:
        self._gamerpic_grid_engaged = True
        self._settings_submenu_focus = "panel"
        self._sync_gamerpic_grid_index()

    def _gamerpic_grid_is_active(self) -> bool:
        if not self._in_art_submenu or not self._gamerpic_grid_engaged:
            return False
        return self._current_settings_submenu_tile().get("action") == "pick_gamerpic"

    def _current_settings_submenu_tile(self) -> dict[str, Any]:
        if self._in_display_submenu:
            options = self._display_submenu_options()
        else:
            options = self._personalization_submenu_options()
        idx = max(0, min(self._display_selected_index, len(options) - 1))
        return options[idx]

    def _settings_submenu_needs_panel(self, tile: dict[str, Any]) -> bool:
        action = tile.get("action")
        if action in {"pick_gamerpic", "edit_gamertag"}:
            return True
        return bool(tile.get("command")) and action != "switch_display"

    def _handle_settings_submenu_select(self) -> None:
        tile = self._current_settings_submenu_tile()
        tile_action = tile.get("action")

        if self._settings_submenu_focus == "sidebar":
            if tile_action == "pick_gamerpic":
                if not self._gamerpic_grid_engaged:
                    self._engage_gamerpic_grid()
                else:
                    self._apply_gamerpic_grid_selection()
                return
            if self._settings_submenu_needs_panel(tile):
                self._settings_submenu_focus = "panel"
                if tile_action == "edit_gamertag":
                    self._profile_edit_mode = "gamertag"
                    self._profile_edit_buffer = load_profile().get("gamertag", DEFAULT_GAMERTAG)
                return
            if tile_action == "switch_display":
                if self.on_switch_display is not None:
                    self.on_switch_display()
                    self.status_text = "Switched display."
                    self._status_timer = 2.0
                return
            if tile_action == "scan_game_art":
                self._start_scan_for_game_art()
                return
            if tile_action == "open_jerlauncher_theme_submenu":
                self._in_jerlauncher_theme_submenu = True
                self._display_selected_index = 0
                return
            if tile_action == "pick_theme":
                if self.on_choose_theme is not None:
                    self.on_choose_theme()
                else:
                    self.status_text = "Theme picker is not available."
                    self._status_timer = 2.0
                return
            if tile_action == "reset_to_core":
                if self.on_back_to_core is not None:
                    self.on_back_to_core()
                else:
                    self.status_text = "Core mode is not available."
                    self._status_timer = 2.0
                return
            if tile.get("command"):
                try:
                    self.launcher.launch(tile)
                    self.status_text = f"Launching: {tile.get('title', 'Unknown')}"
                except LaunchError as exc:
                    self.status_text = str(exc)
                self._status_timer = 2.5
            return

        if tile_action == "edit_gamertag":
            if self._profile_edit_mode == "gamertag":
                self._save_gamertag_edit()
            else:
                self._profile_edit_mode = "gamertag"
                self._profile_edit_buffer = load_profile().get("gamertag", DEFAULT_GAMERTAG)
            return
        if tile_action == "pick_gamerpic":
            self._apply_gamerpic_grid_selection()
            return
        if tile_action == "switch_display":
            if self.on_switch_display is not None:
                self.on_switch_display()
                self.status_text = "Switched display."
                self._status_timer = 2.0
            return
        if tile_action == "scan_game_art":
            self._start_scan_for_game_art()
            return
        if tile_action == "pick_theme":
            if self.on_choose_theme is not None:
                self.on_choose_theme()
            else:
                self.status_text = "Theme picker is not available."
                self._status_timer = 2.0
            return
        if tile_action == "reset_to_core":
            if self.on_back_to_core is not None:
                self.on_back_to_core()
            else:
                self.status_text = "Core mode is not available."
                self._status_timer = 2.0
            return
        if tile.get("command"):
            try:
                self.launcher.launch(tile)
                self.status_text = f"Launching: {tile.get('title', 'Unknown')}"
            except LaunchError as exc:
                self.status_text = str(exc)
            self._status_timer = 2.5

    def _is_gamerpic_panel_active(self) -> bool:
        return self._gamerpic_grid_is_active()

    def _gamerpic_grid_dims(self) -> tuple[int, int]:
        count = len(gamerpic_grid_slots())
        cols = GAMERPIC_GRID_COLS
        rows = max(1, (count + cols - 1) // cols)
        return cols, rows

    def _sync_gamerpic_grid_index(self) -> None:
        profile_rel = load_profile().get("gamerpic", "").strip()
        for idx, slot in enumerate(gamerpic_grid_slots()):
            if slot.get("custom"):
                if profile_rel == CUSTOM_GAMERPIC_REL:
                    self._gamerpic_grid_index = idx
                    return
                continue
            if profile_rel and slot.get("rel") == profile_rel:
                self._gamerpic_grid_index = idx
                return
        self._gamerpic_grid_index = 0

    def _gamerpic_grid_nav(self, dx: int, dy: int) -> bool:
        if not self._gamerpic_grid_is_active():
            return False
        slots = gamerpic_grid_slots()
        if not slots:
            return False
        cols, rows = self._gamerpic_grid_dims()
        row = self._gamerpic_grid_index // cols
        col = self._gamerpic_grid_index % cols
        col = max(0, min(cols - 1, col + dx))
        row = max(0, min(rows - 1, row + dy))
        new_index = row * cols + col
        if new_index >= len(slots):
            new_index = len(slots) - 1
        self._gamerpic_grid_index = new_index
        return True

    def _gamerpic_grid_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        if not self._gamerpic_grid_is_active():
            return None
        for idx, rect in enumerate(self._gamerpic_grid_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _gamerpic_thumb(self, rel_path: str, size: int) -> pygame.Surface | None:
        cache_key = f"{rel_path}@{size}"
        cached = self._gamerpic_thumb_cache.get(cache_key)
        if cached is not None:
            return cached
        path = gamerpic_absolute(rel_path)
        if path is None:
            return None
        try:
            image = pygame.image.load(str(path)).convert_alpha()
            thumb = pygame.transform.smoothscale(image, (size, size))
            self._gamerpic_thumb_cache[cache_key] = thumb
            return thumb
        except (pygame.error, FileNotFoundError):
            return None

    def _apply_gamerpic_grid_selection(self) -> None:
        slots = gamerpic_grid_slots()
        if not slots or self._gamerpic_grid_index >= len(slots):
            return
        slot = slots[self._gamerpic_grid_index]
        if slot.get("custom"):
            self._pick_gamerpic_file()
            return
        rel = str(slot.get("rel", "")).strip()
        if not rel:
            return
        profile = load_profile()
        save_profile(profile.get("gamertag", DEFAULT_GAMERTAG), rel)
        self._apply_profile_to_guide()
        self.status_text = "Gamerpic updated."
        self._status_timer = 2.0

    @staticmethod
    def _draw_controller_selection_box(
        screen: pygame.Surface,
        rect: pygame.Rect,
        *,
        pulse: bool = True,
    ) -> None:
        """Xbox-style focus ring for controller-driven grid selection."""
        pad = 5
        frame = rect.inflate(pad * 2, pad * 2)
        accent = pygame.Color(79, 203, 37)
        glow = pygame.Color(120, 220, 80, 90)
        if pulse:
            t = pygame.time.get_ticks() / 1000.0
            pad += int(2 * (0.5 + 0.5 * math.sin(t * 4.0)))
            frame = rect.inflate(pad * 2, pad * 2)
        glow_surf = pygame.Surface(frame.size, pygame.SRCALPHA)
        pygame.draw.rect(glow_surf, glow, glow_surf.get_rect(), border_radius=4)
        screen.blit(glow_surf, frame.topleft)
        pygame.draw.rect(screen, accent, frame, 3, border_radius=2)
        inner = frame.inflate(-6, -6)
        pygame.draw.rect(screen, pygame.Color(255, 255, 255), inner, 1, border_radius=1)
        corner = max(8, min(14, frame.width // 5))
        for ox, oy, dx, dy in (
            (frame.left, frame.top, 1, 1),
            (frame.right, frame.top, -1, 1),
            (frame.left, frame.bottom, 1, -1),
            (frame.right, frame.bottom, -1, -1),
        ):
            cx = ox if dx > 0 else ox - 1
            cy = oy if dy > 0 else oy - 1
            pygame.draw.line(screen, accent, (cx, cy), (cx + dx * corner, cy), 3)
            pygame.draw.line(screen, accent, (cx, cy), (cx, cy + dy * corner), 3)

    def _draw_gamerpic_grid(
        self,
        screen: pygame.Surface,
        panel: pygame.Rect,
        colors: dict[str, Any],
        body_font: pygame.font.Font,
        small_font: pygame.font.Font,
    ) -> None:
        slots = gamerpic_grid_slots()
        self._gamerpic_grid_rects = []
        if not slots:
            msg = body_font.render("No gamerpics found.", True, pygame.Color(colors["text"]))
            screen.blit(msg, (panel.x + 16, panel.y + 16))
            return

        cols, _rows = self._gamerpic_grid_dims()
        pad = 10
        gap = 8

        heading = body_font.render(page_title("Choose Gamerpic"), True, pygame.Color(colors["text"]))
        heading_y = panel.y + pad
        screen.blit(heading, (panel.x + pad, heading_y))
        grid_top = heading_y + heading.get_height() + pad + 4

        usable_w = panel.width - pad * 2
        usable_h = panel.height - (grid_top - panel.y) - pad - 28
        cell = max(48, min((usable_w - gap * (cols - 1)) // cols, (usable_h - gap * 2) // 3))
        grid_w = cols * cell + gap * (cols - 1)
        start_x = panel.x + pad + max(0, (usable_w - grid_w) // 2)
        start_y = grid_top

        profile_rel = load_profile().get("gamerpic", "").strip()
        panel_active = self._is_gamerpic_panel_active()
        focus_rect: pygame.Rect | None = None
        for idx, slot in enumerate(slots):
            row = idx // cols
            col = idx % cols
            rect = pygame.Rect(
                start_x + col * (cell + gap),
                start_y + row * (cell + gap),
                cell,
                cell,
            )
            self._gamerpic_grid_rects.append(rect)
            is_cursor = idx == self._gamerpic_grid_index and panel_active
            if is_cursor:
                focus_rect = rect
            rel = str(slot.get("rel", "")).strip()
            is_applied = bool(rel and profile_rel == rel)
            fill = pygame.Color("#2a3840")
            pygame.draw.rect(screen, fill, rect)
            if slot.get("custom"):
                plus = body_font.render("+", True, pygame.Color("#d8e8f0"))
                screen.blit(plus, plus.get_rect(center=rect.center).topleft)
                label = small_font.render("Custom", True, pygame.Color("#b8c8d0"))
                screen.blit(label, (rect.x + 4, rect.bottom - label.get_height() - 4))
            else:
                thumb = self._gamerpic_thumb(rel, cell - 6)
                if thumb is not None:
                    inner = thumb.get_rect(center=rect.center)
                    screen.blit(thumb, inner.topleft)
            border_color = pygame.Color("#5a6a72")
            border_w = 1
            if is_applied:
                border_color = pygame.Color("#88c848")
                border_w = 2
            pygame.draw.rect(screen, border_color, rect, border_w)

        if focus_rect is not None:
            self._draw_controller_selection_box(screen, focus_rect)

        hint = small_font.render(
            "A: apply   D-pad: move   B: menu",
            True,
            pygame.Color(colors.get("text_dim", colors["text"])),
        )
        screen.blit(hint, (panel.x + pad, panel.bottom - hint.get_height() - 8))

    @staticmethod
    def _build_home_tiles() -> list[dict[str, Any]]:
        return [
            {
                "title": "Open Tray",
                "col": 0,
                "row": 0,
                "w": 1,
                "h": 1,
                "command": "explorer.exe",
                "args": [],
                "cwd": "",
            },
            {
                "title": "My Pins",
                "icon": "my_pins",
                "col": 0,
                "row": 1,
                "w": 1,
                "h": 1,
                "action": "open_my_pins",
            },
            {"title": "Recent", "col": 0, "row": 2, "w": 1, "h": 1},
            {
                "title": "Games with Gold",
                "col": 1,
                "row": 0,
                "w": 2,
                "h": 2,
                "command": "cmd.exe",
                "args": ["/c", "start", "", "steam://store"],
                "cwd": "",
            },
            {"title": "Search", "col": 3, "row": 0, "w": 1, "h": 1},
            {"title": "Browse Apps", "icon": "browse_apps", "col": 3, "row": 1, "w": 1, "h": 1},
            {"title": "Demos", "col": 1, "row": 2, "w": 1, "h": 1},
            {
                "title": "My Apps",
                "icon": "my_apps",
                "col": 2,
                "row": 2,
                "w": 1,
                "h": 1,
                "action": "switch_hub",
                "hub": "Apps",
            },
            {
                "title": "My Games",
                "icon": "my_games",
                "col": 3,
                "row": 2,
                "w": 1,
                "h": 1,
                "action": "switch_hub",
                "hub": "Games",
            },
        ]

    def _draw_settings_panel(self, screen: pygame.Surface) -> None:
        palette = self.theme["colors"]
        settings_cfg = self.theme.get("settings_panel") or {}
        sc = settings_cfg.get("colors") or {}
        tile_fill = pygame.Color(sc.get("tile", palette["tile"]))
        tile_focus_fill = pygame.Color(sc.get("tile_focus", palette["tile_focus"]))
        accent = pygame.Color(sc.get("accent", palette["accent"]))

        tiles = self._hub_tiles["Settings"]
        self._settings_tile_rects = []

        cols = 4
        rows = 2
        base_width = int(settings_cfg.get("base_width", 1920))
        base_height = int(settings_cfg.get("base_height", 1080))
        scale = min(
            screen.get_width() / max(1, base_width),
            screen.get_height() / max(1, base_height),
        )
        scale = max(0.8, scale)

        tile_size = int(settings_cfg.get("tile_size", 170) * scale)
        gap = int(settings_cfg.get("gap", 14) * scale)
        focus_border = max(2, int(settings_cfg.get("focus_border", 4) * scale))
        radius = 0
        selected_scale = int(settings_cfg.get("selected_scale_px", 0) * scale)
        selected_lift = int(settings_cfg.get("selected_lift_px", 0) * scale)
        label_px = max(
            16,
            int(
                settings_cfg.get("label_size", self.theme["typography"]["body_size"])
                * scale,
            ),
        )
        font = pygame.font.SysFont(self.theme["typography"]["font_family"], label_px)
        total_width = cols * tile_size + (cols - 1) * gap
        total_height = rows * tile_size + (rows - 1) * gap
        start_x = (screen.get_width() - total_width) // 2
        start_y = (screen.get_height() - total_height) // 2 + 24

        text_color = pygame.Color(palette["text"])
        pad = max(12, tile_size // 14)

        for idx in range(self._settings_slot_count()):
            tile = tiles[idx] if idx < len(tiles) else {"title": "Coming Soon"}
            row = idx // cols
            col = idx % cols
            rect = pygame.Rect(
                start_x + col * (tile_size + gap),
                start_y + row * (tile_size + gap),
                tile_size,
                tile_size,
            )
            is_selected = idx == self._settings_selected_index
            draw_rect = rect
            if is_selected and selected_scale > 0:
                draw_rect = rect.inflate(selected_scale, selected_scale)
                draw_rect.y -= selected_lift
            self._settings_tile_rects.append(draw_rect)

            fill = tile_focus_fill if is_selected else tile_fill
            if radius > 0:
                pygame.draw.rect(screen, fill, draw_rect, border_radius=radius)
            else:
                pygame.draw.rect(screen, fill, draw_rect)
            if is_selected:
                if radius > 0:
                    pygame.draw.rect(screen, accent, draw_rect, width=focus_border, border_radius=radius)
                else:
                    pygame.draw.rect(screen, accent, draw_rect, width=focus_border)

            label = font.render(page_title(tile.get("title", "Untitled")), True, text_color)
            label_reserve = label.get_height() + pad + 4
            draw_tile_icon(
                screen,
                draw_rect,
                tile.get("icon"),
                label_bottom_reserve=label_reserve,
                icon_set="settings",
                width_ratio=0.62,
                top_ratio=0.10,
            )
            screen.blit(label, (draw_rect.x + pad, draw_rect.bottom - label.get_height() - pad))

    def _settings_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._settings_tile_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _display_option_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._display_option_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _home_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._home_tile_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _home_move(self, dx: int, dy: int) -> None:
        current = self._home_tiles[self._home_selected_index]
        target_col = int(current["col"]) + dx
        target_row = int(current["row"]) + dy
        best_idx = self._home_selected_index
        best_dist = 999
        for idx, tile in enumerate(self._home_tiles):
            col = int(tile["col"])
            row = int(tile["row"])
            dist = abs(col - target_col) + abs(row - target_row)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        self._home_selected_index = best_idx

    def _draw_home_panel(self, screen: pygame.Surface) -> None:
        self._home_tile_rects = []
        width = screen.get_width()
        height = screen.get_height()
        home_cfg = self.theme.get("home_panel") or {}
        base_width = int(home_cfg.get("base_width", 1920))
        base_height = int(home_cfg.get("base_height", 1080))
        scale = min(
            width / max(1, base_width),
            height / max(1, base_height),
        )
        scale = max(0.8, scale)

        base_w = int(int(home_cfg.get("tile_w", 320)) * scale)
        tile_h_ratio = float(home_cfg.get("tile_h_ratio", 0.62))
        base_h = int(base_w * tile_h_ratio)
        gap = int(int(home_cfg.get("gap", 10)) * scale)
        top_offset = int(int(home_cfg.get("top_offset_px", 70)) * scale)
        label_px = max(18, int(int(home_cfg.get("label_size", 28)) * scale))
        focus_border = max(2, int(int(home_cfg.get("focus_border", 4)) * scale))

        grid_cols = 4
        grid_rows = 3
        grid_w = grid_cols * base_w + (grid_cols - 1) * gap
        grid_h = grid_rows * base_h + (grid_rows - 1) * gap
        start_x = (width - grid_w) // 2
        start_y = (height - grid_h) // 2 + top_offset

        for idx, tile in enumerate(self._home_tiles):
            col = int(tile["col"])
            row = int(tile["row"])
            tw = base_w * int(tile["w"]) + gap * (int(tile["w"]) - 1)
            th = base_h * int(tile["h"]) + gap * (int(tile["h"]) - 1)
            rect = pygame.Rect(
                start_x + col * (base_w + gap),
                start_y + row * (base_h + gap),
                tw,
                th,
            )
            self._home_tile_rects.append(rect)
            is_selected = idx == self._home_selected_index
            fill = pygame.Color("#7BDE57" if is_selected else "#4FCB25")
            pygame.draw.rect(screen, fill, rect)
            if is_selected:
                pygame.draw.rect(
                    screen,
                    pygame.Color(self.theme["colors"]["accent"]),
                    rect,
                    width=focus_border,
                )
            font = pygame.font.SysFont(self.theme["typography"]["font_family"], label_px)
            label = font.render(page_title(tile["title"]), True, pygame.Color("#f3f6ff"))
            label_y = rect.bottom - label.get_height() - 10
            draw_home_tile_icon(
                screen,
                rect,
                tile.get("icon"),
                label_bottom_reserve=label.get_height() + 14,
            )
            screen.blit(label, (rect.x + 10, label_y))

    def _draw_display_submenu(self, screen: pygame.Surface, alpha: int = 255) -> None:
        if alpha >= 255:
            self._draw_display_submenu_content(screen)
            return
        layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        self._draw_display_submenu_content(layer)
        layer.set_alpha(max(0, alpha))
        screen.blit(layer, (0, 0))

    def _draw_settings_submenu(self, screen: pygame.Surface, alpha: int = 255) -> None:
        if alpha >= 255:
            self._draw_settings_submenu_content(screen)
            return
        layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        self._draw_settings_submenu_content(layer)
        layer.set_alpha(max(0, alpha))
        screen.blit(layer, (0, 0))

    def _draw_settings_submenu_content(self, screen: pygame.Surface) -> None:
        kind = self._active_settings_submenu_kind()
        if kind == "system":
            self._draw_system_info_submenu_content(screen)
            return
        if kind == "personalization":
            self._draw_art_submenu_content(screen)
            return
        if kind == "display":
            self._draw_display_submenu_content(screen)

    def _draw_art_submenu_content(self, screen: pygame.Surface) -> None:
        colors = self.theme["colors"]
        options = self._personalization_submenu_options()
        self._display_option_rects = []

        width = screen.get_width()
        height = screen.get_height()
        panel_y = 165
        panel_h = max(420, int(height * 0.62))
        left_x = max(64, int(width * 0.12))
        left_w = max(420, int(width * 0.34))
        right_x = left_x + left_w
        right_w = min(max(520, int(width * 0.34)), width - right_x - 80)

        title_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 50)
        item_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 38)
        body_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 30)
        dim_color = pygame.Color(colors.get("text_dim", colors["text"]))

        page_name = "JerLauncher Theme" if self._in_jerlauncher_theme_submenu else "Personalization"
        title = title_font.render(page_title(page_name), True, pygame.Color(colors["text"]))
        screen.blit(title, (left_x, 70))

        right_panel = pygame.Rect(right_x, panel_y, right_w, panel_h)
        panel_bg = pygame.Surface((right_w, panel_h), pygame.SRCALPHA)
        panel_bg.fill((28, 40, 48, 185))
        screen.blit(panel_bg, right_panel.topleft)

        grid_active = self._gamerpic_grid_is_active()
        row_h = max(72, panel_h // max(len(options), 1))
        for idx, option in enumerate(options):
            rect = pygame.Rect(left_x, panel_y + idx * row_h, left_w, row_h)
            self._display_option_rects.append(rect)
            is_row = idx == self._display_selected_index
            if is_row and grid_active:
                fill = pygame.Color("#7cb868")
                text_color = pygame.Color("#1f2b24")
            elif is_row:
                fill = pygame.Color("#4FCB25")
                text_color = pygame.Color("#ffffff")
            else:
                fill = pygame.Color("#f2f5f2")
                text_color = pygame.Color("#1f2b24")
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.line(screen, pygame.Color("#d4d9d6"), (rect.x, rect.bottom), (rect.right, rect.bottom), 1)
            label = item_font.render(page_title(option["title"]), True, text_color)
            screen.blit(label, (rect.x + 20, rect.y + (row_h - label.get_height()) // 2))

        hint_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 24)
        if grid_active:
            hint = hint_font.render("B: back to menu", True, dim_color)
        elif self._in_jerlauncher_theme_submenu:
            hint = hint_font.render("B: back to personalization   Up/Down: move   A: select", True, dim_color)
        else:
            hint = hint_font.render("Up/Down: move   A: open", True, dim_color)
        screen.blit(hint, (left_x, panel_y + len(options) * row_h + 8))

        info_x = right_x + 22
        info_y = panel_y + 24
        selected = options[self._display_selected_index]

        if self._profile_edit_mode == "gamertag":
            heading = body_font.render(page_title("Edit Gamertag"), True, pygame.Color(colors["text"]))
            screen.blit(heading, (info_x, info_y))
            info_y += 48
            display_text = self._profile_edit_buffer or DEFAULT_GAMERTAG
            if int(pygame.time.get_ticks() / 500) % 2 == 0:
                display_text += "|"
            value = body_font.render(display_text, True, pygame.Color(colors["text"]))
            screen.blit(value, (info_x, info_y))
            info_y += 56
            for line in (
                "Type on keyboard, then press Enter or A to save.",
                f"Max {MAX_GAMERTAG_LEN} characters. B cancels.",
            ):
                surf = body_font.render(line, True, dim_color)
                screen.blit(surf, (info_x, info_y))
                info_y += 40
            return

        if selected.get("action") == "edit_gamertag":
            profile = load_profile()
            tag = profile.get("gamertag", DEFAULT_GAMERTAG)
            heading = body_font.render(page_title("Current Gamertag"), True, pygame.Color(colors["text"]))
            screen.blit(heading, (info_x, info_y))
            info_y += 48
            screen.blit(body_font.render(tag, True, pygame.Color(colors["text"])), (info_x, info_y))
            info_y += 56
            if self._profile_edit_mode == "gamertag":
                screen.blit(
                    body_font.render("Type on keyboard. A saves. B returns to menu.", True, dim_color),
                    (info_x, info_y),
                )
            else:
                screen.blit(
                    body_font.render("Press A to edit gamertag.", True, dim_color),
                    (info_x, info_y),
                )
            return

        if selected.get("action") == "pick_gamerpic":
            small_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 22)
            self._draw_gamerpic_grid(screen, right_panel, colors, body_font, small_font)
            if not self._gamerpic_grid_is_active():
                veil = pygame.Surface(right_panel.size, pygame.SRCALPHA)
                veil.fill((12, 20, 28, 120))
                screen.blit(veil, right_panel.topleft)
                lock_hint = small_font.render("Press A to choose a gamerpic", True, pygame.Color("#e8f0f4"))
                screen.blit(lock_hint, lock_hint.get_rect(center=right_panel.center).topleft)
            return

        theme_actions = {
            "open_jerlauncher_theme_submenu",
            "pick_theme",
            "reset_to_core",
        }
        if selected.get("action") in theme_actions:
            detail_title = body_font.render(page_title("Current Option"), True, pygame.Color(colors["text"]))
            detail_body = body_font.render(page_title(selected["title"]), True, pygame.Color(colors["text"]))
            detail_desc = body_font.render(selected.get("description", ""), True, dim_color)
            screen.blit(detail_title, (info_x, info_y))
            info_y += 48
            screen.blit(detail_body, (info_x, info_y))
            info_y += 56
            screen.blit(detail_desc, (info_x, info_y))
            info_y += 56
            if selected.get("action") == "open_jerlauncher_theme_submenu":
                action_hint = body_font.render("Press A to open.", True, dim_color)
            else:
                action_hint = body_font.render("Press A to confirm.", True, dim_color)
            screen.blit(action_hint, (info_x, info_y))
            return

        total = max(0, self._game_art_scan_total)
        completed = max(0, min(self._game_art_scan_completed, total)) if total > 0 else 0
        pct = int((completed / total) * 100) if total > 0 else 0
        status = "Running" if self._game_art_scan_in_progress else "Idle"
        lines = [
            f"Status: {status}",
            f"Processed: {completed}/{total}" if total > 0 else "Processed: 0/0",
            f"Progress: {pct}%",
            f"New downloads: {self._game_art_scan_new}",
            f"Applied to cache: {self._game_art_scan_applied}",
            f"Failed to resolve: {self._game_art_scan_failed}",
        ]
        for line in lines:
            surf = body_font.render(line, True, pygame.Color(colors["text"]))
            screen.blit(surf, (info_x, info_y))
            info_y += 52

    def _draw_display_submenu_content(self, screen: pygame.Surface) -> None:
        colors = self.theme["colors"]
        options = self._display_submenu_options()
        self._display_option_rects = []

        width = screen.get_width()
        height = screen.get_height()
        panel_y = 165
        panel_h = max(360, int(height * 0.56))
        left_x = max(64, int(width * 0.12))
        left_w = max(420, int(width * 0.34))
        right_x = left_x + left_w
        right_w = min(max(420, int(width * 0.27)), width - right_x - 80)

        title_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 50)
        item_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 38)
        body_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 32)

        title = title_font.render(page_title("Display"), True, pygame.Color(colors["text"]))
        screen.blit(title, (left_x, 70))

        right_panel = pygame.Rect(right_x, panel_y, right_w, panel_h)
        panel_bg = pygame.Surface((right_w, panel_h), pygame.SRCALPHA)
        panel_bg.fill((28, 40, 48, 180))
        screen.blit(panel_bg, right_panel.topleft)

        dim_color = pygame.Color(colors.get("text_dim", colors["text"]))
        row_h = panel_h // max(len(options), 1)
        for idx, option in enumerate(options):
            rect = pygame.Rect(left_x, panel_y + idx * row_h, left_w, row_h)
            self._display_option_rects.append(rect)
            is_row = idx == self._display_selected_index
            if is_row:
                fill = pygame.Color("#4FCB25")
                text_color = pygame.Color("#ffffff")
            else:
                fill = pygame.Color("#f2f5f2")
                text_color = pygame.Color("#1f2b24")
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.line(screen, pygame.Color("#d4d9d6"), (rect.x, rect.bottom), (rect.right, rect.bottom), 1)

            label = item_font.render(page_title(option["title"]), True, text_color)
            screen.blit(label, (rect.x + 20, rect.y + (row_h - label.get_height()) // 2))

        hint_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 24)
        hint = hint_font.render("Up/Down: move   A: select", True, dim_color)
        screen.blit(hint, (left_x, panel_y + len(options) * row_h + 8))

        selected = options[self._display_selected_index]
        detail_title = body_font.render(page_title("Current Option"), True, pygame.Color(colors["text"]))
        detail_body = body_font.render(page_title(selected["title"]), True, pygame.Color(colors["text"]))
        detail_desc = body_font.render(selected.get("description", ""), True, dim_color)
        screen.blit(detail_title, (right_x + 22, panel_y + 24))
        screen.blit(detail_body, (right_x + 22, panel_y + 84))
        screen.blit(detail_desc, (right_x + 22, panel_y + 150))
        if selected.get("command"):
            action_hint = body_font.render("Press A to run.", True, dim_color)
            screen.blit(action_hint, (right_x + 22, panel_y + 220))

    def _draw_system_info_submenu_content(self, screen: pygame.Surface) -> None:
        colors = self.theme["colors"]
        self._display_option_rects = []

        width = screen.get_width()
        height = screen.get_height()
        panel_y = 165
        panel_h = max(420, int(height * 0.62))
        panel_x = max(64, int(width * 0.12))
        panel_w = min(max(900, int(width * 0.68)), width - panel_x - 80)

        title_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 50)
        item_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 34)
        value_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 30)

        title = title_font.render(page_title("System Information"), True, pygame.Color(colors["text"]))
        screen.blit(title, (panel_x, 70))

        panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
        panel_bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_bg.fill((28, 40, 48, 185))
        screen.blit(panel_bg, panel_rect.topleft)

        label_x = panel_x + 30
        value_x = panel_x + int(panel_w * 0.42)
        row_top = panel_y + 34
        row_height = 58

        for idx, (label_text, value_text) in enumerate(self._system_info_rows):
            y = row_top + idx * row_height
            if y + row_height > panel_rect.bottom - 24:
                break
            label = item_font.render(label_text, True, pygame.Color(colors["text"]))
            value = value_font.render(value_text, True, pygame.Color(colors["text_dim"]))
            screen.blit(label, (label_x, y))
            screen.blit(value, (value_x, y + 4))

    @staticmethod
    def _collect_system_info_rows() -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = [
            ("Processor", DashboardScene._processor_name()),
            ("Graphics Card", DashboardScene._graphics_name()),
            ("RAM", DashboardScene._total_ram_label()),
            ("OS", DashboardScene._os_label()),
            ("Machine", platform.machine() or "Unknown"),
        ]
        rows.extend(DashboardScene._storage_rows())
        return rows

    @staticmethod
    def _processor_name() -> str:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                model_str = str(model).strip()
                if model_str:
                    return model_str
        except OSError:
            pass

        try:
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name) -join ', '",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            name = output.strip()
            if name:
                return name
        except (subprocess.SubprocessError, OSError):
            pass

        processor = platform.processor().strip()
        if processor:
            return processor
        return os.environ.get("PROCESSOR_IDENTIFIER", "Unknown")

    @staticmethod
    def _graphics_name() -> str:
        gpu_names: list[str] = []
        commands = [
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            ["wmic", "path", "win32_VideoController", "get", "name"],
        ]
        for command in commands:
            try:
                output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, OSError):
                continue
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            if not lines:
                continue
            if lines[0].lower() == "name":
                lines = lines[1:]
            gpu_names.extend(lines)
            if gpu_names:
                break

        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in gpu_names:
            parts = [part.strip() for part in raw.split(",") if part.strip()]
            for part in parts:
                key = part.casefold()
                if key in seen:
                    continue
                seen.add(key)
                cleaned.append(part)

        if not cleaned:
            return "Unknown"

        def _gpu_sort_key(name: str) -> tuple[int, int, str]:
            lowered = name.casefold()
            vendor_order = {"nvidia": 0, "intel": 1, "amd": 2, "radeon": 2}
            for vendor, order in vendor_order.items():
                if vendor in lowered:
                    return (0, order, lowered)
            return (1, 99, lowered)

        ordered = sorted(cleaned, key=_gpu_sort_key)
        return ", ".join(ordered)

    @staticmethod
    def _storage_rows() -> list[tuple[str, str]]:
        try:
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_LogicalDisk | "
                    "Where-Object {$_.DriveType -eq 3 -and $_.Size} | "
                    "ForEach-Object {"
                    "$t=$_.Size/1GB; $f=$_.FreeSpace/1GB; "
                    "'{0}|{1:N1} GB total ({2:N1} GB free)' -f $_.DeviceID,$t,$f"
                    "}",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, OSError):
            return [("Storage", "Unknown")]

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return [("Storage", "Unknown")]

        rows: list[tuple[str, str]] = []
        for line in lines:
            if "|" not in line:
                continue
            drive, details = line.split("|", 1)
            rows.append((f"Storage ({drive})", details.strip()))
        if not rows:
            return [("Storage", "Unknown")]
        return rows

    def _draw_power_menu(self, screen: pygame.Surface) -> None:
        mix = max(0.0, min(1.0, self._power_transition_progress))
        if mix <= 0.0:
            self._power_option_rects = []
            return

        self._power_option_rects = []

        width = screen.get_width()
        height = screen.get_height()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, int(175 * mix)))
        screen.blit(overlay, (0, 0))

        base_panel_w = min(1120, int(width * 0.72))
        base_panel_h = min(1200, int(height * 0.96))
        scale = 0.88 + (0.12 * mix)
        panel_w = max(520, int(base_panel_w * scale))
        panel_h = max(420, int(base_panel_h * scale))
        panel_x = (width - panel_w) // 2
        panel_y = (height - panel_h) // 2
        panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        popup_bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        popup_bg.fill((245, 248, 249, 245))
        screen.blit(popup_bg, panel_rect.topleft)
        pygame.draw.rect(screen, pygame.Color("#bfc9cc"), panel_rect, width=2)

        header_h = 48
        header_rect = pygame.Rect(panel_x, panel_y, panel_w, header_h)
        pygame.draw.rect(screen, pygame.Color("#9fb2b7"), header_rect)
        pygame.draw.line(
            screen,
            pygame.Color("#d6e1e4"),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        title_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 34)
        icon_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 22, bold=True)
        desc_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 34)
        option_font = pygame.font.SysFont(self.theme["typography"]["font_family"], 36)

        pygame.draw.circle(screen, pygame.Color("#7dc53c"), (panel_x + 18, panel_y + 24), 11)
        icon_q = icon_font.render("?", True, pygame.Color("#ffffff"))
        icon_rect = icon_q.get_rect(center=(panel_x + 18, panel_y + 24))
        screen.blit(icon_q, icon_rect.topleft)
        title = title_font.render(page_title("Power"), True, pygame.Color("#ffffff"))
        title_rect = title.get_rect(midleft=(panel_x + 36, panel_y + (header_h // 2)))
        screen.blit(title, title_rect.topleft)

        desc = desc_font.render("Choose a power action.", True, pygame.Color("#454d52"))
        screen.blit(desc, (panel_x + 24, panel_y + 68))

        row_h = 54
        row_w = panel_w
        list_top = panel_y + max(310, panel_h - (len(self._power_options) * row_h) - 28)
        for idx, option in enumerate(self._power_options):
            row_rect = pygame.Rect(panel_x, list_top + idx * row_h, row_w, row_h)
            self._power_option_rects.append(row_rect)
            is_selected = idx == self._power_selected_index
            fill = pygame.Color("#52c425") if is_selected else pygame.Color("#eef2f3")
            fg = pygame.Color("#ffffff") if is_selected else pygame.Color("#465156")
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.line(screen, pygame.Color("#cfd8db"), (row_rect.x, row_rect.y), (row_rect.right, row_rect.y), 1)
            label = option_font.render(option, True, fg)
            screen.blit(label, (row_rect.x + 22, row_rect.y + (row_rect.height - label.get_height()) // 2))

    def _power_option_index_at_pos(self, pos: tuple[int, int]) -> int | None:
        for idx, rect in enumerate(self._power_option_rects):
            if rect.collidepoint(pos):
                return idx
        return None

    def _apply_power_action(self, action_name: str) -> None:
        lowered = action_name.casefold()
        self._in_power_menu = False
        self._power_transition_progress = 0.0
        self._power_transition_target = 0.0
        if lowered == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "0"])
            return
        if lowered == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "0"])
            return
        if lowered == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            return
        if lowered == "lock":
            try:
                ctypes.windll.user32.LockWorkStation()
            except AttributeError:
                pass
            return
        if lowered == "exit":
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    @staticmethod
    def _total_ram_label() -> str:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memory_status = MEMORYSTATUSEX()
        memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status))
        except AttributeError:
            success = 0
        if not success:
            return "Unknown"
        gib = memory_status.ullTotalPhys / (1024 ** 3)
        return f"{gib:.1f} GB"

    @staticmethod
    def _os_label() -> str:
        system = platform.system() or "Unknown OS"
        release = platform.release().strip()
        version = platform.version().strip()
        if release and version:
            return f"{system} {release} ({version})"
        if release:
            return f"{system} {release}"
        return system
