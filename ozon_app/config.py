from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "OZPriceAnalyzer"
APP_TITLE = "OZ Price Analyzer"
APP_VERSION = "0.1.0"
DEFAULT_TAX_RATE = 0.04


def application_data_dir() -> Path:
    override = os.environ.get("OZON_APP_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def resource_path(name: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "ozon_app" / "resources" / name
    return Path(__file__).resolve().parent / "resources" / name


def ensure_app_dirs(base: Path | None = None) -> dict[str, Path]:
    root = base or application_data_dir()
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
