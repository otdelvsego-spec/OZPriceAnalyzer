from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ozon_app.excel_reader import REPORT_ADDITIONAL_INCOME, parse_report, preview_pdf


PDF_TEXT = """
Акт о премии за расчеты баллами # 848264 от 31.01.2026
Ozon: Интернет Решения, ООО
Премия не изменяет цену оказанных Ozon Продавцу услуг.
Итого к начислению, руб. 61.40
"""


class _Page:
    def extract_text(self) -> str:
        return PDF_TEXT


class _Reader:
    pages = [_Page()]


class AdditionalIncomePdfTests(unittest.TestCase):
    def test_ozon_premium_act_is_parsed_as_additional_income(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MarketplaceDocumentCertificate.pdf"
            path.write_bytes(b"mock-pdf")
            with patch("pypdf.PdfReader", return_value=_Reader()):
                source = parse_report(path)

        self.assertEqual(source.report_type, REPORT_ADDITIONAL_INCOME)
        self.assertEqual(source.period_start.isoformat(), "2026-01-31")
        self.assertEqual(source.period_end.isoformat(), "2026-01-31")
        self.assertEqual(source.row_count, 1)
        self.assertEqual(source.total_amount, 61.40)
        row = source.additional_income_rows[0]
        self.assertEqual(row.document_number, "848264")
        self.assertEqual(row.income_type, "Премия за расчеты баллами")

    def test_pdf_preview_returns_page_and_text_lines(self) -> None:
        with patch("pypdf.PdfReader", return_value=_Reader()):
            headers, rows = preview_pdf("act.pdf")

        self.assertEqual(headers, ["Страница", "Текст"])
        self.assertTrue(any(row == ["1", "Итого к начислению, руб. 61.40"] for row in rows))


if __name__ == "__main__":
    unittest.main()
