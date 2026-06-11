from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from services.ea_library import list_installed_ea_games
from services.epic_library import list_installed_epic_games
from services.rockstar_library import list_installed_rockstar_games
from services.steam_library import list_installed_steam_games


def load_all_games(*, fast: bool = True) -> list[dict[str, Any]]:
    steam = list_installed_steam_games(fast=fast)
    epic = list_installed_epic_games(fast=fast)
    ea = list_installed_ea_games(fast=fast)
    rockstar = list_installed_rockstar_games(fast=fast)
    return sorted(
        steam + epic + ea + rockstar,
        key=lambda game: str(game.get("title", "")).casefold(),
    )


class GameLibraryLoader:
    def __init__(self) -> None:
        self._generation = 0
        self._results: queue.Queue[tuple[str, int, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None

    def cancel(self) -> None:
        self._generation += 1

    def start(self, *, fast: bool = True) -> int:
        self.cancel()
        generation = self._generation

        def worker() -> None:
            try:
                entries = load_all_games(fast=fast)
                self._results.put(("ok", generation, entries))
            except Exception as exc:  # pragma: no cover
                self._results.put(("err", generation, str(exc)))

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return generation

    def poll(
        self,
        generation: int,
        *,
        on_ok: Callable[[list[dict[str, Any]]], None],
        on_err: Callable[[str], None],
    ) -> bool:
        handled = False
        while True:
            try:
                status, result_generation, payload = self._results.get_nowait()
            except queue.Empty:
                break
            if result_generation != generation:
                continue
            handled = True
            if status == "ok":
                on_ok(payload)
            else:
                on_err(str(payload))
        return handled
