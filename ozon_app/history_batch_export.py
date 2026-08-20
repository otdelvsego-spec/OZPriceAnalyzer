from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .exporter import export_run, suggested_export_name
from .shutdown_all_windows import ShutdownAllWindowsOZPriceAnalyzerApp


def ordered_selected_iids(visible_iids, selected_iids) -> list[str]:
    """Return selected tree rows in their visible table order."""
    selected = {str(iid) for iid in selected_iids}
    return [str(iid) for iid in visible_iids if str(iid) in selected]


def available_export_path(
    directory: str | Path,
    filename: str,
    reserved: set[str] | None = None,
) -> Path:
    """Choose a non-overwriting path, adding (2), (3), ... when needed."""
    root = Path(directory).expanduser().resolve()
    requested = Path(filename)
    stem = requested.stem
    suffix = requested.suffix or ".xlsx"
    reserved_paths = reserved if reserved is not None else set()

    candidate = root / f"{stem}{suffix}"
    index = 2
    while candidate.exists() or str(candidate).casefold() in reserved_paths:
        candidate = root / f"{stem} ({index}){suffix}"
        index += 1
    reserved_paths.add(str(candidate).casefold())
    return candidate


class HistoryBatchExportOZPriceAnalyzerApp(ShutdownAllWindowsOZPriceAnalyzerApp):
    """v0.5.14: export every selected history row to its own standard XLSX."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._install_history_batch_export_button()

    def _install_history_batch_export_button(self) -> None:
        header = None
        for child in self.history_tab.winfo_children():
            if child.winfo_manager() != "grid":
                continue
            try:
                if int(child.grid_info().get("row", -1)) == 0:
                    header = child
                    break
            except (TypeError, ValueError, tk.TclError):
                continue
        if header is None:
            return

        self.history_batch_export_button = ttk.Button(
            header,
            text="Выгрузить выбранные XLSX",
            style="Accent.TButton",
            command=self.export_selected_history_runs,
        )
        self.history_batch_export_button.grid(row=0, column=5, padx=(8, 0))

    def export_selected_history_runs(self) -> None:
        selected_iids = ordered_selected_iids(
            self.history_tree.get_children(""),
            self.history_tree.selection(),
        )
        if not selected_iids:
            messagebox.showinfo(
                "Экспорт истории",
                "Выберите один или несколько отчетов в таблице истории.",
                parent=self,
            )
            return

        destination = filedialog.askdirectory(
            title="Выберите папку для выбранных отчетов",
            initialdir=str(self.service.paths["exports"]),
            parent=self,
        )
        if not destination:
            return

        target_dir = Path(destination).expanduser().resolve()
        reserved: set[str] = set()
        exported: list[Path] = []
        failed: list[tuple[int, str]] = []

        self.configure(cursor="watch")
        self.status_var.set(f"Выгрузка выбранных отчетов: {len(selected_iids)}…")
        self.update_idletasks()
        try:
            for iid in selected_iids:
                run_id = int(iid)
                try:
                    calculation = self.db.load_calculation(run_id)
                    output = available_export_path(
                        target_dir,
                        suggested_export_name(calculation),
                        reserved,
                    )
                    exported.append(export_run(self.db, run_id, output))
                except Exception as exc:
                    failed.append((run_id, str(exc)))
        finally:
            self.configure(cursor="")
            self.status_var.set(self._current_run_status())

        if failed:
            details = "\n".join(
                f"• Отчет №{self._run_number(run_id)}: {error}"
                for run_id, error in failed[:10]
            )
            if len(failed) > 10:
                details += f"\n• …и еще ошибок: {len(failed) - 10}"
            messagebox.showwarning(
                "Экспорт истории",
                f"Сохранено файлов: {len(exported)} из {len(selected_iids)}.\n"
                f"Папка:\n{target_dir}\n\n"
                f"Не удалось выгрузить:\n{details}",
                parent=self,
            )
            return

        messagebox.showinfo(
            "Экспорт истории",
            f"Сохранено отдельных XLSX-файлов: {len(exported)}.\n\n"
            f"Папка:\n{target_dir}",
            parent=self,
        )


def run_app() -> None:
    app = HistoryBatchExportOZPriceAnalyzerApp()
    app.mainloop()
