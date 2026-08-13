from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from ozon_app.database import Database
from ozon_app.exporter import export_run
from ozon_app.models import ParsedSource, Product, ProductResult, RunCalculation


class DatabaseExporterTests(unittest.TestCase):
    def test_history_snapshot_and_excel_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "app.sqlite3")
            source_path = root / "source.xlsx"
            source = ParsedSource(
                path=source_path,
                file_hash="hash-1",
                report_type="ACCRUAL",
                sheet_name="Начисления",
                header_row=1,
            )
            calculation = RunCalculation(
                run_id=None,
                period_start=None,
                period_end=None,
                tax_rate=0.04,
                products=[
                    ProductResult(
                        article="A-1",
                        name="Товар",
                        material_cost=70,
                        labor_cost=30,
                        category="Старая категория",
                        units=2,
                        revenue_no_points=500,
                        commission=-100,
                        financial_result=400,
                    )
                ],
                unallocated_total=-50,
                unallocated={"Подписка Premium": (1, -50)},
                accrual_stats={"Подписка Premium": (0, 1)},
                source_files=[source],
            )
            run_id = database.save_run(calculation, {str(source_path): source_path})

            loaded = database.load_calculation(run_id)
            self.assertEqual(loaded.products[0].material_cost, 70)
            self.assertEqual(loaded.products[0].labor_cost, 30)
            self.assertEqual(loaded.products[0].category, "Старая категория")
            self.assertEqual(loaded.unallocated_total, -50)

            database.save_product(
                Product("A-1", "Товар", material_cost=999, labor_cost=1, category="Новая категория")
            )
            refreshed = database.load_calculation(run_id)
            self.assertEqual(refreshed.products[0].category, "Новая категория")
            self.assertEqual(refreshed.products[0].material_cost, 70)

            destination = root / "result.xlsx"
            export_run(database, run_id, destination)
            workbook = load_workbook(destination, data_only=False)
            try:
                self.assertEqual(workbook.sheetnames, ["КонсОтчет", "Разбивка"])
                self.assertEqual(workbook["КонсОтчет"]["H4"].value, -50)
                self.assertEqual(workbook["Разбивка"]["A5"].value, "Подписка Premium")
                self.assertEqual(workbook["Разбивка"]["C5"].value, -50)
                self.assertTrue(str(workbook["КонсОтчет"]["AO8"].value).startswith("=IF"))
            finally:
                workbook.close()


if __name__ == "__main__":
    unittest.main()
