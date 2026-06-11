from __future__ import annotations

from pathlib import Path

import pygame

from core.theme_context import get_active

_page_left: pygame.mixer.Sound | None = None
_page_right: pygame.mixer.Sound | None = None


def init_page_sounds() -> None:
    global _page_left, _page_right
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    theme = get_active()
    if theme is None:
        return
    left = theme.asset("assets/sounds/pageleft.flac")
    right = theme.asset("assets/sounds/pageright.flac")
    _page_left = pygame.mixer.Sound(left) if left.is_file() else None
    _page_right = pygame.mixer.Sound(right) if right.is_file() else None


def play_hub_page_sound(direction: int) -> None:
    if direction < 0 and _page_left is not None:
        _page_left.play()
    elif direction > 0 and _page_right is not None:
        _page_right.play()
