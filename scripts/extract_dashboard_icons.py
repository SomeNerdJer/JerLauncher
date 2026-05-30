"""
Extract white home-dashboard tile icons from the reference screenshot.

Source: reference dashboard screenshot (1920×1080) for glyphs not in the 360 icon pack.
Output: assets/dashboard_icons/<id>.png — runtime loads only from this folder.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REF_PATH = Path(r"C:\Users\Jeremy\Pictures\iCloud Photos\dashboard.png")
OUT_DIR = PROJECT_ROOT / "assets" / "dashboard_icons"

# Tile grid at 1920×1080 — matches theme home_panel layout in dashboard_scene.py
BASE_W, BASE_H_RATIO, GAP, TOP_OFF = 320, 0.62, 10, 70
BASE_H = int(BASE_W * BASE_H_RATIO)
GRID_COLS, GRID_ROWS = 4, 3
SW, SH = 1920, 1080
GRID_W = GRID_COLS * BASE_W + (GRID_COLS - 1) * GAP
GRID_H = GRID_ROWS * BASE_H + (GRID_ROWS - 1) * GAP
START_X = (SW - GRID_W) // 2
START_Y = (SH - GRID_H) // 2 + TOP_OFF
PITCH_X = BASE_W + GAP
PITCH_Y = BASE_H + GAP


def tile_rect(col: int, row: int, w: int = 1, h: int = 1) -> tuple[int, int, int, int]:
    tw = BASE_W * w + GAP * (w - 1)
    th = BASE_H * h + GAP * (h - 1)
    x = START_X + col * PITCH_X
    y = START_Y + row * PITCH_Y
    return x, y, tw, th


def isolate_icon(tile: Image.Image, *, size_ratio: float = 0.58, center_y_ratio: float = 0.40) -> Image.Image:
    tile = tile.convert("RGBA")
    tw, th = tile.size
    size = int(min(tw, th) * size_ratio)
    cx, cy = tw // 2, int(th * center_y_ratio)
    box = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
    crop = tile.crop(box)
    out = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    opx = out.load()
    cpx = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, a = cpx[x, y]
            lum = (r + g + b) / 3
            green_bg = g > r + 25 and g > b + 15 and g > 70
            if green_bg:
                continue
            if lum >= 165:
                alpha = min(255, int((lum - 140) * 2.2))
                opx[x, y] = (255, 255, 255, alpha)
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    return out


# (icon_id, col, row, w, h, size_ratio, center_y_ratio)
ICON_TILES: list[tuple[str, int, int, int, int, float, float]] = [
    ("open_tray", 0, 0, 1, 1, 0.58, 0.40),
    ("my_pins", 0, 1, 1, 1, 0.58, 0.40),
    ("recent", 0, 2, 1, 1, 0.58, 0.40),
    ("search", 3, 0, 1, 1, 0.58, 0.40),
    ("browse_apps", 3, 1, 1, 1, 0.58, 0.40),
    ("demos", 1, 2, 1, 1, 0.72, 0.38),
    ("my_apps", 2, 2, 1, 1, 0.58, 0.40),
    ("my_games", 3, 2, 1, 1, 0.58, 0.40),
]


def main() -> None:
    if not REF_PATH.is_file():
        raise SystemExit(f"Reference image not found: {REF_PATH}")
    ref = Image.open(REF_PATH).convert("RGB")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for icon_id, col, row, w, h, size_ratio, center_y in ICON_TILES:
        x, y, tw, th = tile_rect(col, row, w, h)
        tile = ref.crop((x, y, x + tw, y + th))
        icon = isolate_icon(tile, size_ratio=size_ratio, center_y_ratio=center_y)
        dest = OUT_DIR / f"{icon_id}.png"
        icon.save(dest)
        print(f"Wrote {dest} ({icon.size[0]}x{icon.size[1]})")


if __name__ == "__main__":
    main()
