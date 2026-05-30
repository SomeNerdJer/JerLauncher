"""
Discover Rockstar titles installed via Rockstar Games Launcher (Windows registry).

Uses ``InstallFolder`` under ``HKLM\\SOFTWARE\\WOW6432Node\\Rockstar Games`` (and 32-bit view).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore

__all__ = ["list_installed_rockstar_games"]

if winreg is not None:
    _ROCKSTAR_REG_ROOTS: tuple[tuple[int, str], ...] = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Rockstar Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Rockstar Games"),
    )
else:  # pragma: no cover
    _ROCKSTAR_REG_ROOTS = ()

_SKIP_SUBKEYS: frozenset[str] = frozenset(
    {
        "launcher",
        "social club",
        "rgsc",
    }
)


def _read_install_folder(key_path: str, hive: int) -> Path | None:
    try:
        with winreg.OpenKey(hive, key_path) as key:
            for name in ("InstallFolder", "Install Dir", "InstallDir"):
                try:
                    raw, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                p = Path(str(raw).strip().strip('"'))
                if p.is_dir():
                    return p
    except OSError:
        pass
    return None


_EXE_SKIP_RE = re.compile(
    r"(launcher|rockstar|socialclub|unins|setup|redist|dotnet|vc_redist|"
    r"bilibili|crash)\.exe$",
    re.IGNORECASE,
)


def _pick_launch_exe(install: Path, game_title: str) -> Path | None:
    """Pick main game executable; avoid launcher/small tools."""
    candidates: list[Path] = []
    search_roots = [install]
    for sub in ("x64", "X64", "PlayGTAV", "Red Dead Redemption 2", "RDR2"):
        p = install / sub
        if p.is_dir():
            search_roots.append(p)

    for root in search_roots:
        try:
            for exe in root.glob("*.exe"):
                if _EXE_SKIP_RE.search(exe.name):
                    continue
                try:
                    if exe.stat().st_size < 300_000:
                        continue
                except OSError:
                    continue
                candidates.append(exe)
        except OSError:
            continue

    if not candidates:
        return None

    title_tokens = set(re.findall(r"[a-z0-9]+", game_title.casefold()))

    def score(p: Path) -> tuple[int, int]:
        name_l = p.name.casefold()
        ntok = set(re.findall(r"[a-z0-9]+", name_l))
        overlap = len(title_tokens & ntok)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        # Prefer GTA5 / RDR2 style names
        boost = 0
        if any(x in name_l for x in ("gta5", "playgtav", "rdr2", "game_rdr2")):
            boost = 5
        return (overlap + boost, size)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def list_installed_rockstar_games(*, fast: bool = False) -> list[dict[str, Any]]:
    if winreg is None:
        return []

    by_key: dict[str, dict[str, Any]] = {}
    for hive, parent in _ROCKSTAR_REG_ROOTS:
        if not parent:
            break
        try:
            with winreg.OpenKey(hive, parent) as pkey:
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(pkey, i)
                    except OSError:
                        break
                    i += 1
                    if sub_name.casefold() in _SKIP_SUBKEYS:
                        continue
                    sub_path = f"{parent}\\{sub_name}"
                    install = _read_install_folder(sub_path, hive)
                    if install is None:
                        continue
                    exe = _pick_launch_exe(install, sub_name)
                    if exe is None or not exe.is_file():
                        continue

                    slug = re.sub(r"[^\w.\-]+", "_", sub_name.strip())[:80] or "game"
                    library_key = f"rockstar:{slug}"
                    title = sub_name.strip() or "Rockstar Game"
                    header = None if fast else _find_local_cover(install)
                    entry: dict[str, Any] = {
                        "title": title,
                        "appid": 0,
                        "store": "rockstar",
                        "library_key": library_key,
                        "command": str(exe),
                        "args": [],
                        "cwd": str(exe.parent),
                        "header_image": str(header) if header else "",
                    }
                    by_key[library_key] = entry
        except OSError:
            continue

    return sorted(by_key.values(), key=lambda g: str(g["title"]).casefold())


def _find_local_cover(install: Path) -> Path | None:
    for pat in ("**/poster*.jpg", "**/cover*.jpg", "**/tile*.jpg", "**/poster*.png", "**/cover*.png"):
        try:
            for p in install.glob(pat):
                if p.is_file():
                    return p
        except OSError:
            continue
    return None
