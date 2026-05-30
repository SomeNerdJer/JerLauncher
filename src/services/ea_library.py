"""
Discover EA PC titles on Windows.

Primary source is the **EA app / EA Desktop** encrypted install list under
``ProgramData\\EA Desktop\\…\\IS`` (same data the launcher uses). If that cannot
be read (missing ``pycryptodome``, bad decrypt, or no ``IS`` file), we fall back to
legacy registry keys under ``EA Games`` / ``Origin Games``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from services.ea_desktop_is import try_load_ea_desktop_games

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore

__all__ = ["list_installed_ea_games"]

if winreg is not None:
    _EA_REG_PARENTS: tuple[tuple[int, str], ...] = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\EA Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Origin Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EA Games"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\EA Games"),
    )
else:  # pragma: no cover
    _EA_REG_PARENTS = ()

_INSTALL_VALUE_NAMES: tuple[str, ...] = ("Install Dir", "InstallDir", "InstallPath")

_SKIP_SUBKEYS: frozenset[str] = frozenset(
    k.casefold()
    for k in (
        "EA Core",
        "EADM",
    )
)

_SKIP_FOLDER_NAMES: frozenset[str] = frozenset(
    k.casefold()
    for k in (
        "ea desktop",
        "ea app",
        "origin",
        "ea installer",
        "eaanticheat",
        "easyanticheat",
    )
)


def _read_install_dir(key_path: str, hive: int) -> Path | None:
    try:
        with winreg.OpenKey(hive, key_path) as key:
            for name in _INSTALL_VALUE_NAMES:
                try:
                    raw, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                p = Path(str(raw).strip().strip('"'))
                if p.is_dir():
                    return p
            # Origin sometimes stores a .exe path in GDFBinary
            try:
                gdf, _ = winreg.QueryValueEx(key, "GDFBinary")
                gp = Path(str(gdf).strip().strip('"'))
                if gp.is_file():
                    cand = gp.parent
                    if cand.is_dir():
                        return cand
            except OSError:
                pass
    except OSError:
        pass
    return None


_EXE_SKIP_RE = re.compile(
    r"(redist|unins|setup|touchup|activation|datacollect|crash|error|repair|vc_redist|"
    r"dxsetup|dotnet|easyanticheat|eac_|origin(?:thin)?setup)\.exe$",
    re.IGNORECASE,
)


def _pick_launch_exe(install: Path) -> Path | None:
    """Pick a plausible game executable under the install folder."""
    roots = [install]
    for sub in ("bin", "Bin", "x64", "Game", "__Installer"):
        p = install / sub
        if p.is_dir():
            roots.append(p)

    candidates: list[Path] = []
    for root in roots:
        try:
            for exe in root.glob("*.exe"):
                if _EXE_SKIP_RE.search(exe.name):
                    continue
                try:
                    if exe.stat().st_size < 200_000:
                        continue
                except OSError:
                    continue
                candidates.append(exe)
        except OSError:
            continue

    if not candidates:
        return None

    def sort_key(p: Path) -> tuple[int, int]:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        # Prefer executables whose names look like the game / launcher
        name_l = p.name.casefold()
        priority = 0
        if "launcher" in name_l or "game" in name_l or "start" in name_l:
            priority = 2
        elif not any(x in name_l for x in ("server", "sdk", "tool", "editor")):
            priority = 1
        return (priority, size)

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def _program_files_ea_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base:
            continue
        b = Path(base)
        for tail in ("EA Games", "Origin Games"):
            roots.append(b / tail)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _folder_display_title(folder_name: str) -> str:
    return folder_name.replace("_", " ").strip() or "EA Game"


def _list_ea_games_from_program_files(*, fast: bool = False) -> list[dict[str, Any]]:
    """
    Discover titles under ``Program Files\\EA Games`` / ``Origin Games`` when the EA app
    encrypted manifest cannot be read.
    """
    by_path: dict[str, dict[str, Any]] = {}
    for root in _program_files_ea_roots():
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name.casefold() in _SKIP_FOLDER_NAMES:
                continue
            exe = _pick_launch_exe(child)
            if exe is None or not exe.is_file():
                continue
            try:
                path_key = str(child.resolve()).casefold()
            except OSError:
                continue
            slug = re.sub(r"[^\w.\-]+", "_", child.name.strip())[:80] or "game"
            library_key = f"ea:{slug}"
            title = _folder_display_title(child.name)
            header = None if fast else _find_local_cover(child)
            by_path[path_key] = {
                "title": title,
                "appid": 0,
                "store": "ea",
                "library_key": library_key,
                "command": str(exe),
                "args": [],
                "cwd": str(child),
                "header_image": str(header) if header else "",
                "ea_source": "program_files",
                "ea_install_dir": str(child),
            }
    return list(by_path.values())


def _merge_ea_game_lists(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-dupe by resolved install folder; prefer EA Desktop manifest > folder scan > registry."""
    priority = {"ea_desktop_is": 0, "ea_desktop": 0, "program_files": 1, "registry": 2}

    flat: list[dict[str, Any]] = []
    for lst in lists:
        flat.extend(lst)

    flat.sort(
        key=lambda g: (
            priority.get(str(g.get("ea_source") or "registry"), 9),
            str(g.get("title", "")).casefold(),
        )
    )

    seen_install: set[str] = set()
    seen_lk: set[str] = set()
    out: list[dict[str, Any]] = []
    for game in flat:
        install_dir = str(game.get("ea_install_dir") or game.get("cwd") or "").strip()
        lk = str(game.get("library_key") or "")
        ik = ""
        if install_dir:
            try:
                ik = str(Path(install_dir).resolve()).casefold()
            except OSError:
                ik = ""
        if ik:
            if ik in seen_install:
                continue
            seen_install.add(ik)
        elif lk:
            if lk in seen_lk:
                continue
            seen_lk.add(lk)
        else:
            continue
        out.append(game)
    return sorted(out, key=lambda g: str(g.get("title", "")).casefold())


def _list_ea_games_from_registry(*, fast: bool = False) -> list[dict[str, Any]]:
    if winreg is None:
        return []

    by_key: dict[str, dict[str, Any]] = {}
    for hive, parent in _EA_REG_PARENTS:
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
                    install = _read_install_dir(sub_path, hive)
                    if install is None:
                        continue
                    exe = _pick_launch_exe(install)
                    if exe is None or not exe.is_file():
                        continue

                    slug = re.sub(r"[^\w.\-]+", "_", sub_name.strip())[:80] or "game"
                    library_key = f"ea:{slug}"
                    title = sub_name.strip() or "EA Game"
                    header = None if fast else _find_local_cover(install)
                    entry: dict[str, Any] = {
                        "title": title,
                        "appid": 0,
                        "store": "ea",
                        "library_key": library_key,
                        "command": str(exe),
                        "args": [],
                        "cwd": str(install),
                        "header_image": str(header) if header else "",
                        "ea_registry_title": sub_name,
                        "ea_source": "registry",
                        "ea_install_dir": str(install),
                    }
                    by_key[library_key] = entry
        except OSError:
            continue

    return sorted(by_key.values(), key=lambda g: str(g["title"]).casefold())


def list_installed_ea_games(*, fast: bool = False) -> list[dict[str, Any]]:
    """
    Prefer the EA app encrypted ``IS`` manifest (same catalog as the launcher).

    If decryption fails (hardware mismatch, EA format change), merge:
    ``Program Files\\EA Games`` / ``Origin Games`` folder scan + legacy registry.
    """
    games, mode = try_load_ea_desktop_games()
    if mode == "ea_desktop":
        return games
    program_files = _list_ea_games_from_program_files(fast=fast)
    registry = _list_ea_games_from_registry(fast=fast)
    return _merge_ea_game_lists(program_files, registry)


def _find_local_cover(install: Path) -> Path | None:
    for pat in (
        "CoverArt*.jpg",
        "CoverArt*.png",
        "**/CoverArt*.jpg",
        "**/CoverArt*.png",
        "**/logo*.png",
        "**/gameface*.png",
    ):
        try:
            for p in install.glob(pat):
                if p.is_file():
                    return p
        except OSError:
            continue
    return None
