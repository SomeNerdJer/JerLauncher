from __future__ import annotations

import json
import os
import ctypes
from pathlib import Path
from typing import Any

import pygame

from core.input_manager import InputManager
from core.scene_manager import SceneManager
from core.theme_context import ThemePackage, set_active
from core.theme_loader import ThemeLoadError, load_theme_zip
from services.launcher import Launcher
from themes.registry import load_theme_module
from ui.core_scene import CoreScene
from ui.theme_picker import pick_theme_zip


class GameLauncherApp:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.project_root = self.root.parent
        self.games = self._load_json(self.root / "config" / "games.json")
        self.state_path = self.root / "config" / "app_state.json"
        self.state = self._load_state()
        self.display_index = self._normalized_display_index(int(self.state.get("last_display", 0)))

        pygame.init()
        self.screen = self._apply_display_mode(self.display_index)
        pygame.display.set_caption("JerLauncher")
        self.clock = pygame.time.Clock()
        self.target_fps = 60

        self.scene_manager = SceneManager()
        self.input_manager = InputManager()
        self.input_manager.initialize()
        self.launcher = Launcher()

        self._active_theme: ThemePackage | None = None
        self._dashboard = None
        self._theme_cache_root = self.project_root / "config" / "themes"

        if not self._try_boot_saved_theme():
            self._enter_core()

    def _try_boot_saved_theme(self) -> bool:
        saved = self.state.get("last_theme_zip")
        if not saved:
            return False
        zip_path = Path(str(saved))
        try:
            theme = load_theme_zip(zip_path, cache_root=self._theme_cache_root)
        except ThemeLoadError:
            return False
        return self._activate_theme(theme)

    def _return_to_core(self) -> None:
        self._active_theme = None
        self.state.pop("last_theme_zip", None)
        self._save_state()
        self._enter_core()

    def _enter_core(self) -> None:
        set_active(None)
        self._dashboard = None
        self.scene_manager.set_scene(
            CoreScene(
                launcher=self.launcher,
                on_choose_theme=self._open_theme_picker,
                on_quit=self._request_quit,
            )
        )

    def _request_quit(self) -> None:
        self._quit_requested = True

    def _open_theme_picker(self) -> None:
        themes_dir = self.project_root / "themes"
        initial = themes_dir if themes_dir.is_dir() else self.project_root
        zip_path = pick_theme_zip(initial_dir=initial)
        if zip_path is None:
            return
        try:
            theme = load_theme_zip(zip_path, cache_root=self._theme_cache_root)
        except ThemeLoadError as exc:
            scene = self.scene_manager.current_scene
            if scene is not None and hasattr(scene, "status_text"):
                scene.status_text = str(exc)
                if hasattr(scene, "_status_timer"):
                    scene._status_timer = 4.0
            return

        self.state["last_theme_zip"] = str(zip_path.resolve())
        self._save_state()
        self._activate_theme(theme)

    def _activate_theme(self, theme: ThemePackage) -> bool:
        try:
            module = load_theme_module(theme)
        except RuntimeError as exc:
            scene = self.scene_manager.current_scene
            if scene is not None and hasattr(scene, "status_text"):
                scene.status_text = str(exc)
                if hasattr(scene, "_status_timer"):
                    scene._status_timer = 4.0
            return False

        self._active_theme = theme
        module.activate(theme)
        boot_scene = module.create_boot_scene(
            theme,
            screen=self.screen,
            on_finished=self._enter_themed_dashboard,
        )
        self.scene_manager.set_scene(boot_scene)
        boot_scene.render(self.screen)
        pygame.display.flip()
        return True

    def _enter_themed_dashboard(self) -> None:
        if self._active_theme is None:
            self._enter_core()
            return
        module = load_theme_module(self._active_theme)
        self._dashboard = module.create_dashboard_scene(
            self._active_theme,
            self.games,
            self.launcher,
            on_switch_display=self._cycle_display,
            on_back_to_core=self._return_to_core,
            on_choose_theme=self._open_theme_picker,
        )
        self.scene_manager.set_scene(self._dashboard)

    def run(self) -> None:
        self._quit_requested = False
        running = True
        while running and not self._quit_requested:
            dt = self.clock.tick(self.target_fps) / 1000.0
            self.input_manager.update(dt)

            scene_for_input = self.scene_manager.current_scene
            if scene_for_input is not None:
                for action in self.input_manager.consume_synthetic_actions():
                    if action == "EXIT_TO_DESKTOP":
                        running = False
                        break
                    scene_for_input.handle_action(action)

            if not running:
                break

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    continue
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F10:
                    self._cycle_display()
                    continue
                if event.type in (
                    pygame.CONTROLLERDEVICEADDED,
                    pygame.CONTROLLERDEVICEREMOVED,
                    pygame.JOYDEVICEADDED,
                    pygame.JOYDEVICEREMOVED,
                ):
                    self.input_manager.handle_device_event(event)
                    continue

                scene = self.scene_manager.current_scene
                if scene is None:
                    continue
                if event.type == pygame.TEXTINPUT and scene.handle_text_input(event):
                    continue
                if event.type == pygame.KEYDOWN and scene.handle_keydown(event):
                    continue
                for action in self.input_manager.actions_from_event(event):
                    if action == "EXIT_TO_DESKTOP":
                        running = False
                        break
                    scene.handle_action(action)
                if not running:
                    break

            scene = self.scene_manager.current_scene
            if scene is not None:
                scene.update(dt)
            scene = self.scene_manager.current_scene
            if scene is not None:
                scene.render(self.screen)
            pygame.mouse.set_visible(self.input_manager.mouse_enabled)
            pygame.display.flip()

        self.state["last_display"] = self.display_index
        self._save_state()
        pygame.quit()

    @staticmethod
    def _load_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"last_display": 0}
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
                if isinstance(loaded, dict):
                    return loaded
        except (OSError, json.JSONDecodeError):
            pass
        return {"last_display": 0}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2)

    @staticmethod
    def _get_display_count() -> int:
        if os.name == "nt":
            monitor_bounds = GameLauncherApp._get_monitor_bounds_windows()
            if monitor_bounds:
                return len(monitor_bounds)
        count_from_num = 0
        count_from_sizes = 0
        try:
            count_from_num = pygame.display.get_num_displays()
        except AttributeError:
            count_from_num = 0
        try:
            count_from_sizes = len(pygame.display.get_desktop_sizes())
        except pygame.error:
            count_from_sizes = 0
        return max(count_from_num, count_from_sizes, 1)

    def _normalized_display_index(self, requested_index: int) -> int:
        display_count = self._get_display_count()
        if display_count <= 0:
            return 0
        return max(0, min(requested_index, display_count - 1))

    def _cycle_display(self) -> None:
        display_count = self._get_display_count()
        if display_count <= 1:
            self._set_status_message("Only one display detected.")
            return
        self.display_index = (self.display_index + 1) % display_count
        self.screen = self._apply_display_mode(self.display_index)
        self.state["last_display"] = self.display_index
        self._save_state()
        self._set_status_message(f"Switched to display {self.display_index + 1}/{display_count}.")

    def _set_status_message(self, message: str) -> None:
        scene = self.scene_manager.current_scene
        if scene is None:
            return
        if hasattr(scene, "status_text"):
            scene.status_text = message
        if hasattr(scene, "_status_timer"):
            scene._status_timer = 2.0

    def _apply_display_mode(self, display_index: int) -> pygame.Surface:
        os.environ["SDL_VIDEO_FULLSCREEN_DISPLAY"] = str(display_index)
        monitor_bounds = self._get_monitor_bounds_windows()
        desktop_sizes = pygame.display.get_desktop_sizes()
        if not desktop_sizes:
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN, display=display_index)

        safe_index = min(display_index, len(desktop_sizes) - 1)
        width, height = desktop_sizes[safe_index]
        left = 0
        top = 0
        target_width = width
        target_height = height
        if monitor_bounds and safe_index < len(monitor_bounds):
            left, top, right, bottom = monitor_bounds[safe_index]
            target_width = right - left
            target_height = bottom - top

        screen = pygame.display.set_mode((target_width, target_height), pygame.NOFRAME)

        if monitor_bounds and safe_index < len(monitor_bounds):
            self._position_window_windows(left, top, target_width, target_height)

        return screen

    @staticmethod
    def _get_monitor_bounds_windows() -> list[tuple[int, int, int, int]]:
        if os.name != "nt":
            return []

        user32 = ctypes.windll.user32
        monitors: list[tuple[int, int, int, int]] = []

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(RECT),
            ctypes.c_double,
        )

        def _callback(_monitor, _hdc, rect_ptr, _data):
            rect = rect_ptr.contents
            monitors.append((rect.left, rect.top, rect.right, rect.bottom))
            return 1

        callback = MonitorEnumProc(_callback)
        user32.EnumDisplayMonitors(0, 0, callback, 0)
        return monitors

    @staticmethod
    def _position_window_windows(left: int, top: int, width: int, height: int) -> None:
        if os.name != "nt":
            return
        wm_info = pygame.display.get_wm_info()
        hwnd = wm_info.get("window")
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        swp_nozorder = 0x0004
        swp_showwindow = 0x0040
        user32.SetWindowPos(
            ctypes.c_void_p(hwnd),
            ctypes.c_void_p(0),
            int(left),
            int(top),
            int(width),
            int(height),
            swp_nozorder | swp_showwindow,
        )
