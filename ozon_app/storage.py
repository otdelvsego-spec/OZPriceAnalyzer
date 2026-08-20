from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupInfo, create_backup, restore_backup
from .config import ensure_app_dirs


class StorageMigrationError(ValueError):
    """Raised when application storage cannot be copied safely."""


@dataclass(slots=True)
class StorageMigrationResult:
    source: Path
    destination: Path
    backup_info: BackupInfo


def migrate_storage(source: str | Path, destination: str | Path) -> StorageMigrationResult:
    source_root = Path(source).expanduser().resolve()
    destination_root = Path(destination).expanduser().resolve()
    if source_root == destination_root:
        raise StorageMigrationError("Выбрана текущая папка хранилища")
    if destination_root.is_relative_to(source_root) or source_root.is_relative_to(destination_root):
        raise StorageMigrationError("Новое хранилище не должно находиться внутри текущего и наоборот")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise StorageMigrationError("Выберите пустую папку для нового хранилища")

    destination_existed = destination_root.exists()
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ozprice_move_") as temp_name:
            archive = Path(temp_name) / "storage.ozbackup"
            info = create_backup(source_root, archive)
            restored = restore_backup(destination_root, archive)
            if (
                restored.info.run_count != info.run_count
                or restored.info.product_count != info.product_count
                or restored.info.source_count != info.source_count
            ):
                raise StorageMigrationError("Проверка перенесенных данных не пройдена")

        source_paths = ensure_app_dirs(source_root)
        destination_paths = ensure_app_dirs(destination_root)
        for key in ("exports", "backups"):
            _copy_directory_contents(source_paths[key], destination_paths[key])
    except Exception as exc:
        if destination_root.exists():
            shutil.rmtree(destination_root, ignore_errors=True)
            if destination_existed:
                destination_root.mkdir(parents=True, exist_ok=True)
        if isinstance(exc, StorageMigrationError):
            raise
        raise StorageMigrationError(f"Не удалось перенести хранилище: {exc}") from exc

    return StorageMigrationResult(source_root, destination_root, info)


def _copy_directory_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
