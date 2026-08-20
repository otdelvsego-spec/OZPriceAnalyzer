from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from .config import APP_VERSION, ensure_app_dirs


BACKUP_FORMAT = "ozpriceanalyzer-backup"
BACKUP_VERSION = 1
DATABASE_ARCHIVE_PATH = "database/ozpriceanalyzer.sqlite3"
MAX_ARCHIVE_ENTRIES = 100_000
MAX_UNCOMPRESSED_SIZE = 10 * 1024 * 1024 * 1024
MAX_MANIFEST_SIZE = 10 * 1024 * 1024
REQUIRED_TABLES = {
    "settings",
    "products",
    "product_cost_history",
    "runs",
    "source_files",
    "product_results",
    "unallocated",
    "accrual_stats",
    "quality_events",
    "scenario_prices",
}


class BackupError(ValueError):
    """Raised when a backup cannot be created, validated, or restored safely."""


@dataclass(slots=True)
class BackupInfo:
    path: Path
    created_at: str
    app_version: str
    run_count: int
    product_count: int
    source_count: int
    source_size: int

    @property
    def total_items(self) -> int:
        return self.run_count + self.product_count + self.source_count


@dataclass(slots=True)
class RestoreResult:
    info: BackupInfo
    safety_backup: Path | None


def create_backup(base_dir: str | Path, destination: str | Path) -> BackupInfo:
    paths = ensure_app_dirs(Path(base_dir).expanduser().resolve())
    output = Path(destination).expanduser().resolve()
    if output.suffix.casefold() != ".ozbackup":
        output = output.with_suffix(".ozbackup")
    if output.is_relative_to(paths["files"]):
        raise BackupError("Резервную копию нельзя сохранять в папку исходных отчетов")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ozprice_backup_") as temp_name:
        temp_root = Path(temp_name)
        snapshot = temp_root / "ozpriceanalyzer.sqlite3"
        _snapshot_database(paths["database"], snapshot)
        counts = _database_counts(snapshot)

        files: list[dict[str, object]] = []
        files.append(_manifest_file(snapshot, DATABASE_ARCHIVE_PATH, "database"))
        seen_names: set[str] = set()
        for source in sorted(paths["files"].iterdir(), key=lambda item: item.name.casefold()):
            if not source.is_file():
                continue
            if source.name in seen_names:
                raise BackupError(f"Повторяющееся имя исходного файла: {source.name}")
            seen_names.add(source.name)
            files.append(_manifest_file(source, f"source_files/{source.name}", "source"))
        _validate_referenced_file_names(snapshot, seen_names)

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        manifest = {
            "format": BACKUP_FORMAT,
            "backup_version": BACKUP_VERSION,
            "app_version": APP_VERSION,
            "created_at": created_at,
            "counts": {
                "runs": counts["runs"],
                "products": counts["products"],
                "sources": counts["sources"],
            },
            "files": files,
        }
        temp_archive = output.parent / f".{output.name}.{os.getpid()}.tmp"
        try:
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.write(snapshot, DATABASE_ARCHIVE_PATH)
                for item in files[1:]:
                    archive.write(paths["files"] / Path(str(item["path"])).name, str(item["path"]))
            inspect_backup(temp_archive)
            os.replace(temp_archive, output)
        finally:
            temp_archive.unlink(missing_ok=True)

    return _info_from_manifest(output, manifest)


def inspect_backup(source: str | Path) -> BackupInfo:
    archive_path = Path(source).expanduser().resolve()
    manifest = _read_and_validate_manifest(archive_path)
    with tempfile.TemporaryDirectory(prefix="ozprice_inspect_") as temp_name:
        temp_db = Path(temp_name) / "ozpriceanalyzer.sqlite3"
        with zipfile.ZipFile(archive_path, "r") as archive:
            _verify_archive_items(archive, manifest)
            _extract_verified_file(archive, _file_entry(manifest, DATABASE_ARCHIVE_PATH), temp_db)
        _validate_database(temp_db, manifest)
        _validate_referenced_file_names(
            temp_db,
            {Path(str(item["path"])).name for item in manifest["files"] if item["kind"] == "source"},
        )
    return _info_from_manifest(archive_path, manifest)


def restore_backup(base_dir: str | Path, source: str | Path) -> RestoreResult:
    root = Path(base_dir).expanduser().resolve()
    paths = ensure_app_dirs(root)
    archive_path = Path(source).expanduser().resolve()
    manifest = _read_and_validate_manifest(archive_path)
    info = _info_from_manifest(archive_path, manifest)

    staging_parent = root.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ozprice_restore_", dir=staging_parent) as temp_name:
        temp_root = Path(temp_name)
        payload = temp_root / "payload"
        staged_files = payload / "source_files"
        staged_files.mkdir(parents=True)
        staged_db = payload / "ozpriceanalyzer.sqlite3"
        with zipfile.ZipFile(archive_path, "r") as archive:
            for item in manifest["files"]:
                archive_name = str(item["path"])
                destination = (
                    staged_db
                    if archive_name == DATABASE_ARCHIVE_PATH
                    else staged_files / Path(archive_name).name
                )
                _extract_verified_file(archive, item, destination)
        _validate_database(staged_db, manifest)
        _rewrite_source_paths(staged_db, paths["files"], staged_files)
        _validate_database(staged_db, manifest)

        safety_backup: Path | None = None
        if paths["database"].exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_backup = _unique_path(
                paths["backups"] / f"Автокопия_перед_восстановлением_{stamp}.ozbackup"
            )
            create_backup(root, safety_backup)

        _swap_restored_data(paths, staged_db, staged_files, temp_root / "rollback")
    return RestoreResult(info=info, safety_backup=safety_backup)


def suggested_backup_name() -> str:
    return f"OZPriceAnalyzer_{datetime.now():%Y-%m-%d_%H-%M}.ozbackup"


def _snapshot_database(source: Path, destination: Path) -> None:
    if not source.exists():
        raise BackupError("База приложения не найдена")
    try:
        with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            snapshot.execute("PRAGMA journal_mode = DELETE")
            snapshot.commit()
    except sqlite3.Error as exc:
        raise BackupError(f"Не удалось создать снимок базы: {exc}") from exc
    _validate_database(destination)


def _database_counts(path: Path) -> dict[str, int]:
    try:
        with closing(sqlite3.connect(path)) as db:
            return {
                "runs": int(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
                "products": int(db.execute("SELECT COUNT(*) FROM products").fetchone()[0]),
                "sources": int(db.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]),
            }
    except sqlite3.Error as exc:
        raise BackupError(f"Не удалось прочитать содержимое базы: {exc}") from exc


def _validate_database(path: Path, manifest: dict[str, object] | None = None) -> None:
    try:
        with closing(sqlite3.connect(path)) as db:
            integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise BackupError(f"Проверка базы не пройдена: {integrity}")
            tables = {str(row[0]) for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing = sorted(REQUIRED_TABLES - tables)
            if missing:
                raise BackupError(f"В резервной копии отсутствуют таблицы: {', '.join(missing)}")
        if manifest:
            actual = _database_counts(path)
            expected = manifest["counts"]
            for key in ("runs", "products", "sources"):
                if actual[key] != int(expected[key]):
                    raise BackupError(f"Количество записей {key} не совпадает с манифестом")
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError(f"Резервная база повреждена: {exc}") from exc


def _read_and_validate_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise BackupError("Файл резервной копии не найден")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise BackupError("В архиве слишком много файлов")
            if sum(item.file_size for item in members) > MAX_UNCOMPRESSED_SIZE:
                raise BackupError("Резервная копия слишком велика")
            names: set[str] = set()
            for member in members:
                _validate_archive_name(member.filename)
                if member.filename in names:
                    raise BackupError(f"В архиве повторяется файл: {member.filename}")
                names.add(member.filename)
            if "manifest.json" not in names:
                raise BackupError("В архиве отсутствует manifest.json")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_SIZE:
                raise BackupError("Манифест резервной копии слишком велик")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except BackupError:
        raise
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"Файл не является корректной резервной копией: {exc}") from exc

    if not isinstance(manifest, dict):
        raise BackupError("Манифест резервной копии поврежден")
    try:
        backup_version = int(manifest.get("backup_version", 0))
    except (TypeError, ValueError) as exc:
        raise BackupError("Версия резервной копии не поддерживается") from exc
    if manifest.get("format") != BACKUP_FORMAT or backup_version != BACKUP_VERSION:
        raise BackupError("Версия резервной копии не поддерживается")
    counts = manifest.get("counts")
    files = manifest.get("files")
    if not isinstance(counts, dict) or not isinstance(files, list):
        raise BackupError("Манифест резервной копии поврежден")
    try:
        if any(int(counts[key]) < 0 for key in ("runs", "products", "sources")):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError("В манифесте неверно указано количество записей") from exc
    expected_names = {"manifest.json"}
    manifest_names: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not {"path", "sha256", "size", "kind"}.issubset(item):
            raise BackupError("В манифесте есть некорректная запись файла")
        archive_name = str(item["path"])
        _validate_archive_name(archive_name)
        if archive_name in manifest_names:
            raise BackupError(f"В манифесте повторяется файл: {archive_name}")
        manifest_names.add(archive_name)
        try:
            size = int(item["size"])
        except (TypeError, ValueError) as exc:
            raise BackupError(f"В манифесте неверно указан размер: {archive_name}") from exc
        digest = str(item["sha256"])
        if size < 0 or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise BackupError(f"В манифесте неверна контрольная сумма: {archive_name}")
        if item["kind"] not in {"database", "source"}:
            raise BackupError(f"В манифесте неизвестный тип файла: {archive_name}")
        expected_names.add(archive_name)
    if DATABASE_ARCHIVE_PATH not in expected_names:
        raise BackupError("В резервной копии отсутствует база данных")
    if _file_entry(manifest, DATABASE_ARCHIVE_PATH)["kind"] != "database":
        raise BackupError("База данных неверно описана в манифесте")
    if expected_names != names:
        raise BackupError("Состав архива не совпадает с манифестом")
    return manifest


def _validate_archive_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        not name
        or "\\" in name
        or normalized.startswith("/")
        or ".." in parts
        or any(part in {"", "."} for part in parts)
    ):
        raise BackupError(f"Недопустимый путь внутри архива: {name}")


def _file_entry(manifest: dict[str, object], archive_path: str) -> dict[str, object]:
    for item in manifest["files"]:
        if item["path"] == archive_path:
            return item
    raise BackupError(f"В манифесте отсутствует {archive_path}")


def _extract_verified_file(archive: zipfile.ZipFile, item: dict[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(str(item["path"]), "r") as source, destination.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except KeyError as exc:
        raise BackupError(f"В архиве отсутствует {item['path']}") from exc
    if size != int(item["size"]) or digest.hexdigest() != str(item["sha256"]):
        destination.unlink(missing_ok=True)
        raise BackupError(f"Контрольная сумма не совпадает: {item['path']}")


def _verify_archive_items(archive: zipfile.ZipFile, manifest: dict[str, object]) -> None:
    for item in manifest["files"]:
        digest = hashlib.sha256()
        size = 0
        try:
            with archive.open(str(item["path"]), "r") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
        except KeyError as exc:
            raise BackupError(f"В архиве отсутствует {item['path']}") from exc
        if size != int(item["size"]) or digest.hexdigest() != str(item["sha256"]):
            raise BackupError(f"Контрольная сумма не совпадает: {item['path']}")


def _manifest_file(path: Path, archive_path: str, kind: str) -> dict[str, object]:
    return {
        "path": archive_path,
        "kind": kind,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rewrite_source_paths(database: Path, target_files: Path, staged_files: Path) -> None:
    try:
        with closing(sqlite3.connect(database)) as db:
            db.execute("PRAGMA journal_mode = DELETE")
            rows = db.execute("SELECT id, stored_path FROM source_files").fetchall()
            for row_id, stored_path in rows:
                filename = _stored_filename(stored_path)
                if not filename or not (staged_files / filename).is_file():
                    raise BackupError(f"Не найден сохраненный исходный файл: {filename or stored_path}")
                db.execute(
                    "UPDATE source_files SET stored_path = ? WHERE id = ?",
                    (str(target_files / filename), row_id),
                )
            db.commit()
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError(f"Не удалось подготовить пути к исходным файлам: {exc}") from exc


def _validate_referenced_file_names(database: Path, available_names: set[str]) -> None:
    try:
        with closing(sqlite3.connect(database)) as db:
            missing = sorted(
                {
                    filename
                    for (stored_path,) in db.execute("SELECT stored_path FROM source_files")
                    if (filename := _stored_filename(stored_path)) not in available_names
                }
            )
    except sqlite3.Error as exc:
        raise BackupError(f"Не удалось проверить сохраненные исходники: {exc}") from exc
    if missing:
        preview = ", ".join(missing[:5])
        suffix = f" и еще {len(missing) - 5}" if len(missing) > 5 else ""
        raise BackupError(f"Не найдены сохраненные исходные файлы: {preview}{suffix}")


def _stored_filename(value: object) -> str:
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise BackupError("Не удалось выбрать имя для страховочной копии")


def _swap_restored_data(paths: dict[str, Path], staged_db: Path, staged_files: Path, rollback: Path) -> None:
    rollback.mkdir(parents=True, exist_ok=True)
    old_files = rollback / "source_files"
    old_db = rollback / "ozpriceanalyzer.sqlite3"
    sidecars = [
        (Path(f"{paths['database']}-wal"), rollback / "ozpriceanalyzer.sqlite3-wal"),
        (Path(f"{paths['database']}-shm"), rollback / "ozpriceanalyzer.sqlite3-shm"),
    ]
    files_moved = False
    new_files_installed = False
    db_moved = False
    new_db_installed = False
    moved_sidecars: list[tuple[Path, Path]] = []
    try:
        if paths["files"].exists():
            os.replace(paths["files"], old_files)
            files_moved = True
        os.replace(staged_files, paths["files"])
        new_files_installed = True
        for source, destination in sidecars:
            if source.exists():
                os.replace(source, destination)
                moved_sidecars.append((source, destination))
        if paths["database"].exists():
            os.replace(paths["database"], old_db)
            db_moved = True
        os.replace(staged_db, paths["database"])
        new_db_installed = True
    except Exception as exc:
        if new_db_installed and paths["database"].exists():
            paths["database"].unlink()
        if db_moved and old_db.exists():
            os.replace(old_db, paths["database"])
        for original, saved in moved_sidecars:
            if saved.exists():
                os.replace(saved, original)
        if new_files_installed and paths["files"].exists():
            shutil.rmtree(paths["files"])
        if files_moved and old_files.exists():
            os.replace(old_files, paths["files"])
        raise BackupError(f"Восстановление отменено, текущие данные сохранены: {exc}") from exc


def _info_from_manifest(path: Path, manifest: dict[str, object]) -> BackupInfo:
    counts = manifest["counts"]
    source_entries = [item for item in manifest["files"] if item["kind"] == "source"]
    return BackupInfo(
        path=path,
        created_at=str(manifest.get("created_at", "")),
        app_version=str(manifest.get("app_version", "")),
        run_count=int(counts["runs"]),
        product_count=int(counts["products"]),
        source_count=int(counts["sources"]),
        source_size=sum(int(item["size"]) for item in source_entries),
    )
