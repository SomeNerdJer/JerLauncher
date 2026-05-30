from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pygame

from core.boot_audio import BootAudioPlayer

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


_SKIP_ACTIONS = frozenset(
    {
        "SELECT",
        "BACK",
        "MOVE_LEFT",
        "MOVE_RIGHT",
        "MOVE_UP",
        "MOVE_DOWN",
        "HUB_PREV",
        "HUB_NEXT",
        "DETAILS",
        "GUIDE_Y",
        "TOGGLE_GUIDE",
    }
)

_MAX_PRELOAD_FRAMES = 900
_LEADING_BLACK_MEAN = 8.0
_MAX_FRAME_DT = 0.1
_LOADING_DOT_INTERVAL_S = 0.35
_LOADING_DOT_COUNT = 5
_PRELOAD_BUDGET_S = 0.028
_PRELOAD_MAX_FRAMES_PER_TICK = 24


class BootScene:
    def __init__(
        self,
        theme: dict[str, Any],
        video_path: Path,
        on_finished: Callable[[], None],
        *,
        screen: pygame.Surface,
    ) -> None:
        self.theme = theme
        self._on_finished = on_finished
        self._screen = screen
        self._screen_size = screen.get_size()
        self._finished = False
        self._elapsed = 0.0
        self._intro_started = False
        self._fps = 30.0
        self._frames: list[pygame.Surface] = []
        self._frame_index = 0
        self._error: str | None = None
        self._audio: BootAudioPlayer | None = None

        self._preload_complete = False
        self._capture: Any = None
        self._skipping_leading_black = True
        self._loading_elapsed = 0.0

        boot_cfg = theme.get("boot") or {}
        self._skip_on_input = bool(boot_cfg.get("skip_on_input", True))
        theme_fps = boot_cfg.get("fps")
        self._fps_override = float(theme_fps) if theme_fps else None

        self._video_path = self._resolve_video_path(video_path, boot_cfg.get("video"))

    @property
    def duration_s(self) -> float:
        if not self._frames or self._fps <= 0:
            return 0.0
        return len(self._frames) / self._fps

    @staticmethod
    def _resolve_video_path(explicit: Path, theme_relative: str | None) -> Path:
        if theme_relative:
            project_root = Path(__file__).resolve().parents[2]
            candidate = project_root / theme_relative
            if candidate.is_file():
                return candidate
        return explicit

    @staticmethod
    def _normalize_fps(raw_fps: float) -> float:
        if raw_fps <= 1.0 or raw_fps > 120.0:
            return 30.0
        return raw_fps

    def _open_capture(self) -> Any | None:
        if cv2 is None:
            return None
        backends: list[int | None] = [None]
        if hasattr(cv2, "CAP_MSMF"):
            backends.insert(0, cv2.CAP_MSMF)
        if hasattr(cv2, "CAP_FFMPEG"):
            backends.append(cv2.CAP_FFMPEG)

        for backend in backends:
            capture = (
                cv2.VideoCapture(str(self._video_path), backend)
                if backend is not None
                else cv2.VideoCapture(str(self._video_path))
            )
            if capture.isOpened():
                return capture
            capture.release()
        return None

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _begin_preload_capture(self) -> None:
        if cv2 is None:
            self._error = "opencv-python is required for boot video playback"
            self._preload_complete = True
            return
        if not self._video_path.is_file():
            self._error = f"Boot video not found: {self._video_path}"
            self._preload_complete = True
            return

        capture = self._open_capture()
        if capture is None:
            self._error = f"Could not open boot video: {self._video_path}"
            self._preload_complete = True
            return

        if self._fps_override is not None:
            self._fps = self._fps_override
        else:
            self._fps = self._normalize_fps(float(capture.get(cv2.CAP_PROP_FPS)))

        self._capture = capture
        self._skipping_leading_black = True

    def _end_preload(self) -> None:
        self._release_capture()
        self._preload_complete = True
        if not self._frames and not self._error:
            self._error = f"Boot video has no visible frames: {self._video_path}"

    def _preload_chunk(self) -> None:
        if self._capture is None:
            self._begin_preload_capture()
            if self._capture is None:
                return

        deadline = time.perf_counter() + _PRELOAD_BUDGET_S
        loaded = 0
        while (
            time.perf_counter() < deadline
            and loaded < _PRELOAD_MAX_FRAMES_PER_TICK
            and len(self._frames) < _MAX_PRELOAD_FRAMES
        ):
            ok, frame = self._capture.read()
            if not ok:
                self._end_preload()
                return
            if self._skipping_leading_black and float(frame.mean()) < _LEADING_BLACK_MEAN:
                continue
            self._skipping_leading_black = False
            self._frames.append(self._frame_to_surface(frame, self._screen_size))
            loaded += 1

        pygame.event.pump()

    def _frame_to_surface(self, frame_bgr: Any, target_size: tuple[int, int]) -> pygame.Surface:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        height, width = frame_rgb.shape[:2]
        surface = pygame.image.frombuffer(
            frame_rgb.tobytes(), (width, height), "RGB"
        ).copy()
        if surface.get_size() != target_size:
            surface = pygame.transform.scale(surface, target_size)
        return surface.convert(self._screen)

    def _start_audio(self) -> None:
        if not self._video_path.is_file():
            return
        if self._audio is None:
            cache_dir = Path(__file__).resolve().parents[2] / "assets" / "cache"
            self._audio = BootAudioPlayer(self._video_path, cache_dir)
        self._audio.start()

    def _stop_audio(self) -> None:
        if self._audio is not None:
            self._audio.stop()

    def _show_loading_text(self) -> bool:
        return not self._finished and not self._intro_started

    def _loading_label(self) -> str:
        step = int(self._loading_elapsed / _LOADING_DOT_INTERVAL_S) % _LOADING_DOT_COUNT
        return f"Loading{'.' * (step + 1)}"

    def _tick_loading_clock(self, dt: float) -> None:
        if not self._intro_started:
            self._loading_elapsed += dt

    def _draw_overlay(self, screen: pygame.Surface) -> None:
        margin = max(20, screen.get_height() // 40)
        typography = self.theme.get("typography") or {}
        colors = self.theme.get("colors") or {}
        font = pygame.font.SysFont(
            typography.get("font_family", "Segoe UI"),
            max(20, screen.get_height() // 48),
        )
        color = pygame.Color(colors.get("text", "#f3f6ff"))

        if self._show_loading_text():
            loading = font.render(self._loading_label(), True, color)
            screen.blit(
                loading,
                (margin, screen.get_height() - margin - loading.get_height()),
            )

        if self._skip_on_input and not self._intro_started:
            skip = font.render("Press Any Button To Skip Intro", True, color)
            skip_rect = skip.get_rect(
                bottomright=(screen.get_width() - margin, screen.get_height() - margin),
            )
            screen.blit(skip, skip_rect)

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._release_capture()
        self._frames.clear()
        self._stop_audio()
        self._on_finished()

    def handle_action(self, action: str) -> None:
        if self._finished:
            return
        if not self._skip_on_input:
            return
        if action in _SKIP_ACTIONS or action.startswith("MOUSE_CLICK"):
            self._finish()

    def handle_keydown(self, event: pygame.event.Event) -> bool:
        if self._finished:
            return False
        if self._skip_on_input:
            self._finish()
            return True
        return False

    def _begin_intro(self) -> None:
        self._intro_started = True
        self._elapsed = 0.0
        self._frame_index = 0
        self._start_audio()

    def update(self, dt: float) -> None:
        if self._finished:
            return

        dt = min(max(dt, 0.0), _MAX_FRAME_DT)
        self._tick_loading_clock(dt)

        if not self._preload_complete:
            self._preload_chunk()
            return

        if self._error or not self._frames:
            return

        if not self._intro_started:
            self._begin_intro()
            return

        if self._audio is not None:
            self._audio.pump()

        self._elapsed += dt
        target_index = int(self._elapsed * self._fps)
        if target_index >= len(self._frames):
            self._finish()
            return
        self._frame_index = target_index

    def render(self, screen: pygame.Surface) -> None:
        colors = self.theme.get("colors") or {}
        screen.fill(pygame.Color(colors.get("background", "#0a0f1d")))

        if self._intro_started and self._frames:
            screen.blit(self._frames[self._frame_index], (0, 0))
        elif self._preload_complete and not self._finished and (self._error or not self._frames):
            font = pygame.font.SysFont(
                self.theme.get("typography", {}).get("font_family", "Segoe UI"),
                28,
            )
            message = self._error or "Boot video unavailable"
            label = font.render(message, True, pygame.Color("#f3f6ff"))
            rect = label.get_rect(
                center=(screen.get_width() // 2, screen.get_height() // 2),
            )
            screen.blit(label, rect)

        if not self._finished:
            self._draw_overlay(screen)
