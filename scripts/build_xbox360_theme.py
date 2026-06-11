#!/usr/bin/env python3
"""Build the Xbox 360 theme zip from bundled design assets."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ZIP = PROJECT_ROOT / "themes" / "Xbox360Metro.zip"
STAGING = PROJECT_ROOT / "build" / "xbox360-theme"


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build() -> Path:
    if STAGING.exists():
        shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True, exist_ok=True)

    manifest = {
        "id": "xbox360",
        "name": "Xbox 360 Metro",
        "version": "1.0.0",
        "module": "themes.xbox360",
    }
    theme = {
        "background_image": "assets/backgrounds/night.jpg",
        "display_submenu_background_image": "assets/backgrounds/purple.jpeg",
        "background_overlay_alpha": 120,
        "colors": {
            "background": "#0a0f1d",
            "text": "#f3f6ff",
            "text_dim": "#a6afcc",
            "accent": "#ffffff",
            "tile": "#4FCB25",
            "tile_focus": "#7BDE57",
        },
        "typography": {
            "font_family": "Segoe UI",
            "hub_size": 42,
            "tile_size": 26,
            "body_size": 24,
        },
        "tile": {
            "width": 340,
            "height": 200,
            "gap": 24,
            "focus_border": 4,
        },
        "home_panel": {
            "base_width": 1920,
            "base_height": 1080,
            "tile_w": 320,
            "tile_h_ratio": 0.62,
            "gap": 10,
            "top_offset_px": 70,
            "label_size": 28,
            "focus_border": 4,
        },
        "settings_panel": {
            "base_width": 1920,
            "base_height": 1080,
            "tile_size": 320,
            "gap": 16,
            "label_size": 40,
            "focus_border": 5,
            "border_radius": 3,
            "selected_scale_px": 12,
            "selected_lift_px": 8,
            "colors": {
                "tile": "#4FCB25",
                "tile_focus": "#7BDE57",
                "accent": "#ffffff",
            },
        },
        "guide_panel": {
            "base_width": 1920,
            "base_height": 1080,
            "min_scale": 0.8,
            "panel_scale": 0.9,
            "panel_width": 1480,
            "panel_height": 720,
            "header_height": 56,
            "header_content_gap": 18,
            "orb_half_size": 26,
            "orb_glow_pad": 12,
            "tab_width": 40,
            "row_height": 44,
            "footer_button_radius": 9,
            "footer_font_size": 15,
            "footer_btn_letter_size": 12,
            "title_font_size": 24,
            "item_font_size": 26,
            "tab_font_size": 15,
            "time_font_size": 19,
            "footer_gap_below": 10,
            "vertical_offset_ratio": 0.01,
        },
        "motion": {
            "focus_lerp_speed": 14.0,
            "target_fps": 60,
        },
        "boot": {
            "video": "assets/boot/xbox360metro.mp4",
            "skip_on_input": True,
            "fps": 60,
        },
    }

    _write_json(STAGING / "manifest.json", manifest)
    _write_json(STAGING / "theme.json", theme)

    _copy_tree(PROJECT_ROOT / "assets" / "xbox360metro.mp4", STAGING / "assets" / "boot" / "xbox360metro.mp4")
    _copy_tree(PROJECT_ROOT / "assets" / "dashboard_icons", STAGING / "assets" / "dashboard_icons")
    _copy_tree(PROJECT_ROOT / "assets" / "settings_icons", STAGING / "assets" / "settings_icons")
    _copy_tree(PROJECT_ROOT / "src" / "assets" / "gamerpics", STAGING / "assets" / "gamerpics")

    for name in ("pageleft.flac", "pageright.flac"):
        src = PROJECT_ROOT / "src" / "assets" / name
        _copy_tree(src, STAGING / "assets" / "sounds" / name)

    for name in ("night.jpg", "purple.jpeg", "blue.webp"):
        src = PROJECT_ROOT / "assets" / name
        _copy_tree(src, STAGING / "assets" / "backgrounds" / name)

    OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(STAGING.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("._") or path.name == ".DS_Store":
                continue
            archive.write(path, path.relative_to(STAGING).as_posix())

    print(f"Built theme package: {OUTPUT_ZIP}")
    return OUTPUT_ZIP


if __name__ == "__main__":
    build()
