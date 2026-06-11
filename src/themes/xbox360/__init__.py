from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pygame

from core.theme_context import ThemePackage, set_active
from themes.xbox360.boot_scene import BootScene
from themes.xbox360.dashboard_scene import DashboardScene
from themes.xbox360.page_sounds import init_page_sounds


def activate(theme: ThemePackage) -> None:
    set_active(theme)
    init_page_sounds()


def create_boot_scene(
    theme: ThemePackage,
    *,
    screen: pygame.Surface,
    on_finished: Callable[[], None],
) -> BootScene:
    boot_cfg = theme.config.get("boot", {})
    video_rel = str(boot_cfg.get("video", "assets/boot/xbox360metro.mp4"))
    video_path = theme.asset(video_rel)
    return BootScene(theme.config, video_path, on_finished, screen=screen)


def create_dashboard_scene(
    theme: ThemePackage,
    games: list[dict[str, Any]],
    launcher: Any,
    *,
    on_switch_display: Callable[[], None],
    on_back_to_core: Callable[[], None] | None = None,
    on_choose_theme: Callable[[], None] | None = None,
) -> DashboardScene:
    scene = DashboardScene(
        theme.config,
        games,
        launcher,
        on_switch_display=on_switch_display,
    )
    if on_back_to_core is not None:
        scene.on_back_to_core = on_back_to_core
    if on_choose_theme is not None:
        scene.on_choose_theme = on_choose_theme
    return scene
