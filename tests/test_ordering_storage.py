from __future__ import annotations

import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from ozon_app.config import (
    ensure_app_dirs,
    read_storage_location,
    save_storage_location,
)
from ozon_app.database import Database
from ozon_app.models import Product
from ozon_app.ordering import default_article_order
from ozon_app.storage import StorageMigrationError, migrate_storage


class ProductOrderingTests(unittest.TestCase):
    def test_default_order_groups_and_naturally_sorts_articles(self) -> None:
        articles = [
            "Бант 10",
            "ГС20",
            "БРГС2",
            "Бант 2",
            "ГС3",
            "БРГС10",
            "Другое",
        ]
        self.assertEqual(
            default_article_order(articles),
            ["БРГС2", "БРГС10", "ГС3", "ГС20", "Бант 2", "Бант 10", "Другое"],
        )

    def test_database_initial_order_and_manual_order_are_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            database = Database(path)
            initial = [product.article for product in database.list_products()]
            self.assertTrue(initial[:8] == default_article_order(initial)[:8])
            self.assertTrue(all(article.startswith("БРГС") for article in initial[:8]))
            self.assertTrue(all(article.startswith("ГС") for article in initial[8:14]))
            self.assertTrue(all(article.casefold().startswith("бант") for article in initial[14:]))

            changed = list(initial)
            changed[0], changed[1] = changed[1], changed[0]
            database.reorder_products(changed)
            reopened = Database(path)
            self.assertEqual([product.article for product in reopened.list_products()], changed)

    def test_new_product_is_inserted_at_end_of_its_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "app.sqlite3")
            database.save_product(Product("ГС999", "Новый ГС", 10, 2))
            articles = [product.article for product in database.list_products()]
            position = articles.index("ГС999")
            self.assertTrue(all(value.startswith(("БРГС", "ГС")) for value in articles[: position + 1]))
            self.assertTrue(articles[position + 1].casefold().startswith("бант"))

    def test_existing_database_without_sort_column_is_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    """
                    CREATE TABLE products (
                        article TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        material_cost REAL NOT NULL DEFAULT 0,
                        labor_cost REAL NOT NULL DEFAULT 0,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                db.executemany(
                    "INSERT INTO products(article, name) VALUES (?, ?)",
                    [("Бант 02", "Бант"), ("ГС2", "ГС"), ("БРГС10", "БРГС")],
                )
                db.commit()
            database = Database(path)
            self.assertEqual(
                [product.article for product in database.list_products()],
                ["БРГС10", "ГС2", "Бант 02"],
            )

    def test_history_is_sorted_by_report_period_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "app.sqlite3")
            inserted: dict[str, int] = {}
            with database.transaction() as db:
                for period in ("2026-03-01", "2026-07-01", "2026-05-01"):
                    inserted[period] = int(
                        db.execute(
                            """
                            INSERT INTO runs(
                                period_start, period_end, tax_rate, source_count, units, revenue,
                                financial_result, cost_sold, tax, net_profit, unallocated_total,
                                realization_revenue, realization_units, duplicate_realization_rows,
                                already_accrued_realization_rows, status
                            ) VALUES (?, ?, 0.04, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'Готов')
                            """,
                            (period, period),
                        ).lastrowid
                    )
            self.assertEqual(
                [run.id for run in database.list_runs()],
                [inserted["2026-03-01"], inserted["2026-05-01"], inserted["2026-07-01"]],
            )


class StorageTests(unittest.TestCase):
    def test_storage_location_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "settings" / "storage.json"
            destination = root / "Данные Ozon"
            save_storage_location(destination, config)
            self.assertEqual(read_storage_location(config), destination.resolve())

    def test_migration_copies_database_sources_exports_and_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "current"
            source_paths = ensure_app_dirs(source)
            database = Database(source_paths["database"])
            database.set_setting("theme", "light")
            database.save_product(Product("CUSTOM", "Пользовательский товар", 50, 10))
            (source_paths["files"] / "source.xlsx").write_bytes(b"source")
            (source_paths["exports"] / "report.xlsx").write_bytes(b"report")
            (source_paths["backups"] / "old.ozbackup").write_bytes(b"backup")

            destination = workspace / "new-empty"
            destination.mkdir()
            result = migrate_storage(source, destination)

            migrated = Database(destination / "ozpriceanalyzer.sqlite3")
            self.assertEqual(migrated.get_setting("theme"), "light")
            self.assertIn("CUSTOM", migrated.product_map(active_only=False))
            self.assertTrue((destination / "source_files" / "source.xlsx").is_file())
            self.assertTrue((destination / "exports" / "report.xlsx").is_file())
            self.assertTrue((destination / "backups" / "old.ozbackup").is_file())
            self.assertTrue((source / "ozpriceanalyzer.sqlite3").is_file())
            self.assertEqual(result.destination, destination.resolve())

    def test_migration_rejects_nonempty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "source"
            Database(ensure_app_dirs(source)["database"])
            destination = workspace / "not-empty"
            destination.mkdir()
            (destination / "existing.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(StorageMigrationError):
                migrate_storage(source, destination)
            self.assertEqual((destination / "existing.txt").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
