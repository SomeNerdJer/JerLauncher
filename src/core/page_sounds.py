from __future__ import annotations

from pathlib import Path

import pygame

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_page_left: pygame.mixer.Sound | None = None
_page_right: pygame.mixer.Sound | None = None


def init_page_sounds() -> None:
    global _page_left, _page_right
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    _page_left = pygame.mixer.Sound(_ASSETS_DIR / "pageleft.flac")
    _page_right = pygame.mixer.Sound(_ASSETS_DIR / "pageright.flac")


def play_hub_page_sound(direction: int) -> None:
    if direction < 0 and _page_left is not None:
        _page_left.play()
    elif direction > 0 and _page_right is not None:
        _page_right.play()
