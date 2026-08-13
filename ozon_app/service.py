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


@dataclass(slots=True)
class ImportBatch:
    sessions: list[ImportSession]
    unknown_products: list[UnknownProduct]

    @property
    def sources(self) -> list[ParsedSource]:
        return [source for session in self.sessions for source in session.sources]

    @property
    def duplicate_sources(self) -> list[ParsedSource]:
        return [
            source
            for session in self.sessions
            for source in session.duplicate_sources
        ]


class AppService:
    def __init__(self, base_dir: Path | None = None):
        self.paths = ensure_app_dirs(base_dir)
        self.db = Database(self.paths["database"])

    def prepare_import(self, file_paths: list[str | Path]) -> ImportBatch:
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
        sessions = split_import_sources(sources)
        products = self.db.product_map(active_only=False)
        unknown = discover_unknown_products(sources, products)
        duplicate_hashes = {source.file_hash for source in duplicates}
        for session in sessions:
            session.duplicate_sources = [
                source for source in session.sources if source.file_hash in duplicate_hashes
            ]
        return ImportBatch(sessions=sessions, unknown_products=unknown)

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
        return self.complete_import_batch(
            [session],
            created_products=created_products,
            skipped_articles=skipped_articles,
            replace_run_ids_by_session=[list(replace_run_ids or [])],
            source_period_warnings_by_session=[list(source_period_warnings or [])],
        )[0]

    def complete_import_batch(
        self,
        sessions: list[ImportSession],
        created_products: list[Product] | None = None,
        skipped_articles: set[str] | None = None,
        replace_run_ids_by_session: list[list[int]] | None = None,
        source_period_warnings_by_session: list[list[str]] | None = None,
    ) -> list[RunCalculation]:
        if not sessions:
            raise ValueError("Нет подготовленных отчетов для сохранения")
        replacements = replace_run_ids_by_session or [[] for _session in sessions]
        warnings = source_period_warnings_by_session or [[] for _session in sessions]
        if len(replacements) != len(sessions) or len(warnings) != len(sessions):
            raise ValueError("Нарушена структура пакетного импорта")

        tax_rate = float(self.db.get_setting("tax_rate", "0.04"))
        if tax_rate < 0 or tax_rate > 1:
            raise ValueError("Налоговая ставка должна быть от 0 до 100%")
        product_map = self.db.product_map(active_only=True)
        for product in created_products or []:
            if product.active:
                product_map[product.article] = product

        # Calculate every period before changing history. A malformed later month
        # therefore cannot leave a normally failed batch half-created.
        calculations: list[RunCalculation] = []
        for session, session_warnings in zip(sessions, warnings):
            calculation = calculate_run(
                session.sources,
                product_map,
                tax_rate=tax_rate,
                skipped_articles=skipped_articles,
            )
            calculation.source_period_warnings = list(session_warnings)
            calculations.append(calculation)

        for product in created_products or []:
            self.db.save_product(product, source="Новый артикул из отчета")
        for calculation, replace_run_ids in zip(calculations, replacements):
            stored_paths = self._store_source_files(calculation.source_files)
            calculation.run_id = self.db.save_run(
                calculation,
                stored_paths,
                replace_run_ids=replace_run_ids,
            )
        return calculations

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


def split_import_sources(sources: list[ParsedSource]) -> list[ImportSession]:
    """Create one calculation session per accrual file and match realization by month."""
    accrual_sources = [source for source in sources if source.report_type == REPORT_ACCRUAL]
    realization_sources = [
        source for source in sources if source.report_type == REPORT_REALIZATION
    ]
    if not accrual_sources:
        raise ValueError("Для расчета нужен хотя бы один отчет по начислениям")

    sessions = [ImportSession(sources=[source], unknown_products=[]) for source in accrual_sources]
    sessions.sort(key=_session_sort_key)
    accruals_by_month: dict[tuple[int, int], list[ImportSession]] = {}
    for session in sessions:
        month = _session_month(session)
        if month is not None:
            accruals_by_month.setdefault(month, []).append(session)

    for source in sorted(realization_sources, key=_source_sort_key):
        month = _source_month(source)
        matches = accruals_by_month.get(month, []) if month is not None else []
        if len(matches) == 1:
            matches[0].sources.append(source)
            continue

        if len(sessions) == 1:
            # Preserve the explicit confirmation flow for a single accrual report.
            # ImportSession.realization_period_warnings() will record the mismatch.
            sessions[0].sources.append(source)
            continue

        period = _source_period(source)
        if month is None:
            raise ValueError(
                f"Не удалось определить один календарный месяц отчета по выкупам "
                f"«{source.path.name}» ({period}). При пакетном импорте невозможно "
                "надежно выбрать отчет по начислениям. Добавьте файл с однозначным "
                "периодом или импортируйте этот отчет отдельно."
            )
        if not matches:
            raise ValueError(
                f"Для отчета по выкупам «{source.path.name}» ({period}) не найден "
                f"отчет по начислениям за {month[1]:02d}.{month[0]}. "
                "Добавьте соответствующий отчет по начислениям или исключите этот "
                "файл из пакетного импорта."
            )
        names = ", ".join(f"«{session.sources[0].path.name}»" for session in matches)
        raise ValueError(
            f"Отчет по выкупам «{source.path.name}» ({period}) нельзя распределить "
            f"однозначно: за {month[1]:02d}.{month[0]} выбрано несколько отчетов "
            f"по начислениям: {names}. Импортируйте их раздельно."
        )

    return sessions


def _session_month(session: ImportSession) -> tuple[int, int] | None:
    if session.period_start is None or session.period_end is None:
        return None
    start = session.period_start
    end = session.period_end
    if (start.year, start.month) != (end.year, end.month):
        return None
    return start.year, start.month


def _source_month(source: ParsedSource) -> tuple[int, int] | None:
    if source.period_start is None or source.period_end is None:
        return None
    start = source.period_start
    end = source.period_end
    if (start.year, start.month) != (end.year, end.month):
        return None
    return start.year, start.month


def _source_period(source: ParsedSource) -> str:
    if source.period_start is None or source.period_end is None:
        return "период не определен"
    return f"{source.period_start:%d.%m.%Y}–{source.period_end:%d.%m.%Y}"


def _session_sort_key(session: ImportSession) -> tuple[date, date, str]:
    return (
        session.period_start or date.max,
        session.period_end or date.max,
        session.sources[0].path.name.casefold(),
    )


def _source_sort_key(source: ParsedSource) -> tuple[date, date, str]:
    return (
        source.period_start or date.max,
        source.period_end or date.max,
        source.path.name.casefold(),
    )
