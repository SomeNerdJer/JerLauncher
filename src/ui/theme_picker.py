from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog


def pick_theme_zip(*, initial_dir: Path | None = None) -> Path | None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            title="Choose Theme Package",
            filetypes=[("Theme packages", "*.zip"), ("All files", "*.*")],
            initialdir=str(initial_dir) if initial_dir and initial_dir.is_dir() else None,
        )
    finally:
        root.destroy()
    if not selected:
        return None
    return Path(selected)
