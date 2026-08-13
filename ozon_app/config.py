from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__


APP_NAME = "OZPriceAnalyzer"
APP_TITLE = "OZ Price Analyzer"
APP_VERSION = __version__
DEFAULT_TAX_RATE = 0.04


def default_application_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def storage_location_config_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / f"{APP_NAME}.storage.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / f"{APP_NAME}.storage.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / APP_NAME / "storage.json"


def read_storage_location(config_path: str | Path | None = None) -> Path | None:
    path = Path(config_path or storage_location_config_path()).expanduser().resolve()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    location = payload.get("storage_path") if isinstance(payload, dict) else None
    if not isinstance(location, str) or not location.strip():
        return None
    return Path(location).expanduser().resolve()


def save_storage_location(location: str | Path, config_path: str | Path | None = None) -> Path:
    root = Path(location).expanduser().resolve()
    path = Path(config_path or storage_location_config_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps({"storage_path": str(root)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def application_data_dir() -> Path:
    override = os.environ.get("OZON_APP_DATA")
    if override:
        return Path(override).expanduser().resolve()
    return read_storage_location() or default_application_data_dir()


def resource_path(name: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "ozon_app" / "resources" / name
    return Path(__file__).resolve().parent / "resources" / name


def ensure_app_dirs(base: Path | None = None) -> dict[str, Path]:
    root = Path(base or application_data_dir()).expanduser().resolve()
    paths = {
        "root": root,
        "files": root / "source_files",
        "exports": root / "exports",
        "backups": root / "backups",
        "database": root / "ozpriceanalyzer.sqlite3",
    }
    for key in ("root", "files", "exports", "backups"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths
