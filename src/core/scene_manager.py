from __future__ import annotations

from typing import Protocol


class Scene(Protocol):
    def handle_action(self, action: str) -> None:
        ...

    def update(self, dt: float) -> None:
        ...

    def render(self, screen) -> None:
        ...


class SceneManager:
    def __init__(self) -> None:
        self._current_scene: Scene | None = None

    def set_scene(self, scene: Scene) -> None:
        self._current_scene = scene

    @property
    def current_scene(self) -> Scene | None:
        return self._current_scene
