from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from ozon_app.backup import BackupError, create_backup, inspect_backup, restore_backup
from ozon_app.config import ensure_app_dirs
from ozon_app.database import Database
from ozon_app.models import Product


class BackupTests(unittest.TestCase):
    def test_creates_and_restores_portable_history_with_safety_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source_root = workspace / "computer_a"
            source_paths = ensure_app_dirs(source_root)
            source_db = Database(source_paths["database"])
            source_db.set_setting("theme", "dark")
            source_db.save_product(Product("CUSTOM", "Новый товар", 75, 25), source="Тест")
            stored = source_paths["files"] / "abc123_report.xlsx"
            stored.write_bytes(b"test xlsx contents")
            digest = hashlib.sha256(stored.read_bytes()).hexdigest()
            with source_db.transaction() as db:
                run_id = db.execute(
                    """
                    INSERT INTO runs(
                        period_start, period_end, tax_rate, source_count, units, revenue,
                        financial_result, cost_sold, tax, net_profit, unallocated_total,
                        realization_revenue, realization_units, duplicate_realization_rows,
                        already_accrued_realization_rows, status
                    ) VALUES ('2026-07-01', '2026-07-29', 0.04, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'Готов')
                    """
                ).lastrowid
                db.execute(
                    """
                    INSERT INTO source_files(
                        run_id, original_name, original_path, stored_path, file_hash,
                        report_type, sheet_name, header_row, row_count, total_amount
                    ) VALUES (?, 'report.xlsx', 'C:\\old\\report.xlsx', ?, ?, 'ACCRUAL', 'Начисления', 1, 1, 0)
                    """,
                    (run_id, r"C:\Users\Vladimir\OZPriceAnalyzer\source_files\abc123_report.xlsx", digest),
                )

            archive = workspace / "portable.ozbackup"
            created = create_backup(source_root, archive)
            inspected = inspect_backup(archive)
            self.assertEqual(created.run_count, 1)
            self.assertEqual(inspected.product_count, len(source_db.list_products()))
            self.assertEqual(inspected.source_count, 1)

            target_root = workspace / "computer_b"
            target_paths = ensure_app_dirs(target_root)
            target_db = Database(target_paths["database"])
            target_db.set_setting("theme", "light")
            (target_paths["files"] / "old_file.xlsx").write_bytes(b"old")

            result = restore_backup(target_root, archive)
            restored_db = Database(target_paths["database"])
            self.assertEqual(restored_db.get_setting("theme"), "dark")
            self.assertIn("CUSTOM", restored_db.product_map(active_only=False))
            self.assertEqual(len(restored_db.list_runs()), 1)
            restored_source = restored_db.list_source_files(int(run_id))[0]
            restored_path = Path(str(restored_source["stored_path"]))
            self.assertEqual(restored_path.parent, target_paths["files"])
            self.assertTrue(restored_path.is_file())
            self.assertFalse((target_paths["files"] / "old_file.xlsx").exists())
            self.assertIsNotNone(result.safety_backup)
            self.assertTrue(result.safety_backup.is_file())
            self.assertEqual(inspect_backup(result.safety_backup).run_count, 0)

    def test_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "invalid.ozbackup"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../outside.txt", "bad")
                output.writestr("manifest.json", "{}")
            with self.assertRaises(BackupError) as context:
                inspect_backup(archive)
            self.assertIn("Недопустимый путь", str(context.exception))

    def test_rejects_changed_file_before_replacing_current_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source_root = workspace / "source"
            source_paths = ensure_app_dirs(source_root)
            source_db = Database(source_paths["database"])
            source_file = source_paths["files"] / "orphan.xlsx"
            source_file.write_bytes(b"original")
            valid = create_backup(source_root, workspace / "valid.ozbackup")

            tampered = workspace / "tampered.ozbackup"
            with zipfile.ZipFile(valid.path, "r") as source, zipfile.ZipFile(tampered, "w") as output:
                for item in source.infolist():
                    content = source.read(item.filename)
                    if item.filename == "source_files/orphan.xlsx":
                        content = b"changed"
                    output.writestr(item, content)

            target_root = workspace / "target"
            target_paths = ensure_app_dirs(target_root)
            target_db = Database(target_paths["database"])
            target_db.set_setting("theme", "light")
            with self.assertRaises(BackupError) as inspect_context:
                inspect_backup(tampered)
            self.assertIn("Контрольная сумма", str(inspect_context.exception))
            with self.assertRaises(BackupError) as context:
                restore_backup(target_root, tampered)
            self.assertIn("Контрольная сумма", str(context.exception))
            self.assertEqual(Database(target_paths["database"]).get_setting("theme"), "light")


if __name__ == "__main__":
    unittest.main()
