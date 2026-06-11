from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from core.theme_context import ThemePackage


class ThemeLoadError(RuntimeError):
    pass


def load_theme_zip(zip_path: Path, *, cache_root: Path) -> ThemePackage:
    if not zip_path.is_file():
        raise ThemeLoadError(f"Theme file not found: {zip_path}")
    if zip_path.suffix.casefold() != ".zip":
        raise ThemeLoadError("Theme must be a .zip file.")

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            manifest = _read_json_from_zip(archive, "manifest.json")
            theme_id = str(manifest.get("id", "")).strip()
            if not theme_id:
                raise ThemeLoadError("Theme manifest is missing 'id'.")
            name = str(manifest.get("name", theme_id)).strip() or theme_id
            version = str(manifest.get("version", "1.0.0")).strip() or "1.0.0"
            module = str(manifest.get("module", f"themes.{theme_id}")).strip()

            extract_dir = cache_root / theme_id
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            archive.extractall(extract_dir)

            theme_config_path = extract_dir / "theme.json"
            if not theme_config_path.is_file():
                raise ThemeLoadError("Theme zip is missing theme.json.")
            with theme_config_path.open("r", encoding="utf-8") as handle:
                theme_config = json.load(handle)
            if not isinstance(theme_config, dict):
                raise ThemeLoadError("theme.json must be a JSON object.")
    except zipfile.BadZipFile as exc:
        raise ThemeLoadError(f"Invalid theme zip: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ThemeLoadError(f"Invalid theme JSON: {exc}") from exc

    return ThemePackage(
        id=theme_id,
        name=name,
        version=version,
        root=extract_dir,
        config=theme_config,
        module=module,
        source_zip=zip_path.resolve(),
    )


def _read_json_from_zip(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        raw = archive.read(name).decode("utf-8")
    except KeyError as exc:
        raise ThemeLoadError(f"Theme zip is missing {name}.") from exc
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ThemeLoadError(f"{name} must be a JSON object.")
    return data
