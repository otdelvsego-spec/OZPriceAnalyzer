from __future__ import annotations

from tkinter import ttk

from .overview_export import OverviewExportOZPriceAnalyzerApp
from .ui import _money


def report_total_value(calculation) -> float:
    """Return business result including unallocated income/expenses."""
    totals = calculation.totals()
    return float(totals["net_profit"]) + float(totals["unallocated"])


class ReportTotalsOZPriceAnalyzerApp(OverviewExportOZPriceAnalyzerApp):
    """v0.5.16: explicit full-report result and clearer financial headings."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._install_report_total_kpi()
        self._clarify_financial_headings()
        self.after_idle(self._refresh_report_total_kpi)

    def _install_report_total_kpi(self) -> None:
        self.kpi_frame.columnconfigure(6, weight=1)
        for child in self.kpi_frame.winfo_children():
            try:
                info = child.grid_info()
                if int(info.get("row", -1)) in (0, 2):
                    child.grid_configure(columnspan=7)
            except (TypeError, ValueError):
                continue

        self.kpi_vars["report_total"] = self.kpi_vars.get("report_total") or __import__("tkinter").StringVar(
            master=self,
            value="—",
        )
        card = ttk.Frame(self.kpi_frame, style="Card.TFrame", padding=(16, 14))
        card.grid(row=1, column=6, sticky="nsew", padx=(5, 0))
        ttk.Label(
            card,
            text="Итог отчёта с нераспределёнными",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            textvariable=self.kpi_vars["report_total"],
            style="Kpi.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def _clarify_financial_headings(self) -> None:
        self.overview_tree.heading("profit_unit", text="Финрезультат Ozon на ед.")
        self.overview_tree.heading(
            "profit_total",
            text="Финрезультат Ozon до с/с и налога",
        )
        self.scenario_tree.heading("profit", text="Прибыль до себестоимости")
        if hasattr(self, "_heading_tooltips"):
            self.after_idle(self._heading_tooltips.fit_all)

    def _populate_overview(self) -> None:
        super()._populate_overview()
        self._refresh_report_total_kpi()

    def _refresh_report_total_kpi(self) -> None:
        variable = self.kpi_vars.get("report_total")
        if variable is None:
            return
        calculation = self.overview_calculation
        if calculation is None:
            variable.set("—")
            return
        variable.set(_money(report_total_value(calculation)))


def run_app() -> None:
    app = ReportTotalsOZPriceAnalyzerApp()
    app.mainloop()
