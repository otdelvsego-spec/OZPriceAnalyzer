from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .calculator import calculate_scenario, discover_unknown_products
from .comparison import ComparisonMetric, compare_calculations
from .excel_reader import REPORT_REALIZATION, preview_sheet, workbook_sheet_names
from .exporter import export_run, suggested_export_name
from .models import Product, ProductResult, RunCalculation, ScenarioRow, UnknownProduct
from .service import AppService, ImportSession
from .theme import apply_theme


THEME_LABELS = {"Системная": "system", "Темная": "dark", "Светлая": "light"}
THEME_VALUES = {value: key for key, value in THEME_LABELS.items()}
DUPLICATE_LABELS = {"Спрашивать": "ask", "Пропускать": "skip", "Разрешать": "allow"}
DUPLICATE_VALUES = {value: key for key, value in DUPLICATE_LABELS.items()}


class OZPriceAnalyzerApp(tk.Tk):
    def __init__(self, service: AppService | None = None):
        super().__init__()
        self.service = service or AppService()
        self.db = self.service.db
        self.current_run_id: int | None = None
        self.current_calculation: RunCalculation | None = None
        self.run_display_to_id: dict[str, int] = {}
        self.source_by_iid: dict[str, dict[str, object]] = {}
        self.preview_headers: list[str] = []
        self.preview_rows: list[list[str]] = []
        self.preview_path: str | None = None
        self.scenario_rows: dict[str, ScenarioRow] = {}
        self.import_in_progress = False
        self.import_queue: queue.Queue[tuple[ImportSession | None, Exception | None]] = queue.Queue()
        self.colors = apply_theme(self, self.db.get_setting("theme", "system"))

        self.title("OZ Price Analyzer")
        self.geometry("1540x920")
        self.minsize(1180, 720)
        self.option_add("*Font", "Segoe UI 10")
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))

        self.overview_tab = ttk.Frame(self.notebook, padding=4)
        self.sources_tab = ttk.Frame(self.notebook, padding=4)
        self.breakdown_tab = ttk.Frame(self.notebook, padding=4)
        self.guide_tab = ttk.Frame(self.notebook, padding=4)
        self.scenario_tab = ttk.Frame(self.notebook, padding=4)
        self.history_tab = ttk.Frame(self.notebook, padding=4)
        self.comparison_tab = ttk.Frame(self.notebook, padding=4)
        self.settings_tab = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(self.overview_tab, text="Обзор")
        self.notebook.add(self.sources_tab, text="Исходные файлы")
        self.notebook.add(self.breakdown_tab, text="Разбивка")
        self.notebook.add(self.guide_tab, text="Справочник начислений")
        self.notebook.add(self.scenario_tab, text="Сценарий цены")
        self.notebook.add(self.history_tab, text="История отчетов")
        self.notebook.add(self.comparison_tab, text="Сравнение периодов")
        self.notebook.add(self.settings_tab, text="Настройки")

        self._build_overview_tab()
        self._build_sources_tab()
        self._build_breakdown_tab()
        self._build_guide_tab()
        self._build_scenario_tab()
        self._build_history_tab()
        self._build_comparison_tab()
        self._build_settings_tab()

        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=2, column=0, sticky="ew", padx=22, pady=(0, 10)
        )

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(22, 18, 22, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title_box = ttk.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="OZ Price Analyzer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            title_box,
            text="Отчеты Ozon, история, контроль начислений и плановая доходность",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        actions = ttk.Frame(header)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(actions, text="Расчет:", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.run_var = tk.StringVar()
        self.run_combo = ttk.Combobox(actions, textvariable=self.run_var, state="readonly", width=32)
        self.run_combo.grid(row=0, column=1, padx=(0, 12))
        self.run_combo.bind("<<ComboboxSelected>>", self._on_run_selected)
        ttk.Button(actions, text="Импортировать отчеты", style="Accent.TButton", command=self.import_reports).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(actions, text="Экспорт в Excel", command=self.export_current_run).grid(row=0, column=3, padx=5)

    def _build_overview_tab(self) -> None:
        self.overview_tab.columnconfigure(0, weight=1)
        self.overview_tab.rowconfigure(2, weight=1)
        ttk.Label(self.overview_tab, text="Итоговый отчет", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 8)
        )
        self.kpi_frame = ttk.Frame(self.overview_tab)
        self.kpi_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for column in range(6):
            self.kpi_frame.columnconfigure(column, weight=1)
        self.kpi_vars: dict[str, tk.StringVar] = {}
        cards = [
            ("revenue", "Выручка"),
            ("net_profit", "Чистая прибыль"),
            ("profitability", "Доходность"),
            ("units", "Продажи, шт."),
            ("unallocated", "Нераспределенные"),
            ("files", "Исходные файлы"),
        ]
        for index, (key, title) in enumerate(cards):
            self.kpi_vars[key] = tk.StringVar(value="—")
            card = ttk.Frame(self.kpi_frame, style="Card.TFrame", padding=(16, 14))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0 if index == 5 else 5))
            ttk.Label(card, text=title, style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, textvariable=self.kpi_vars[key], style="Kpi.TLabel").grid(
                row=1, column=0, sticky="w", pady=(5, 0)
            )

        columns = [
            "article", "name", "unit_cost", "material", "labor", "material_sold", "labor_sold", "cost_sold",
            "profitability", "net_unit", "profit_unit", "net_total", "profit_total", "avg_price", "tax",
            "taxable", "units", "revenue", "revenue_no_points", "partner", "points", "commission", "processing",
            "delivery", "logistics", "reverse", "returns", "acquiring", "stars", "packaging", "compensation",
            "other", "financial_result",
        ]
        headings = [
            "Артикул", "Наименование", "Итого с/с", "Материал", "Трудозатраты", "Материал проданного",
            "Трудозатраты проданного", "С/с проданного", "Доходность", "Чистая прибыль на ед.",
            "Прибыль от продаж на ед.", "Чистая прибыль всего", "Прибыль от продаж всего", "Средняя цена",
            "Налог", "Налогооблагаемый доход", "Продажи", "Выручка с баллами", "Выручка без баллов",
            "Программы партнеров", "Баллы", "Комиссия Ozon", "Обработка отправления", "Доставка до ПВЗ",
            "Логистика", "Обратная логистика", "Возвраты/отмены", "Эквайринг", "Звездные товары",
            "Упаковка и материалы", "Компенсации Ozon", "Прочие начисления", "Финрезультат Ozon",
        ]
        self.overview_tree = self._create_tree(self.overview_tab, columns, headings, row=2, widths=[120, 230] + [125] * 31)

    def _build_sources_tab(self) -> None:
        self.sources_tab.columnconfigure(0, weight=1)
        self.sources_tab.rowconfigure(3, weight=1)
        source_header = ttk.Frame(self.sources_tab)
        source_header.grid(row=0, column=0, sticky="ew", pady=(10, 8))
        source_header.columnconfigure(0, weight=1)
        ttk.Label(source_header, text="Файлы выбранного расчета", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(source_header, text="Просмотреть любой XLSX", command=self.browse_xlsx_preview).grid(
            row=0, column=1, sticky="e"
        )
        source_columns = ["name", "type", "rows", "amount", "period", "hash"]
        source_headings = ["Файл", "Тип", "Строк", "Сумма", "Период", "SHA-256"]
        self.source_tree = self._create_tree(
            self.sources_tab, source_columns, source_headings, row=1, height=6, widths=[380, 150, 80, 130, 190, 220]
        )
        self.source_tree.bind("<<TreeviewSelect>>", self._on_source_selected)

        controls = ttk.Frame(self.sources_tab, padding=(0, 10, 0, 8))
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Label(controls, text="Лист:").grid(row=0, column=0, padx=(0, 6))
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(controls, textvariable=self.sheet_var, state="readonly", width=35)
        self.sheet_combo.grid(row=0, column=1, padx=(0, 18))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_preview())
        ttk.Label(controls, text="Поиск в показанных строках:").grid(row=0, column=2, padx=(0, 6))
        self.preview_search_var = tk.StringVar()
        search = ttk.Entry(controls, textvariable=self.preview_search_var, width=35)
        search.grid(row=0, column=3, padx=(0, 8))
        search.bind("<KeyRelease>", lambda _event: self._filter_preview())
        ttk.Label(controls, text="Просмотр выполняется без запуска Excel", style="Muted.TLabel").grid(
            row=0, column=4, sticky="w", padx=(12, 0)
        )
        self.preview_file_var = tk.StringVar(value="Файл не выбран")
        ttk.Label(controls, textvariable=self.preview_file_var, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )
        self.preview_container = ttk.Frame(self.sources_tab)
        self.preview_container.grid(row=3, column=0, sticky="nsew")
        self.preview_container.columnconfigure(0, weight=1)
        self.preview_container.rowconfigure(0, weight=1)
        self.preview_tree: ttk.Treeview | None = None

    def _build_breakdown_tab(self) -> None:
        self.breakdown_tab.columnconfigure(0, weight=1)
        self.breakdown_tab.rowconfigure(2, weight=1)
        ttk.Label(self.breakdown_tab, text="Нераспределенные доходы / расходы", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Label(
            self.breakdown_tab,
            text="Здесь находятся начисления без артикула. Положительные суммы — доходы, отрицательные — расходы.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.breakdown_tree = self._create_tree(
            self.breakdown_tab,
            ["type", "count", "amount", "share"],
            ["Тип начисления", "Количество строк", "Сумма, руб.", "Доля в нераспределенных"],
            row=2,
            widths=[520, 150, 180, 190],
        )

    def _build_guide_tab(self) -> None:
        self.guide_tab.columnconfigure(0, weight=1)
        self.guide_tab.rowconfigure(2, weight=1)
        ttk.Label(self.guide_tab, text="Справочник начислений", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Label(
            self.guide_tab,
            text="Фактическое наличие артикула проверяется для каждой строки. Справочник ничего не принуждает распределять.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.guide_tree = self._create_tree(
            self.guide_tab,
            ["type", "category", "current_status", "current_with", "current_without", "history_status", "history_with", "history_without"],
            ["Тип начисления", "Куда относится", "Текущий запуск", "С артикулом", "Без артикула", "История", "История с артикулом", "История без артикула"],
            row=2,
            widths=[320, 460, 260, 115, 115, 260, 150, 150],
        )

    def _build_scenario_tab(self) -> None:
        self.scenario_tab.columnconfigure(0, weight=1)
        self.scenario_tab.rowconfigure(3, weight=1)
        ttk.Label(self.scenario_tab, text="Доходность при плановой цене", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Label(
            self.scenario_tab,
            text="Объем продаж остается текущим. Комиссия, баллы и прочие затраты пересчитываются по средним показателям выбранного периода.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        scenario_top = ttk.Frame(self.scenario_tab)
        scenario_top.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        scenario_top.columnconfigure(5, weight=1)
        ttk.Label(scenario_top, text="Плановая цена выбранного товара:").grid(row=0, column=0, padx=(0, 6))
        self.planned_price_var = tk.StringVar()
        ttk.Entry(scenario_top, textvariable=self.planned_price_var, width=16).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(scenario_top, text="Применить", command=self.apply_planned_price).grid(row=0, column=2, padx=(0, 18))
        ttk.Label(scenario_top, text="Изменить все цены на, %:").grid(row=0, column=3, padx=(0, 6))
        self.batch_percent_var = tk.StringVar(value="5")
        ttk.Entry(scenario_top, textvariable=self.batch_percent_var, width=10).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(scenario_top, text="Применить ко всем", command=self.apply_batch_percent).grid(row=0, column=5, sticky="w")
        ttk.Button(scenario_top, text="Сбросить цены", command=self.reset_scenario).grid(row=0, column=6, padx=(12, 0))

        self.scenario_tree = self._create_tree(
            self.scenario_tab,
            ["article", "name", "cost", "units", "current_price", "planned_price", "change", "profitability", "other_costs", "planned_revenue", "commission_rate", "commission", "points", "taxable", "tax", "profit", "profit_unit", "net_unit"],
            ["Артикул", "Наименование", "Себестоимость", "Продажи", "Текущая цена", "Плановая цена", "Изменение", "Доходность", "Затраты Ozon без комиссии", "Плановая выручка", "Средняя комиссия", "Плановая комиссия", "Плановые баллы", "Налоговая база", "Налог", "Прибыль от продаж", "Прибыль/ед. до с/с", "Чистая прибыль/ед."],
            row=3,
            widths=[120, 230] + [135] * 16,
        )
        self.scenario_tree.bind("<<TreeviewSelect>>", self._on_scenario_selected)

        self.scenario_kpi_frame = ttk.Frame(self.scenario_tab)
        self.scenario_kpi_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        for column in range(4):
            self.scenario_kpi_frame.columnconfigure(column, weight=1)
        self.scenario_kpi_vars: dict[str, tk.StringVar] = {}
        for index, (key, title) in enumerate(
            [("current_revenue", "Текущая выручка"), ("planned_revenue", "Плановая выручка"), ("planned_net", "Плановая чистая прибыль"), ("planned_margin", "Плановая доходность")]
        ):
            self.scenario_kpi_vars[key] = tk.StringVar(value="—")
            card = ttk.Frame(self.scenario_kpi_frame, style="Card.TFrame", padding=(16, 12))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0 if index == 3 else 5))
            ttk.Label(card, text=title, style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, textvariable=self.scenario_kpi_vars[key], style="Kpi.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_history_tab(self) -> None:
        self.history_tab.columnconfigure(0, weight=1)
        self.history_tab.rowconfigure(1, weight=3)
        self.history_tab.rowconfigure(3, weight=2)
        ttk.Label(self.history_tab, text="История расчетов", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 8)
        )
        self.history_tree = self._create_tree(
            self.history_tab,
            ["id", "period", "created", "files", "units", "revenue", "net", "unallocated", "status"],
            ["№", "Период", "Дата расчета", "Файлов", "Продажи", "Выручка", "Чистая прибыль", "Нераспределенные", "Статус"],
            row=1,
            height=10,
            widths=[60, 210, 160, 80, 110, 150, 150, 160, 100],
        )
        self.history_tree.bind("<Double-1>", self._open_history_run)
        ttk.Label(self.history_tab, text="Контроль качества выбранного расчета", style="Section.TLabel").grid(
            row=2, column=0, sticky="w", pady=(14, 8)
        )
        self.quality_tree = self._create_tree(
            self.history_tab,
            ["severity", "type", "message"],
            ["Уровень", "Проверка", "Сообщение"],
            row=3,
            widths=[140, 220, 900],
        )

    def _build_comparison_tab(self) -> None:
        self.comparison_tab.columnconfigure(0, weight=1)
        self.comparison_tab.rowconfigure(4, weight=1)
        ttk.Label(self.comparison_tab, text="Сравнение сохраненных периодов", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Label(
            self.comparison_tab,
            text="Первый период — база сравнения. Изменение показывает второй период относительно первого.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        controls = ttk.Frame(self.comparison_tab)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(controls, text="Первый период:").grid(row=0, column=0, padx=(0, 6))
        self.compare_first_var = tk.StringVar()
        self.compare_first_combo = ttk.Combobox(
            controls, textvariable=self.compare_first_var, state="readonly", width=34
        )
        self.compare_first_combo.grid(row=0, column=1, padx=(0, 18))
        ttk.Label(controls, text="Второй период:").grid(row=0, column=2, padx=(0, 6))
        self.compare_second_var = tk.StringVar()
        self.compare_second_combo = ttk.Combobox(
            controls, textvariable=self.compare_second_var, state="readonly", width=34
        )
        self.compare_second_combo.grid(row=0, column=3, padx=(0, 12))
        ttk.Button(controls, text="Сравнить", style="Accent.TButton", command=self.refresh_comparison).grid(
            row=0, column=4
        )

        self.comparison_kpi_frame = ttk.Frame(self.comparison_tab)
        self.comparison_kpi_frame.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        for column in range(4):
            self.comparison_kpi_frame.columnconfigure(column, weight=1)
        self.comparison_kpi_vars: dict[str, tk.StringVar] = {}
        for index, (key, title) in enumerate(
            [
                ("revenue", "Изменение выручки"),
                ("net_profit", "Изменение чистой прибыли"),
                ("units", "Изменение продаж"),
                ("unallocated", "Изменение нераспределенных"),
            ]
        ):
            self.comparison_kpi_vars[key] = tk.StringVar(value="—")
            card = ttk.Frame(self.comparison_kpi_frame, style="Card.TFrame", padding=(16, 12))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0 if index == 3 else 5))
            ttk.Label(card, text=title, style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, textvariable=self.comparison_kpi_vars[key], style="Kpi.TLabel").grid(
                row=1, column=0, sticky="w", pady=(4, 0)
            )

        self.comparison_tree = self._create_tree(
            self.comparison_tab,
            [
                "article", "name", "units_first", "units_second", "units_change",
                "revenue_first", "revenue_second", "revenue_change", "revenue_percent",
                "profit_first", "profit_second", "profit_change", "profit_percent",
                "margin_first", "margin_second", "margin_change",
            ],
            [
                "Артикул", "Наименование", "Продажи 1", "Продажи 2", "Изменение продаж",
                "Выручка 1", "Выручка 2", "Изменение выручки", "Выручка, %",
                "Чистая прибыль 1", "Чистая прибыль 2", "Изменение прибыли", "Прибыль, %",
                "Доходность 1", "Доходность 2", "Изменение доходности",
            ],
            row=4,
            widths=[120, 230] + [135] * 14,
        )

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(0, weight=1)
        self.settings_tab.rowconfigure(3, weight=1)
        ttk.Label(self.settings_tab, text="Настройки приложения", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 8)
        )
        settings = ttk.Frame(self.settings_tab)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Тема:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.theme_var = tk.StringVar(value=THEME_VALUES.get(self.db.get_setting("theme", "system"), "Системная"))
        theme_combo = ttk.Combobox(settings, textvariable=self.theme_var, state="readonly", values=list(THEME_LABELS), width=20)
        theme_combo.grid(row=0, column=1, sticky="w", pady=5)
        theme_combo.bind("<<ComboboxSelected>>", self._preview_theme)

        ttk.Label(settings, text="Налоговая ставка, %:").grid(row=0, column=2, sticky="w", padx=(24, 8), pady=5)
        self.tax_rate_var = tk.StringVar(value=_plain_number(float(self.db.get_setting("tax_rate", "0.04")) * 100))
        ttk.Entry(settings, textvariable=self.tax_rate_var, width=14).grid(row=0, column=3, sticky="w", pady=5)

        ttk.Label(settings, text="Повторная загрузка файла:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.duplicate_policy_var = tk.StringVar(
            value=DUPLICATE_VALUES.get(self.db.get_setting("duplicate_policy", "ask"), "Спрашивать")
        )
        ttk.Combobox(
            settings,
            textvariable=self.duplicate_policy_var,
            state="readonly",
            values=list(DUPLICATE_LABELS),
            width=20,
        ).grid(row=1, column=1, sticky="w", pady=5)

        self.warn_realization_var = tk.BooleanVar(value=self.db.get_setting("warn_without_realization", "1") == "1")
        ttk.Checkbutton(
            settings,
            variable=self.warn_realization_var,
            text="Предупреждать, если не выбран отчет о выкупленных товарах",
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=(24, 0), pady=5)

        ttk.Label(settings, text="Строк в предпросмотре:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
        self.preview_rows_var = tk.StringVar(value=self.db.get_setting("preview_rows", "500"))
        ttk.Spinbox(settings, textvariable=self.preview_rows_var, from_=100, to=5000, increment=100, width=12).grid(
            row=2, column=1, sticky="w", pady=5
        )
        ttk.Label(settings, text="Хранилище:").grid(row=2, column=2, sticky="w", padx=(24, 8), pady=5)
        ttk.Label(settings, text=str(self.service.paths["root"]), style="Muted.TLabel").grid(
            row=2, column=3, sticky="w", pady=5
        )
        ttk.Button(settings, text="Сохранить настройки", style="Accent.TButton", command=self.save_settings).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 0)
        )

        product_header = ttk.Frame(self.settings_tab)
        product_header.grid(row=2, column=0, sticky="ew", pady=(6, 8))
        product_header.columnconfigure(0, weight=1)
        ttk.Label(product_header, text="Товары и себестоимость", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(product_header, text="Добавить товар", command=self.add_product).grid(row=0, column=1, padx=4)
        ttk.Button(product_header, text="Изменить", command=self.edit_product).grid(row=0, column=2, padx=4)
        ttk.Button(product_header, text="В архив / восстановить", command=self.toggle_product).grid(row=0, column=3, padx=4)
        self.products_tree = self._create_tree(
            self.settings_tab,
            ["article", "name", "total", "material", "labor", "status"],
            ["Артикул", "Наименование", "Полная себестоимость", "Материал", "Трудозатраты", "Статус"],
            row=3,
            widths=[150, 360, 180, 150, 150, 110],
        )
        self.products_tree.bind("<Double-1>", lambda _event: self.edit_product())

    def _create_tree(
        self,
        parent,
        columns: list[str],
        headings: list[str],
        row: int,
        widths: list[int] | None = None,
        height: int = 18,
    ) -> ttk.Treeview:
        container = ttk.Frame(parent)
        container.grid(row=row, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        tree = ttk.Treeview(container, columns=columns, show="headings", height=height)
        xscroll = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        yscroll = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        widths = widths or [140] * len(columns)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, minwidth=70, stretch=False, anchor="w" if column in {"article", "name", "type", "category", "message"} else "e")
        return tree

    def refresh_all(self) -> None:
        self.refresh_products()
        self.refresh_runs()

    def refresh_runs(self) -> None:
        runs = self.db.list_runs()
        self.run_display_to_id.clear()
        values: list[str] = []
        for run in runs:
            period = _period_text(run.period_start, run.period_end)
            display = f"#{run.id} · {period} · {run.created_at[:16]}"
            values.append(display)
            self.run_display_to_id[display] = run.id
        self.run_combo["values"] = values
        self.compare_first_combo["values"] = values
        self.compare_second_combo["values"] = values
        if not runs:
            self.run_var.set("Нет расчетов")
            self._clear_current_view()
        else:
            target_id = self.current_run_id if self.current_run_id in {run.id for run in runs} else runs[0].id
            display = next(key for key, value in self.run_display_to_id.items() if value == target_id)
            self.run_var.set(display)
            self.select_run(target_id)
            if len(values) >= 2:
                if self.compare_first_var.get() not in values:
                    self.compare_first_var.set(values[1])
                if self.compare_second_var.get() not in values:
                    self.compare_second_var.set(values[0])
                self.refresh_comparison()
            else:
                self.compare_first_var.set(values[0])
                self.compare_second_var.set(values[0])
                self._clear_comparison("Для сравнения загрузите как минимум два периода")
        self.refresh_history()

    def select_run(self, run_id: int) -> None:
        self.current_run_id = run_id
        self.current_calculation = self.db.load_calculation(run_id)
        self._populate_overview()
        self._populate_sources()
        self._populate_breakdown()
        self._populate_guide()
        self._populate_scenario()
        self._populate_quality()
        self.status_var.set(f"Открыт расчет #{run_id}: {_calculation_period(self.current_calculation)}")

    def _on_run_selected(self, _event=None) -> None:
        run_id = self.run_display_to_id.get(self.run_var.get())
        if run_id is not None:
            self.select_run(run_id)

    def _clear_current_view(self) -> None:
        self.current_run_id = None
        self.current_calculation = None
        for tree in (self.overview_tree, self.source_tree, self.breakdown_tree, self.guide_tree, self.scenario_tree, self.quality_tree):
            tree.delete(*tree.get_children())
        for variable in self.kpi_vars.values():
            variable.set("—")
        for variable in self.scenario_kpi_vars.values():
            variable.set("—")

    def _populate_overview(self) -> None:
        calculation = self.current_calculation
        if calculation is None:
            return
        totals = calculation.totals()
        cost = totals["cost_sold"]
        self.kpi_vars["revenue"].set(_money(totals["revenue"]))
        self.kpi_vars["net_profit"].set(_money(totals["net_profit"]))
        self.kpi_vars["profitability"].set(_percent(totals["net_profit"] / cost if cost else 0))
        self.kpi_vars["units"].set(_number(totals["units"]))
        self.kpi_vars["unallocated"].set(_money(totals["unallocated"]))
        self.kpi_vars["files"].set(str(len(self.db.list_source_files(calculation.run_id or 0))))
        self.overview_tree.delete(*self.overview_tree.get_children())
        for result in calculation.products:
            values = _result_values(result, calculation.tax_rate)
            tag = "negative" if result.net_profit(calculation.tax_rate) < 0 else "positive"
            self.overview_tree.insert("", "end", iid=result.article, values=values, tags=(tag,))
        self._configure_value_tags(self.overview_tree)

    def _populate_sources(self) -> None:
        if self.current_run_id is None:
            return
        sources = self.db.list_source_files(self.current_run_id)
        self.source_tree.delete(*self.source_tree.get_children())
        self.source_by_iid.clear()
        for row in sources:
            iid = str(row["id"])
            self.source_by_iid[iid] = row
            report_type = "Начисления" if row["report_type"] == "ACCRUAL" else "Выкупленные товары"
            period = _period_text(row.get("period_start"), row.get("period_end"))
            self.source_tree.insert(
                "",
                "end",
                iid=iid,
                values=(row["original_name"], report_type, row["row_count"], _money(float(row["total_amount"])), period, str(row["file_hash"])[:24]),
            )
        if sources:
            first = str(sources[0]["id"])
            self.source_tree.selection_set(first)
            self.source_tree.focus(first)
            self._on_source_selected()

    def _on_source_selected(self, _event=None) -> None:
        selection = self.source_tree.selection()
        if not selection:
            return
        source = self.source_by_iid.get(selection[0])
        if source is None:
            return
        try:
            self.preview_path = str(source["stored_path"])
            self.preview_file_var.set(f"Файл: {source['original_name']}")
            sheets = workbook_sheet_names(self.preview_path)
            self.sheet_combo["values"] = sheets
            preferred = str(source["sheet_name"])
            self.sheet_var.set(preferred if preferred in sheets else sheets[0])
            self._load_preview()
        except Exception as exc:
            messagebox.showerror("Просмотр файла", str(exc), parent=self)

    def _load_preview(self) -> None:
        if not self.preview_path or not self.sheet_var.get():
            return
        max_rows = int(self.db.get_setting("preview_rows", "500"))
        try:
            self.preview_headers, self.preview_rows = preview_sheet(
                self.preview_path, self.sheet_var.get(), max_rows=max_rows
            )
            self._filter_preview()
        except Exception as exc:
            messagebox.showerror("Просмотр файла", str(exc), parent=self)

    def browse_xlsx_preview(self) -> None:
        path = filedialog.askopenfilename(
            title="Просмотреть книгу без Excel",
            filetypes=[("Книги Excel", "*.xlsx")],
            parent=self,
        )
        if not path:
            return
        try:
            sheets = workbook_sheet_names(path)
            if not sheets:
                raise ValueError("В книге нет листов")
            self.preview_path = path
            self.preview_file_var.set(f"Файл: {Path(path).name} · только просмотр")
            self.sheet_combo["values"] = sheets
            self.sheet_var.set(sheets[0])
            self.source_tree.selection_remove(*self.source_tree.selection())
            self._load_preview()
        except Exception as exc:
            messagebox.showerror("Просмотр файла", str(exc), parent=self)

    def _filter_preview(self) -> None:
        query = self.preview_search_var.get().casefold().strip()
        rows = self.preview_rows
        if query:
            rows = [row for row in rows if query in " | ".join(row).casefold()]
        self._render_preview_tree(self.preview_headers, rows)

    def _render_preview_tree(self, headers: list[str], rows: list[list[str]]) -> None:
        if self.preview_tree is not None:
            self.preview_tree.master.destroy()
        if not headers:
            return
        columns = [f"c{index}" for index in range(len(headers))]
        frame = ttk.Frame(self.preview_container)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        for column, heading in zip(columns, headers):
            tree.heading(column, text=heading)
            tree.column(column, width=75 if heading == "Строка" else 150, minwidth=55, stretch=False, anchor="w")
        for row in rows:
            tree.insert("", "end", values=row)
        self.preview_tree = tree

    def _populate_breakdown(self) -> None:
        calculation = self.current_calculation
        if calculation is None:
            return
        self.breakdown_tree.delete(*self.breakdown_tree.get_children())
        total = calculation.unallocated_total
        for accrual_type, (count, amount) in calculation.unallocated.items():
            share = amount / total if total else 0.0
            tag = "negative" if amount < 0 else "positive"
            self.breakdown_tree.insert("", "end", values=(accrual_type, count, _money(amount), _percent(share)), tags=(tag,))
        self.breakdown_tree.insert("", "end", values=("Итого", sum(x[0] for x in calculation.unallocated.values()), _money(total), _percent(1 if total else 0)), tags=("total",))
        self._configure_value_tags(self.breakdown_tree)

    def _populate_guide(self) -> None:
        if self.current_run_id is None:
            return
        self.guide_tree.delete(*self.guide_tree.get_children())
        for item in self.db.accrual_guide(self.current_run_id):
            self.guide_tree.insert(
                "",
                "end",
                values=(
                    item["accrual_type"], item["category"], item["current_status"], item["current_with"],
                    item["current_without"], item["history_status"], item["history_with"], item["history_without"],
                ),
            )

    def _populate_scenario(self) -> None:
        calculation = self.current_calculation
        if calculation is None or calculation.run_id is None:
            return
        prices = self.db.planned_prices(calculation.run_id)
        self.scenario_tree.delete(*self.scenario_tree.get_children())
        self.scenario_rows.clear()
        planned_revenue_total = 0.0
        planned_net_total = 0.0
        planned_cost_total = 0.0
        for result in calculation.products:
            scenario = calculate_scenario(result, calculation.tax_rate, prices.get(result.article))
            self.scenario_rows[result.article] = scenario
            tag = "negative" if (scenario.net_profit_per_unit or 0) < 0 else "positive"
            self.scenario_tree.insert("", "end", iid=result.article, values=_scenario_values(scenario), tags=(tag,))
            if scenario.planned_revenue is not None:
                planned_revenue_total += scenario.planned_revenue
            if scenario.net_profit_per_unit is not None:
                planned_net_total += scenario.net_profit_per_unit * scenario.units
                planned_cost_total += scenario.unit_cost * scenario.units
        totals = calculation.totals()
        self.scenario_kpi_vars["current_revenue"].set(_money(totals["revenue"]))
        self.scenario_kpi_vars["planned_revenue"].set(_money(planned_revenue_total))
        self.scenario_kpi_vars["planned_net"].set(_money(planned_net_total))
        self.scenario_kpi_vars["planned_margin"].set(_percent(planned_net_total / planned_cost_total if planned_cost_total else 0))
        self._configure_value_tags(self.scenario_tree)

    def _on_scenario_selected(self, _event=None) -> None:
        selection = self.scenario_tree.selection()
        if not selection:
            return
        row = self.scenario_rows.get(selection[0])
        self.planned_price_var.set(_plain_number(row.planned_price) if row and row.planned_price is not None else "")

    def apply_planned_price(self) -> None:
        if self.current_run_id is None:
            return
        selection = self.scenario_tree.selection()
        if not selection:
            messagebox.showinfo("Плановая цена", "Сначала выберите товар в таблице", parent=self)
            return
        try:
            value = _parse_number(self.planned_price_var.get())
            if value < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Плановая цена", "Введите неотрицательную цену", parent=self)
            return
        self.db.save_planned_price(self.current_run_id, selection[0], value)
        self._populate_scenario()
        self.scenario_tree.selection_set(selection[0])

    def apply_batch_percent(self) -> None:
        if self.current_run_id is None or self.current_calculation is None:
            return
        try:
            percent = _parse_number(self.batch_percent_var.get()) / 100
            if percent <= -1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Изменение цен", "Введите процент больше -100", parent=self)
            return
        for result in self.current_calculation.products:
            current = result.average_price()
            if current is not None:
                self.db.save_planned_price(self.current_run_id, result.article, current * (1 + percent))
        self._populate_scenario()

    def reset_scenario(self) -> None:
        if self.current_run_id is None:
            return
        if messagebox.askyesno("Сбросить сценарий", "Вернуть плановые цены к текущим средним?", parent=self):
            self.db.clear_planned_prices(self.current_run_id)
            self._populate_scenario()

    def refresh_history(self) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        for run in self.db.list_runs():
            self.history_tree.insert(
                "",
                "end",
                iid=str(run.id),
                values=(
                    run.id, _period_text(run.period_start, run.period_end), run.created_at[:16], run.source_count,
                    _number(run.units), _money(run.revenue), _money(run.net_profit), _money(run.unallocated_total), run.status,
                ),
            )
        if self.current_run_id and str(self.current_run_id) in self.history_tree.get_children():
            self.history_tree.selection_set(str(self.current_run_id))

    def _open_history_run(self, _event=None) -> None:
        selection = self.history_tree.selection()
        if not selection:
            return
        run_id = int(selection[0])
        display = next((key for key, value in self.run_display_to_id.items() if value == run_id), None)
        if display:
            self.run_var.set(display)
        self.select_run(run_id)
        self.notebook.select(self.overview_tab)

    def refresh_comparison(self) -> None:
        first_id = self.run_display_to_id.get(self.compare_first_var.get())
        second_id = self.run_display_to_id.get(self.compare_second_var.get())
        if first_id is None or second_id is None:
            self._clear_comparison("Выберите два сохраненных периода")
            return
        if first_id == second_id:
            self._clear_comparison("Выберите разные периоды")
            return
        comparison = compare_calculations(
            self.db.load_calculation(first_id),
            self.db.load_calculation(second_id),
        )
        self.comparison_kpi_vars["revenue"].set(_comparison_kpi(comparison.revenue, money=True))
        self.comparison_kpi_vars["net_profit"].set(_comparison_kpi(comparison.net_profit, money=True))
        self.comparison_kpi_vars["units"].set(_comparison_kpi(comparison.units, money=False))
        self.comparison_kpi_vars["unallocated"].set(_comparison_kpi(comparison.unallocated, money=True))
        self.comparison_tree.delete(*self.comparison_tree.get_children())
        for row in comparison.products:
            tag = "positive" if row.net_profit.change >= 0 else "negative"
            self.comparison_tree.insert(
                "",
                "end",
                iid=row.article,
                values=(
                    row.article,
                    row.name,
                    _number(row.units.first),
                    _number(row.units.second),
                    _signed_number(row.units.change),
                    _money(row.revenue.first),
                    _money(row.revenue.second),
                    _signed_money(row.revenue.change),
                    _comparison_percent(row.revenue),
                    _money(row.net_profit.first),
                    _money(row.net_profit.second),
                    _signed_money(row.net_profit.change),
                    _comparison_percent(row.net_profit),
                    _percent(row.profitability.first),
                    _percent(row.profitability.second),
                    _signed_percentage_points(row.profitability.change),
                ),
                tags=(tag,),
            )
        self._configure_value_tags(self.comparison_tree)
        self.status_var.set(f"Сравнение расчетов #{first_id} и #{second_id}")

    def _clear_comparison(self, message: str) -> None:
        if not hasattr(self, "comparison_tree"):
            return
        self.comparison_tree.delete(*self.comparison_tree.get_children())
        for variable in self.comparison_kpi_vars.values():
            variable.set("—")
        self.comparison_tree.insert("", "end", values=("", message))

    def _populate_quality(self) -> None:
        self.quality_tree.delete(*self.quality_tree.get_children())
        if self.current_run_id is None:
            return
        events = self.db.list_quality_events(self.current_run_id)
        if not events:
            self.quality_tree.insert("", "end", values=("Готово", "Проверки", "Ошибок и предупреждений нет"), tags=("positive",))
        else:
            for event in events:
                tag = "negative" if event["severity"] == "Ошибка" else "warning"
                self.quality_tree.insert("", "end", values=(event["severity"], event["event_type"], event["message"]), tags=(tag,))
        self._configure_value_tags(self.quality_tree)

    def refresh_products(self) -> None:
        if not hasattr(self, "products_tree"):
            return
        self.products_tree.delete(*self.products_tree.get_children())
        for product in self.db.list_products():
            self.products_tree.insert(
                "",
                "end",
                iid=product.article,
                values=(
                    product.article, product.name, _money(product.total_cost), _money(product.material_cost),
                    _money(product.labor_cost), "Активен" if product.active else "Архив",
                ),
                tags=("" if product.active else "muted",),
            )
        self._configure_value_tags(self.products_tree)

    def add_product(self) -> None:
        dialog = ProductDialog(self, title="Новый товар")
        self.wait_window(dialog)
        if dialog.result:
            try:
                self.db.save_product(dialog.result)
                self.refresh_products()
            except Exception as exc:
                messagebox.showerror("Товар", str(exc), parent=self)

    def edit_product(self) -> None:
        selection = self.products_tree.selection()
        if not selection:
            messagebox.showinfo("Товары", "Выберите товар", parent=self)
            return
        product = self.db.product_map(active_only=False)[selection[0]]
        dialog = ProductDialog(self, title="Изменить товар", product=product)
        self.wait_window(dialog)
        if dialog.result:
            try:
                self.db.save_product(dialog.result)
                self.refresh_products()
            except Exception as exc:
                messagebox.showerror("Товар", str(exc), parent=self)

    def toggle_product(self) -> None:
        selection = self.products_tree.selection()
        if not selection:
            return
        product = self.db.product_map(active_only=False)[selection[0]]
        product.active = not product.active
        self.db.save_product(product)
        self.refresh_products()

    def save_settings(self) -> None:
        try:
            tax_percent = _parse_number(self.tax_rate_var.get())
            if tax_percent < 0 or tax_percent > 100:
                raise ValueError
            preview_rows = int(self.preview_rows_var.get())
            if preview_rows < 100 or preview_rows > 5000:
                raise ValueError
        except ValueError:
            messagebox.showerror("Настройки", "Проверьте налоговую ставку и количество строк предпросмотра", parent=self)
            return
        self.db.set_setting("theme", THEME_LABELS[self.theme_var.get()])
        self.db.set_setting("tax_rate", str(tax_percent / 100))
        self.db.set_setting("duplicate_policy", DUPLICATE_LABELS[self.duplicate_policy_var.get()])
        self.db.set_setting("warn_without_realization", "1" if self.warn_realization_var.get() else "0")
        self.db.set_setting("preview_rows", str(preview_rows))
        self.colors = apply_theme(self, THEME_LABELS[self.theme_var.get()])
        messagebox.showinfo("Настройки", "Настройки сохранены", parent=self)

    def _preview_theme(self, _event=None) -> None:
        self.colors = apply_theme(self, THEME_LABELS[self.theme_var.get()])
        for tree in (
            self.overview_tree,
            self.breakdown_tree,
            self.scenario_tree,
            self.history_tree,
            self.quality_tree,
            self.comparison_tree,
            self.products_tree,
        ):
            self._configure_value_tags(tree)

    def import_reports(self) -> None:
        if self.import_in_progress:
            messagebox.showinfo("Импорт отчетов", "Проверка файлов уже выполняется", parent=self)
            return
        paths = filedialog.askopenfilenames(
            title="Выберите отчеты Ozon",
            filetypes=[("Отчеты Excel", "*.xlsx")],
            parent=self,
        )
        if not paths:
            return
        self.configure(cursor="watch")
        self.status_var.set("Проверка исходных файлов…")
        self.update_idletasks()
        self.import_in_progress = True
        threading.Thread(target=self._prepare_import_worker, args=(list(paths),), daemon=True).start()
        self.after(100, self._poll_import_queue)

    def _prepare_import_worker(self, paths: list[str]) -> None:
        try:
            session = self.service.prepare_import(list(paths))
            self.import_queue.put((session, None))
        except Exception as exc:
            self.import_queue.put((None, exc))

    def _poll_import_queue(self) -> None:
        try:
            session, error = self.import_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_import_queue)
            return
        self._complete_import_ui(session, error)

    def _complete_import_ui(self, session: ImportSession | None, error: Exception | None) -> None:
        try:
            if error is not None:
                raise error
            if session is None:
                raise RuntimeError("Не удалось подготовить импорт")
            if not self._handle_duplicates(session):
                return
            if not session.sources or not session.has_accrual:
                raise ValueError("После исключения дубликатов не осталось отчета по начислениям")
            if not session.has_realization and self.db.get_setting("warn_without_realization", "1") == "1":
                if not messagebox.askyesno(
                    "Нет отчета о выкупленных товарах",
                    "Продолжить без RealizationReportCIS? Если такие продажи были, выручка будет неполной.",
                    parent=self,
                ):
                    return
            session.unknown_products = discover_unknown_products(session.sources, self.db.product_map(active_only=False))
            created: list[Product] = []
            skipped: set[str] = set()
            if session.unknown_products:
                dialog = UnknownProductsDialog(self, session.unknown_products)
                self.wait_window(dialog)
                if dialog.cancelled:
                    return
                created = dialog.created_products
                skipped = dialog.skipped_articles
            calculation = self.service.complete_import(session, created_products=created, skipped_articles=skipped)
            self.current_run_id = calculation.run_id
            self.refresh_all()
            messagebox.showinfo(
                "Расчет готов",
                f"Создан расчет #{calculation.run_id}.\n"
                f"Период: {_calculation_period(calculation)}\n"
                f"Выручка по выкупленным товарам: {_money(calculation.realization_revenue)}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Импорт отчетов", str(exc), parent=self)
        finally:
            self.import_in_progress = False
            self.configure(cursor="")
            self.status_var.set("Готово" if self.current_run_id is None else f"Открыт расчет #{self.current_run_id}")

    def _handle_duplicates(self, session: ImportSession) -> bool:
        if not session.duplicate_sources:
            return True
        policy = self.db.get_setting("duplicate_policy", "ask")
        names = "\n".join(_duplicate_description(source) for source in session.duplicate_sources)
        if policy == "allow":
            return True
        if policy == "skip":
            _exclude_duplicate_sources(session)
            return True
        answer = messagebox.askyesnocancel(
            "Повторная загрузка файлов",
            "Найдены файлы с уже выбранным или ранее обработанным содержимым:\n\n"
            f"{names}\n\nДа — включить повторно; Нет — пропустить; Отмена — прервать импорт.",
            parent=self,
        )
        if answer is None:
            return False
        if answer is False:
            _exclude_duplicate_sources(session)
        return True

    def export_current_run(self) -> None:
        if self.current_run_id is None or self.current_calculation is None:
            messagebox.showinfo("Экспорт", "Сначала импортируйте или выберите расчет", parent=self)
            return
        destination = filedialog.asksaveasfilename(
            title="Сохранить итоговый отчет",
            defaultextension=".xlsx",
            initialdir=str(self.service.paths["exports"]),
            initialfile=suggested_export_name(self.current_calculation),
            filetypes=[("Книга Excel", "*.xlsx")],
            parent=self,
        )
        if not destination:
            return
        try:
            path = export_run(self.db, self.current_run_id, destination)
            messagebox.showinfo("Экспорт", f"Отчет сохранен:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Экспорт", str(exc), parent=self)

    def _configure_value_tags(self, tree: ttk.Treeview) -> None:
        palette = self.colors
        tree.tag_configure("negative", foreground=palette["negative"])
        tree.tag_configure("positive", foreground=palette["positive"])
        tree.tag_configure("warning", foreground=palette["warning"])
        tree.tag_configure("total", background=palette["surface_alt"], foreground=palette["text"])
        tree.tag_configure("muted", foreground=palette["muted"])


class ProductDialog(tk.Toplevel):
    def __init__(self, parent: OZPriceAnalyzerApp, title: str, product: Product | None = None):
        super().__init__(parent)
        self.result: Product | None = None
        self.product = product
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.configure(background=parent.colors["window"])
        self.columnconfigure(1, weight=1)
        self.article_var = tk.StringVar(value=product.article if product else "")
        self.name_var = tk.StringVar(value=product.name if product else "")
        self.total_var = tk.StringVar(value=_plain_number(product.total_cost) if product else "")
        self.labor_var = tk.StringVar(value=_plain_number(product.labor_cost) if product else "0")

        fields = [
            ("Артикул", self.article_var),
            ("Наименование", self.name_var),
            ("Полная себестоимость, руб.", self.total_var),
            ("Трудозатраты в составе с/с, руб.", self.labor_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(22, 12))
            entry = ttk.Entry(self, textvariable=variable, width=42)
            entry.grid(row=row, column=1, sticky="ew", pady=6, padx=(0, 22))
            if product and row == 0:
                entry.configure(state="disabled")
        buttons = ttk.Frame(self)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", padx=18, pady=(14, 18))
        ttk.Button(buttons, text="Отмена", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Сохранить", style="Accent.TButton", command=self._save).grid(row=0, column=1, padx=4)
        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

    def _save(self) -> None:
        try:
            article = self.article_var.get().strip()
            name = self.name_var.get().strip() or article
            total = _parse_number(self.total_var.get())
            labor = _parse_number(self.labor_var.get())
            if not article or total < 0 or labor < 0 or labor > total:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Товар",
                "Укажите артикул и корректную себестоимость. Трудозатраты должны быть от 0 до полной себестоимости.",
                parent=self,
            )
            return
        self.result = Product(
            article=article,
            name=name,
            material_cost=total - labor,
            labor_cost=labor,
            active=self.product.active if self.product else True,
        )
        self.destroy()


class UnknownProductsDialog(tk.Toplevel):
    def __init__(self, parent: OZPriceAnalyzerApp, unknown: list[UnknownProduct]):
        super().__init__(parent)
        self.title("Новые товары")
        self.geometry("1040x620")
        self.transient(parent)
        self.grab_set()
        self.cancelled = True
        self.items = {item.article: item for item in unknown}
        self.decisions: dict[str, Product | None] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="В отчетах найдены новые артикулы", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=20, pady=(18, 2)
        )
        ttk.Label(
            self,
            text="Для включения начислений укажите себестоимость. Пропущенный артикул не попадет ни в товар, ни в нераспределенные суммы.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        container = ttk.Frame(self)
        container.grid(row=2, column=0, sticky="nsew", padx=20)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(container, columns=("article", "name", "sku", "sources", "decision"), show="headings")
        headings = ["Артикул", "Наименование", "SKU", "Файлы", "Решение"]
        widths = [150, 260, 120, 310, 130]
        for column, heading, width in zip(self.tree["columns"], headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        for item in unknown:
            self.tree.insert(
                "", "end", iid=item.article,
                values=(item.article, item.name, item.sku, ", ".join(sorted(item.source_names)), "Не выбрано"),
            )
        self.tree.bind("<<TreeviewSelect>>", self._select)

        editor = ttk.Frame(self, padding=(20, 12))
        editor.grid(row=3, column=0, sticky="ew")
        ttk.Label(editor, text="Полная себестоимость, руб.:").grid(row=0, column=0, padx=(0, 6))
        self.total_var = tk.StringVar()
        ttk.Entry(editor, textvariable=self.total_var, width=14).grid(row=0, column=1, padx=(0, 14))
        ttk.Label(editor, text="Трудозатраты, руб.:").grid(row=0, column=2, padx=(0, 6))
        self.labor_var = tk.StringVar(value="0")
        ttk.Entry(editor, textvariable=self.labor_var, width=14).grid(row=0, column=3, padx=(0, 14))
        ttk.Button(editor, text="Создать позицию", command=self._create).grid(row=0, column=4, padx=4)
        ttk.Button(editor, text="Пропустить", command=self._skip).grid(row=0, column=5, padx=4)

        buttons = ttk.Frame(self, padding=(20, 12))
        buttons.grid(row=4, column=0, sticky="e")
        ttk.Button(buttons, text="Отменить импорт", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Продолжить расчет", style="Accent.TButton", command=self._finish).grid(row=0, column=1, padx=4)
        first = next(iter(self.items), None)
        if first:
            self.tree.selection_set(first)
            self.tree.focus(first)

    @property
    def created_products(self) -> list[Product]:
        return [item for item in self.decisions.values() if item is not None]

    @property
    def skipped_articles(self) -> set[str]:
        return {article for article, product in self.decisions.items() if product is None}

    def _selected_article(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _select(self, _event=None) -> None:
        article = self._selected_article()
        decision = self.decisions.get(article) if article else None
        if isinstance(decision, Product):
            self.total_var.set(_plain_number(decision.total_cost))
            self.labor_var.set(_plain_number(decision.labor_cost))
        else:
            self.total_var.set("")
            self.labor_var.set("0")

    def _create(self) -> None:
        article = self._selected_article()
        if not article:
            return
        try:
            total = _parse_number(self.total_var.get())
            labor = _parse_number(self.labor_var.get())
            if total < 0 or labor < 0 or labor > total:
                raise ValueError
        except ValueError:
            messagebox.showerror("Себестоимость", "Проверьте полную себестоимость и трудозатраты", parent=self)
            return
        item = self.items[article]
        self.decisions[article] = Product(article, item.name or article, total - labor, labor)
        self._set_decision_text(article, f"Создать: {_money(total)}")
        self._select_next_unresolved()

    def _skip(self) -> None:
        article = self._selected_article()
        if not article:
            return
        self.decisions[article] = None
        self._set_decision_text(article, "Пропустить")
        self._select_next_unresolved()

    def _set_decision_text(self, article: str, text: str) -> None:
        values = list(self.tree.item(article, "values"))
        values[-1] = text
        self.tree.item(article, values=values)

    def _select_next_unresolved(self) -> None:
        for article in self.items:
            if article not in self.decisions:
                self.tree.selection_set(article)
                self.tree.focus(article)
                self.tree.see(article)
                return

    def _finish(self) -> None:
        unresolved = [article for article in self.items if article not in self.decisions]
        if unresolved:
            messagebox.showwarning(
                "Новые товары",
                f"Выберите действие еще для {len(unresolved)} позиций: создать или пропустить.",
                parent=self,
            )
            return
        self.cancelled = False
        self.destroy()


def _result_values(result: ProductResult, tax_rate: float) -> tuple[object, ...]:
    return (
        result.article,
        result.name,
        _money(result.total_cost),
        _money(result.material_cost),
        _money(result.labor_cost),
        _money(result.material_sold),
        _money(result.labor_sold),
        _money(result.cost_sold),
        _percent(result.profitability(tax_rate)),
        _money(result.net_profit_per_unit(tax_rate)),
        _money(result.profit_per_unit()),
        _money(result.net_profit(tax_rate)),
        _money(result.financial_result),
        _money(result.average_price()) if result.average_price() is not None else "—",
        _money(result.tax(tax_rate)),
        _money(result.taxable_income),
        _number(result.units),
        _money(result.revenue_including_points),
        _money(result.revenue_no_points),
        _money(result.partner_programs),
        _money(result.points),
        _money(result.commission),
        _money(result.processing),
        _money(result.delivery),
        _money(result.logistics),
        _money(result.reverse_logistics),
        _money(result.returns_cancels),
        _money(result.acquiring),
        _money(result.stars),
        _money(result.packaging),
        _money(result.compensation),
        _money(result.other),
        _money(result.financial_result),
    )


def _scenario_values(row: ScenarioRow) -> tuple[object, ...]:
    return (
        row.article,
        row.name,
        _money(row.unit_cost),
        _number(row.units),
        _optional_money(row.current_price),
        _optional_money(row.planned_price),
        _optional_percent(row.price_change),
        _optional_percent(row.profitability),
        _optional_money(row.ozon_costs_without_commission),
        _optional_money(row.planned_revenue),
        _optional_percent(row.commission_rate),
        _optional_money(row.planned_commission),
        _optional_money(row.planned_points),
        _optional_money(row.taxable_base),
        _optional_money(row.tax),
        _optional_money(row.profit),
        _optional_money(row.profit_per_unit_before_cost),
        _optional_money(row.net_profit_per_unit),
    )


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} ₽".replace(",", " ")


def _signed_money(value: float) -> str:
    return ("+" if value > 0 else "") + _money(value)


def _signed_number(value: float) -> str:
    return ("+" if value > 0 else "") + _number(value)


def _number(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


def _percent(value: float) -> str:
    return f"{value * 100:,.2f}%".replace(",", " ")


def _signed_percentage_points(value: float) -> str:
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value * 100:,.2f} п.п.".replace(",", " ")


def _comparison_percent(metric: ComparisonMetric) -> str:
    value = metric.change_percent
    if value is None:
        return "0,00%"
    if value == float("inf"):
        return "новое значение"
    prefix = "+" if value > 0 else ""
    return prefix + _percent(value)


def _comparison_kpi(metric: ComparisonMetric, money: bool) -> str:
    absolute = _signed_money(metric.change) if money else _signed_number(metric.change)
    return f"{absolute} · {_comparison_percent(metric)}"


def _optional_money(value: float | None) -> str:
    return _money(value) if value is not None else "—"


def _optional_percent(value: float | None) -> str:
    return _percent(value) if value is not None else "—"


def _plain_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _parse_number(value: str) -> float:
    return float(value.replace("\u00a0", "").replace(" ", "").replace(",", ".").replace("₽", "").replace("%", "").strip())


def _period_text(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{_date_display(start)}–{_date_display(end)}"
    return "Период не определен"


def _date_display(value: str) -> str:
    parts = value[:10].split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else value


def _calculation_period(calculation: RunCalculation) -> str:
    if calculation.period_start and calculation.period_end:
        return f"{calculation.period_start:%d.%m.%Y}–{calculation.period_end:%d.%m.%Y}"
    return "не определен"


def _duplicate_description(source) -> str:
    if source.duplicate_run_ids:
        runs = ", ".join("#" + str(value) for value in source.duplicate_run_ids)
        return f"• {source.path.name} — уже в расчетах {runs}"
    return f"• {source.path.name} — совпадает с другим выбранным файлом"


def _exclude_duplicate_sources(session: ImportSession) -> None:
    duplicate_ids = {id(source) for source in session.duplicate_sources}
    session.sources = [source for source in session.sources if id(source) not in duplicate_ids]


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run_app() -> None:
    app = OZPriceAnalyzerApp()
    app.mainloop()


if __name__ == "__main__":
    run_app()
