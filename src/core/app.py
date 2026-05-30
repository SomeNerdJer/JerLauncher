from __future__ import annotations

import json
import os
import ctypes
from pathlib import Path
from typing import Any

import pygame

from core.input_manager import InputManager
from core.page_sounds import init_page_sounds
from core.scene_manager import SceneManager
from services.launcher import Launcher
from ui.boot_scene import BootScene
from ui.dashboard_scene import DashboardScene


class MetroApp:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.project_root = self.root.parent
        self.theme = self._load_json(self.root / "config" / "theme.json")
        self.games = self._load_json(self.root / "config" / "games.json")
        self.state_path = self.root / "config" / "display_state.json"
        self.state = self._load_state()
        self.display_index = self._normalized_display_index(int(self.state.get("last_display", 0)))

        pygame.init()
        init_page_sounds()
        self.screen = self._apply_display_mode(self.display_index)
        pygame.display.set_caption("360 Experience MVP")
        self.clock = pygame.time.Clock()
        self.target_fps = int(self.theme["motion"]["target_fps"])

        self.scene_manager = SceneManager()
        self.input_manager = InputManager()
        self.input_manager.initialize()
        self.launcher = Launcher()
        self._dashboard: DashboardScene | None = None

        boot_video = self.project_root / "assets" / "xbox360metro.mp4"
        self.scene_manager.set_scene(
            BootScene(
                self.theme,
                boot_video,
                self._enter_dashboard,
                screen=self.screen,
            )
        )
        boot_scene = self.scene_manager.current_scene
        if boot_scene is not None:
            boot_scene.render(self.screen)
        pygame.display.flip()

    def _enter_dashboard(self) -> None:
        if self._dashboard is None:
            self._dashboard = DashboardScene(
                self.theme,
                self.games,
                self.launcher,
                on_switch_display=self._cycle_display,
            )
        self.scene_manager.set_scene(self._dashboard)

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(self.target_fps) / 1000.0
            self.input_manager.update(dt)

            scene_for_input = self.scene_manager.current_scene
            if scene_for_input is not None:
                for action in self.input_manager.consume_synthetic_actions():
                    scene_for_input.handle_action(action)

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
                    scene.handle_action(action)

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
            monitor_bounds = MetroApp._get_monitor_bounds_windows()
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
        # SDL checks this hint for target display on Windows.
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

        # Create borderless fullscreen-style window first.
        screen = pygame.display.set_mode((target_width, target_height), pygame.NOFRAME)

        # Then force exact monitor coordinates using native window APIs.
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
