from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .calculator import calculate_run, discover_unknown_products
from .config import ensure_app_dirs
from .database import Database
from .excel_reader import REPORT_ACCRUAL, REPORT_REALIZATION, parse_report
from .models import ParsedSource, Product, RunCalculation, UnknownProduct


@dataclass(slots=True)
class ImportSession:
    sources: list[ParsedSource]
    unknown_products: list[UnknownProduct]
    duplicate_sources: list[ParsedSource] = field(default_factory=list)

    @property
    def has_accrual(self) -> bool:
        return any(source.report_type == REPORT_ACCRUAL for source in self.sources)

    @property
    def has_realization(self) -> bool:
        return any(source.report_type == REPORT_REALIZATION for source in self.sources)

    @property
    def period_start(self) -> date | None:
        dates = [
            row.accrual_date
            for source in self.sources
            for row in source.accrual_rows
            if row.accrual_date is not None
        ]
        return min(dates) if dates else None

    @property
    def period_end(self) -> date | None:
        dates = [
            row.accrual_date
            for source in self.sources
            for row in source.accrual_rows
            if row.accrual_date is not None
        ]
        return max(dates) if dates else None

    def realization_period_warnings(self) -> list[str]:
        realization_sources = [
            source for source in self.sources if source.report_type == REPORT_REALIZATION
        ]
        if not realization_sources:
            return []

        accrual_months = {
            (row.accrual_date.year, row.accrual_date.month)
            for source in self.sources
            for row in source.accrual_rows
            if row.accrual_date is not None
        }
        if not accrual_months:
            return [
                "В отчете по начислениям не удалось определить месяц, "
                "поэтому совместимость периодов не проверена."
            ]

        expected = _month_list(accrual_months)
        warnings: list[str] = []
        for source in realization_sources:
            if source.period_start is None or source.period_end is None:
                warnings.append(
                    f"«{source.path.name}»: период выкупов не удалось определить; "
                    f"ожидаемый месяц: {expected}."
                )
                continue
            start_month = (source.period_start.year, source.period_start.month)
            end_month = (source.period_end.year, source.period_end.month)
            actual_period = (
                f"{source.period_start:%d.%m.%Y}–{source.period_end:%d.%m.%Y}"
            )
            if start_month != end_month:
                warnings.append(
                    f"«{source.path.name}»: период {actual_period} охватывает "
                    f"несколько месяцев; ожидаемый месяц: {expected}."
                )
            elif start_month not in accrual_months:
                warnings.append(
                    f"«{source.path.name}»: период выкупов {actual_period} не относится "
                    f"к месяцу отчета по начислениям ({expected})."
                )
        return warnings


class AppService:
    def __init__(self, base_dir: Path | None = None):
        self.paths = ensure_app_dirs(base_dir)
        self.db = Database(self.paths["database"])

    def prepare_import(self, file_paths: list[str | Path]) -> ImportSession:
        if not file_paths:
            raise ValueError("Не выбраны исходные файлы")
        sources: list[ParsedSource] = []
        duplicates: list[ParsedSource] = []
        selected_hashes: set[str] = set()
        for path in file_paths:
            source = parse_report(path)
            if source.file_hash in selected_hashes:
                raise ValueError(
                    f"Файл «{source.path.name}» выбран повторно. "
                    "Импорт прерван, чтобы не удваивать суммы."
                )
            source.duplicate_run_ids = self.db.find_runs_by_hash(source.file_hash)
            if source.duplicate_run_ids:
                duplicates.append(source)
            selected_hashes.add(source.file_hash)
            sources.append(source)
        if not any(source.report_type == REPORT_ACCRUAL for source in sources):
            raise ValueError("Для расчета нужен хотя бы один отчет по начислениям")
        products = self.db.product_map(active_only=False)
        unknown = discover_unknown_products(sources, products)
        return ImportSession(sources=sources, unknown_products=unknown, duplicate_sources=duplicates)

    def replacement_run_ids(self, session: ImportSession) -> list[int]:
        if session.period_start is None or session.period_end is None:
            if session.duplicate_sources:
                raise ValueError(
                    "Эти файлы уже использовались, но период нового отчета "
                    "не удалось определить. Импорт прерван."
                )
            return []

        run_ids = self.db.find_runs_by_period(session.period_start, session.period_end)
        duplicate_ids = {
            run_id
            for source in session.duplicate_sources
            for run_id in source.duplicate_run_ids
        }
        unrelated_duplicates = duplicate_ids.difference(run_ids)
        if unrelated_duplicates:
            raise ValueError(
                "Один из выбранных файлов уже использовался в отчете за другой период. "
                "Импорт прерван, чтобы не удваивать суммы."
            )
        return run_ids

    def complete_import(
        self,
        session: ImportSession,
        created_products: list[Product] | None = None,
        skipped_articles: set[str] | None = None,
        replace_run_ids: list[int] | None = None,
        source_period_warnings: list[str] | None = None,
    ) -> RunCalculation:
        for product in created_products or []:
            self.db.save_product(product, source="Новый артикул из отчета")
        tax_rate = float(self.db.get_setting("tax_rate", "0.04"))
        if tax_rate < 0 or tax_rate > 1:
            raise ValueError("Налоговая ставка должна быть от 0 до 100%")
        calculation = calculate_run(
            session.sources,
            self.db.product_map(active_only=True),
            tax_rate=tax_rate,
            skipped_articles=skipped_articles,
        )
        calculation.source_period_warnings = list(source_period_warnings or [])
        stored_paths = self._store_source_files(session.sources)
        calculation.run_id = self.db.save_run(
            calculation,
            stored_paths,
            replace_run_ids=replace_run_ids,
        )
        return calculation

    def _store_source_files(self, sources: list[ParsedSource]) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for source in sources:
            safe_name = re.sub(r"[^\w.()\- ]+", "_", source.path.name, flags=re.UNICODE).strip()
            destination = self.paths["files"] / f"{source.file_hash[:12]}_{safe_name}"
            if not destination.exists():
                shutil.copy2(source.path, destination)
            result[str(source.path)] = destination
        return result

    def latest_run_id(self) -> int | None:
        runs = self.db.list_runs()
        return runs[-1].id if runs else None


def _month_list(months: set[tuple[int, int]]) -> str:
    return ", ".join(f"{month:02d}.{year}" for year, month in sorted(months))
