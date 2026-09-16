import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from database.connection import get_connection
from logic.datasets import list_tables, checked_table, export_table
from ui.common import header, footer, table_view, error_box, save_csv_dialog
from ui.utils import place_window


class ExportWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.dashboard_root = root, dashboard_root
        place_window(root)
        root.title("DQ Studio / " + tr("Export table"))
        header(root, "Export table", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        toolbar = tk.Frame(root)
        toolbar.pack(fill="x", padx=24, pady=16)
        tables = list_tables()
        self.table = tk.StringVar(value=tables[0] if tables else "")
        tk.Label(toolbar, text=tr("Table")).pack(side="left", padx=(0, 10))
        dropdown = ttk.Combobox(
            toolbar, textvariable=self.table, values=tables, state="readonly", width=25
        )
        dropdown.pack(side="left")
        dropdown.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.safe = tk.BooleanVar(value=True)
        tk.Checkbutton(
            toolbar, text=tr("Protect spreadsheet formulas"), variable=self.safe
        ).pack(side="left", padx=12)
        tk.Button(toolbar, text=tr("Export CSV"), command=self.export).pack(
            side="right"
        )
        frame, self.tree = table_view(root, [], 12)
        frame.pack(fill="both", expand=True, padx=24, pady=12)
        self.refresh()

    def refresh(self):
        if not self.table.get():
            return
        connection = get_connection()
        try:
            cursor = connection.execute(
                f"SELECT * FROM {checked_table(connection, self.table.get())} LIMIT 100"
            )
            names = [column[0] for column in cursor.description]
            self.tree.configure(columns=names)
            for name in names:
                self.tree.heading(name, text=name)
                self.tree.column(name, width=160, stretch=False)
            self.tree.delete(*self.tree.get_children())
            for row in cursor:
                self.tree.insert(
                    "", "end", values=["" if value is None else value for value in row]
                )
        finally:
            connection.close()

    def export(self):
        try:
            if not self.table.get():
                raise AppError("Select a table.")
            path = save_csv_dialog(self.root, self.table.get() + ".csv")
            if path:
                count = export_table(self.table.get(), path, self.safe.get())
                messagebox.showinfo(
                    tr("Success"),
                    tr("Exported {count} rows.", count=count),
                    parent=self.root,
                )
        except Exception as error:
            error_box(error, self.root)

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()
