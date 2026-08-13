from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from openpyxl import Workbook

from ozon_app.models import AccrualRow, ParsedSource, Product, ProductResult, RunCalculation
from ozon_app.service import AppService, ImportSession


def _write_accrual_report(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Начисления"
    sheet.append(
        [
            "ID начисления",
            "Дата начисления",
            "Тип начисления",
            "Артикул",
            "SKU",
            "Название товара",
            "Количество",
            "Цена продавца",
            "Сумма итого, руб.",
        ]
    )
    sheet.append(
        [
            "operation-1",
            date(2026, 5, 1),
            "Эквайринг",
            "ARCHIVE-1",
            1000000001,
            "Архивный тестовый товар",
            0,
            0,
            -7.5,
        ]
    )
    workbook.save(path)
    workbook.close()


class HistoryRecalculationTests(unittest.TestCase):
    def test_new_import_uses_archived_catalog_item_when_source_references_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AppService(root)
            service.db.save_product(
                Product("ARCHIVE-1", "Архивный тестовый товар", 50, 50, active=False),
                source="Тест",
            )
            path = root / "source.xlsx"
            path.write_bytes(b"stored source")
            source = ParsedSource(
                path=path,
                file_hash="hash",
                report_type="ACCRUAL",
                sheet_name="Начисления",
                header_row=1,
                accrual_rows=[
                    AccrualRow(
                        source_name=path.name,
                        sheet_name="Начисления",
                        row_number=2,
                        accrual_id="1",
                        accrual_date=date(2026, 5, 1),
                        accrual_type="Эквайринг",
                        article="ARCHIVE-1",
                        sku="1000000001",
                        product_name="Архивный тестовый товар",
                        quantity=0,
                        seller_price=0,
                        amount=-7.5,
                    )
                ],
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 1),
            )

            calculation = service.complete_import(
                ImportSession(sources=[source], unknown_products=[])
            )

            item = next(row for row in calculation.products if row.article == "ARCHIVE-1")
            self.assertEqual(item.units, 0)
            self.assertAlmostEqual(item.acquiring, -7.5)
            self.assertEqual(calculation.skipped_articles, {})

    def test_recalculation_recovers_archived_product_and_preserves_history_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AppService(root)
            incoming = root / "Отчет по начислениям_01.05.2026-31.05.2026.xlsx"
            stored = service.paths["files"] / "stored.xlsx"
            _write_accrual_report(incoming)
            stored.write_bytes(incoming.read_bytes())

            service.db.save_product(
                Product(
                    article="ARCHIVE-1",
                    name="Архивный тестовый товар",
                    material_cost=60,
                    labor_cost=40,
                    active=False,
                    category="Тестовая категория",
                ),
                source="Тест",
            )
            source = ParsedSource(
                path=incoming,
                file_hash="old-hash",
                report_type="ACCRUAL",
                sheet_name="Начисления",
                header_row=1,
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 1),
            )
            old_calculation = RunCalculation(
                run_id=None,
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 1),
                tax_rate=0.04,
                products=[
                    ProductResult(
                        article="ARCHIVE-1",
                        name="Историческое наименование",
                        material_cost=50,
                        labor_cost=50,
                        category="Тестовая категория",
                    )
                ],
                unallocated_total=0,
                unallocated={},
                accrual_stats={},
                source_files=[source],
            )
            old_id = service.db.save_run(
                old_calculation,
                {str(incoming): stored},
            )
            service.db.rename_run(old_id, "Май — проверенный отчет")
            service.db.save_planned_price(old_id, "ARCHIVE-1", 175.0)
            old_created_at = service.db.list_runs()[0].created_at

            repair = service.recalculate_history()

            self.assertEqual(repair.replaced_runs, 1)
            self.assertEqual(repair.recovered_product_rows, 1)
            self.assertAlmostEqual(repair.financial_result_delta, -7.5)
            new_id = repair.old_to_new[old_id]
            run = service.db.list_runs()[0]
            self.assertEqual(run.id, new_id)
            self.assertEqual(run.report_name, "Май — проверенный отчет")
            self.assertEqual(run.created_at, old_created_at)
            self.assertEqual(service.db.planned_prices(new_id)["ARCHIVE-1"], 175.0)

            calculation = service.db.load_calculation(new_id)
            item = next(row for row in calculation.products if row.article == "ARCHIVE-1")
            self.assertEqual(item.name, "Историческое наименование")
            self.assertEqual(item.material_cost, 50)
            self.assertEqual(item.labor_cost, 50)
            self.assertEqual(item.units, 0)
            self.assertAlmostEqual(item.acquiring, -7.5)
            self.assertAlmostEqual(item.financial_result, -7.5)


if __name__ == "__main__":
    unittest.main()
