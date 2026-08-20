from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .catalog_category_filters import CatalogAndCategoryOZPriceAnalyzerApp
from .display_modes import (
    _TableModeController,
    _button_with_text,
    resolve_ui_scale,
)
from .resizable_layout import _GridSplitter, _hide_label_with_text


class CostCatalogTabOZPriceAnalyzerApp(CatalogAndCategoryOZPriceAnalyzerApp):
    """v0.5.7: move the cost catalog to its own tab before Settings."""

    def __init__(self, *args, **kwargs) -> None:
        self._catalog_splitter_base_upper = 150
        super().__init__(*args, **kwargs)
        self._install_cost_catalog_tab()
        self.refresh_products()

    def _install_cost_catalog_tab(self) -> None:
        old_tree = self.products_tree
        self._hide_legacy_catalog_from_settings(old_tree)

        self.cost_catalog_tab = ttk.Frame(self.notebook, padding=4)
        settings_index = self.notebook.index(self.settings_tab)
        self.notebook.insert(
            settings_index,
            self.cost_catalog_tab,
            text="Справочник себестоимости",
        )

        self.cost_catalog_tab.columnconfigure(0, weight=1)
        self.cost_catalog_tab.rowconfigure(0, weight=1)
        self.cost_catalog_tab.rowconfigure(2, weight=0)

        top = ttk.Frame(self.cost_catalog_tab)
        top.grid(row=0, column=0, sticky="new", pady=(8, 0))
        top.columnconfigure(0, weight=1)

        header = ttk.Frame(top)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Справочник себестоимости",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Текущие товары, категории и себестоимость для будущих расчетов",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        actions = ttk.Frame(top)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        ttk.Button(
            actions,
            text="Редактировать справочник",
            style="Accent.TButton",
            command=self.open_cost_catalog_editor,
        ).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(
            actions,
            text="Добавить товар",
            command=self.add_product,
        ).grid(row=0, column=1, padx=4)
        ttk.Button(
            actions,
            text="Изменить выбранный",
            command=self.edit_product,
        ).grid(row=0, column=2, padx=4)
        ttk.Button(
            actions,
            text="В архив / восстановить",
            command=self.toggle_product,
        ).grid(row=0, column=3, padx=4)
        ttk.Button(
            actions,
            text="Журнал изменений",
            command=self.show_cost_history,
        ).grid(row=0, column=4, padx=4)
        ttk.Button(
            actions,
            text="Удалить",
            style="Danger.TButton",
            command=self.delete_selected_product,
        ).grid(row=0, column=5, padx=(4, 0))

        self.catalog_help_label = ttk.Label(
            top,
            text=(
                "Справочник влияет только на будущие расчеты. "
                "Сохраненные отчеты хранят исторический снимок себестоимости."
            ),
            style="Muted.TLabel",
        )
        self.catalog_help_label.grid(row=2, column=0, sticky="w", pady=(0, 8))

        filters = ttk.Frame(top)
        filters.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        filters.columnconfigure(5, weight=1)

        ttk.Label(filters, text="Поиск:").grid(row=0, column=0, padx=(0, 6))
        search_entry = ttk.Entry(
            filters,
            textvariable=self.product_search_var,
            width=28,
        )
        search_entry.grid(row=0, column=1, padx=(0, 12))

        ttk.Label(filters, text="Показывать:").grid(row=0, column=2, padx=(0, 6))
        status_combo = ttk.Combobox(
            filters,
            textvariable=self.product_status_var,
            state="readonly",
            values=("Все", "Активные", "Архив"),
            width=12,
        )
        status_combo.grid(row=0, column=3, padx=(0, 12))
        status_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.refresh_products(),
        )

        ttk.Label(
            filters,
            textvariable=self.product_count_var,
            style="Muted.TLabel",
        ).grid(row=0, column=4, sticky="w")

        ttk.Button(
            filters,
            text="Выгрузить XLSX",
            command=self.export_product_catalog,
        ).grid(row=0, column=6, padx=4)
        ttk.Button(
            filters,
            text="Загрузить XLSX",
            command=self.import_product_catalog,
        ).grid(row=0, column=7, padx=4)
        ttk.Button(
            filters,
            text="Очистить справочник",
            command=self.clear_product_catalog,
        ).grid(row=0, column=8, padx=(12, 4))

        self.products_tree = self._create_tree(
            self.cost_catalog_tab,
            ["article", "name", "category", "total", "material", "labor", "status"],
            [
                "Артикул",
                "Наименование",
                "Категория",
                "Полная себестоимость",
                "Материал",
                "Трудозатраты",
                "Статус",
            ],
            row=2,
            widths=[150, 320, 220, 180, 150, 150, 110],
        )
        self.products_tree.bind("<Double-1>", lambda _event: self.edit_product())
        self.products_tree.bind(
            "<Delete>",
            lambda _event: self.delete_selected_product(),
            add="+",
        )

        def compact(upper: int) -> None:
            _hide_label_with_text(
                top,
                "Справочник влияет только на будущие расчеты",
                upper < 185,
            )

        self._catalog_splitter = _GridSplitter(
            self,
            self.cost_catalog_tab,
            row=1,
            table_row=2,
            absorb_row=0,
            min_upper=self._catalog_splitter_base_upper,
            min_table=220,
            compact=compact,
            protected_rows=(0,),
        )

        if hasattr(self, "_table_modes"):
            self._table_modes.pop("settings", None)
            self._table_modes["catalog"] = _TableModeController(
                self,
                "catalog",
                "Справочник себестоимости",
                self.cost_catalog_tab,
                self.products_tree,
                self._catalog_splitter,
                action_label="Изменить выбранный",
                action=self.edit_product,
            )

        factor = resolve_ui_scale(
            self._saved_scale_preference(),
            int(self.winfo_screenheight()),
        )
        self._catalog_splitter.min_upper = max(
            90,
            int(round(self._catalog_splitter_base_upper * factor)),
        )
        self._catalog_splitter._apply()

    def _hide_legacy_catalog_from_settings(self, old_tree: ttk.Treeview) -> None:
        button = _button_with_text(self.settings_tab, "Редактировать справочник")
        if button is not None:
            try:
                button.master.grid_remove()
            except tk.TclError:
                pass

        try:
            old_tree.master.grid_remove()
        except tk.TclError:
            pass

        if hasattr(self, "_settings_splitter"):
            self._settings_splitter.suspended = True
            try:
                self._settings_splitter.bar.grid_remove()
            except tk.TclError:
                pass

        for row in (2, 3, 4):
            self.settings_tab.rowconfigure(row, weight=0, minsize=0)
        self.settings_tab.rowconfigure(1, weight=0, minsize=0)
        self.settings_tab.rowconfigure(5, weight=1, minsize=0)

    def _apply_ui_scale(self, factor: float) -> None:
        super()._apply_ui_scale(factor)
        if not hasattr(self, "_catalog_splitter"):
            return
        factor = min(1.0, max(0.8, float(factor)))
        self._catalog_splitter.min_upper = max(
            90,
            int(round(self._catalog_splitter_base_upper * factor)),
        )
        self._catalog_splitter._apply()


def run_app() -> None:
    app = CostCatalogTabOZPriceAnalyzerApp()
    app.mainloop()
