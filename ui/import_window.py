import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config.i18n import tr, AppError
from logic.datasets import (
    TYPES,
    list_tables,
    table_columns,
    read_csv,
    suggested_type,
    import_data,
    create_dataset,
    export_template,
)
from ui.common import header, footer, table_view, error_box, save_csv_dialog
from ui.utils import place_window


class ImportWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.username, self.dashboard_root = root, username, dashboard_root
        self.data, self.columns, self.mapping = None, [], {}
        place_window(root)
        root.title("DQ Studio / " + tr("Import CSV"))
        header(root, "Import CSV", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        sources = tk.Frame(root)
        sources.pack(fill="x", padx=24, pady=(6, 0))
        tk.Button(
            sources, text=tr("Import from Databricks"), command=self.open_databricks
        ).pack(side="left")
        tk.Button(
            sources, text=tr("Edit table columns"), command=self.open_table_editor
        ).pack(side="right")
        controls = tk.Frame(root)
        controls.pack(fill="x", padx=20, pady=(10, 4))
        self.mode = tk.StringVar(value="existing")
        for value, label in (
            ("existing", "Existing table"),
            ("new", "Create a new table"),
        ):
            tk.Radiobutton(
                controls,
                text=tr(label),
                variable=self.mode,
                value=value,
                command=self.change_mode,
            ).pack(side="left", padx=6)
        tk.Button(controls, text=tr("Choose file"), command=self.choose_file).pack(
            side="right"
        )
        names = tk.Frame(root)
        names.pack(fill="x", padx=24, pady=4)
        tk.Label(names, text=tr("Table")).pack(side="left", padx=(0, 8))
        tables = list_tables()
        self.table_var = tk.StringVar(value=tables[0] if tables else "")
        self.table_selector = ttk.Combobox(
            names,
            textvariable=self.table_var,
            values=tables,
            state="readonly",
            width=24,
        )
        self.table_selector.pack(side="left")
        self.table_selector.bind(
            "<<ComboboxSelected>>", lambda event: self.update_columns()
        )
        self.new_name = tk.StringVar()
        self.name_entry = tk.Entry(names, textvariable=self.new_name, width=25)
        self.template_button = tk.Button(
            names, text=tr("Download CSV template"), command=self.download_template
        )
        self.template_button.pack(side="right")
        self.filename = tk.Label(root, text=tr("No file selected"), anchor="w")
        self.filename.pack(fill="x", padx=24, pady=4)
        body = tk.Frame(root)
        body.pack(fill="both", expand=True, padx=20, pady=6)
        body.columnconfigure(0, weight=1, uniform="pane")
        body.columnconfigure(1, weight=1, uniform="pane")
        body.rowconfigure(1, weight=1)
        tk.Label(
            body, text=tr("Columns / mapping"), font=("Segoe UI", 11, "bold")
        ).grid(row=0, column=0, sticky="w", pady=5)
        tk.Label(body, text=tr("Preview"), font=("Segoe UI", 11, "bold")).grid(
            row=0, column=1, sticky="w", padx=12, pady=5
        )
        frame, self.column_tree = table_view(
            body,
            [
                ("source", "Source column", 135),
                ("target", "Target column", 145),
                ("type", "Type", 80),
                ("required", "Required", 70),
            ],
            5,
        )
        frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.preview_frame, self.preview_tree = table_view(body, [], 5)
        self.preview_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self.column_tree.bind("<<TreeviewSelect>>", self.select_column)
        editor = tk.Frame(body)
        editor.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Label(editor, text=tr("Target column")).grid(row=0, column=0, sticky="w")
        self.column_name = tk.StringVar()
        self.column_entry = ttk.Combobox(
            editor, textvariable=self.column_name, width=21
        )
        self.column_entry.grid(row=1, column=0, padx=(0, 8))
        self.type_var = tk.StringVar(value="TEXT")
        tk.Label(editor, text=tr("Type")).grid(row=0, column=1, sticky="w")
        self.type_combo = ttk.Combobox(
            editor, textvariable=self.type_var, values=TYPES, state="readonly", width=10
        )
        self.type_combo.grid(row=1, column=1, padx=6)
        self.required = tk.BooleanVar()
        self.required_box = tk.Checkbutton(
            editor, text=tr("Required"), variable=self.required
        )
        self.required_box.grid(row=1, column=2, padx=6)
        tk.Button(editor, text=tr("Apply column"), command=self.apply_column).grid(
            row=1, column=3, padx=6
        )
        self.add_button = tk.Button(
            editor, text=tr("Add column"), command=self.add_column
        )
        self.add_button.grid(row=1, column=4, padx=6)
        self.remove_button = tk.Button(
            editor, text=tr("Remove column"), command=self.remove_column
        )
        self.remove_button.grid(row=1, column=5, padx=6)
        self.hint = tk.Label(root, anchor="w", font=("Segoe UI", 9), wraplength=1040)
        self.hint.pack(fill="x", padx=24, pady=4)
        actions = tk.Frame(root)
        actions.pack(fill="x", padx=24, pady=(4, 8))
        self.create_button = tk.Button(
            actions, text=tr("Create table only"), command=self.create_only
        )
        self.create_button.pack(side="left")
        tk.Button(actions, text=tr("Import"), command=self.import_file).pack(
            side="right"
        )
        self.change_mode()

    def change_mode(self):
        new = self.mode.get() == "new"
        if new:
            self.table_selector.pack_forget()
            self.name_entry.pack(side="left")
        else:
            self.name_entry.pack_forget()
            self.table_selector.pack(side="left")
        for button in (self.add_button, self.remove_button, self.create_button):
            button.configure(state="normal" if new else "disabled")
        self.template_button.configure(state="disabled" if new else "normal")
        self.type_combo.configure(state="readonly" if new else "disabled")
        self.required_box.configure(state="normal" if new else "disabled")
        self.column_entry.configure(state="normal" if new else "readonly")
        self.hint.configure(
            text=tr(
                "If no id column is defined, an INTEGER id is generated automatically."
                if new
                else "Rows with matching id update existing records; missing generated id creates a new record."
            )
        )
        self.update_columns()

    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title=tr("Choose CSV file"),
            filetypes=[(tr("CSV files"), "*.csv"), (tr("All files"), "*.*")],
        )
        if not path:
            return
        try:
            self.data = read_csv(path)
            self.filename.configure(
                text=f"{self.data.filename} — "
                + tr(
                    "Preview: {count} rows. Showing the first {shown}.",
                    count=len(self.data.rows),
                    shown=min(20, len(self.data.rows)),
                )
            )
            self.preview_tree.configure(columns=self.data.headers)
            for name in self.data.headers:
                self.preview_tree.heading(name, text=name)
                self.preview_tree.column(name, width=140, stretch=False)
            self.preview_tree.delete(*self.preview_tree.get_children())
            for row in self.data.rows[:20]:
                self.preview_tree.insert("", "end", values=row)
            self.update_columns()
        except Exception as error:
            error_box(error, self.root)

    def update_columns(self):
        try:
            if self.mode.get() == "new":
                self.columns, self.mapping = [], {}
                if self.data:
                    used = set()
                    for index, source in enumerate(self.data.headers):
                        base = re.sub(r"[^A-Za-z0-9_]", "_", source)
                        if not base or base[0].isdigit():
                            base = "col_" + base
                        if base.casefold() == "id":
                            base = "id"
                        name, suffix = base, 2
                        while name.casefold() in used:
                            name, suffix = f"{base}_{suffix}", suffix + 1
                        used.add(name.casefold())
                        kind = suggested_type([row[index] for row in self.data.rows])
                        if name == "id" and kind == "REAL":
                            kind = "TEXT"
                        self.columns.append(
                            {"name": name, "type": kind, "required": name == "id"}
                        )
                        self.mapping[source] = name
            else:
                self.columns = (
                    table_columns(self.table_var.get()) if self.table_var.get() else []
                )
                names = {
                    column["name"].casefold(): column["name"] for column in self.columns
                }
                self.mapping = (
                    {
                        source: names.get(source.casefold(), "")
                        for source in self.data.headers
                    }
                    if self.data
                    else {}
                )
                self.column_entry.configure(
                    values=[tr("Ignore"), *[column["name"] for column in self.columns]]
                )
            self.render_columns()
        except Exception as error:
            error_box(error, self.root)

    def render_columns(self):
        self.column_tree.delete(*self.column_tree.get_children())
        if self.mode.get() == "new" or not self.data:
            for index, column in enumerate(self.columns):
                source = next(
                    (
                        key
                        for key, value in self.mapping.items()
                        if value == column["name"]
                    ),
                    "—",
                )
                self.column_tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        source,
                        column["name"],
                        column["type"],
                        "✓" if column["required"] else "—",
                    ),
                )
        else:
            for index, source in enumerate(self.data.headers):
                target = self.mapping[source]
                column = next(
                    (column for column in self.columns if column["name"] == target), {}
                )
                self.column_tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        source,
                        tr("Ignore")
                        if target is None
                        else target or tr("Select a column"),
                        column.get("type", ""),
                        "✓" if column.get("required") else "—",
                    ),
                )

    def select_column(self, event=None):
        selected = self.column_tree.selection()
        if selected:
            values = self.column_tree.item(selected[0], "values")
            self.column_name.set(values[1])
            self.type_var.set(values[2])
            self.required.set(values[3] == "✓")

    def apply_column(self):
        try:
            selected = self.column_tree.selection()
            if not selected:
                raise AppError("Select or add a column.")
            index = int(selected[0])
            if self.mode.get() == "new":
                old = self.columns[index]["name"]
                new = self.column_name.get().strip()
                self.columns[index] = {
                    "name": new,
                    "type": self.type_var.get(),
                    "required": self.required.get(),
                }
                self.mapping = {
                    key: new if value == old else value
                    for key, value in self.mapping.items()
                }
            elif self.data:
                self.mapping[self.data.headers[index]] = (
                    None
                    if self.column_name.get() == tr("Ignore")
                    else self.column_name.get()
                )
            self.render_columns()
        except Exception as error:
            error_box(error, self.root)

    def add_column(self):
        self.columns.append(
            {
                "name": f"column_{len(self.columns) + 1}",
                "type": "TEXT",
                "required": False,
            }
        )
        self.render_columns()
        self.column_tree.selection_set(str(len(self.columns) - 1))
        self.select_column()

    def remove_column(self):
        selected = self.column_tree.selection()
        if selected:
            old = self.columns.pop(int(selected[0]))["name"]
            self.mapping = {
                key: None if value == old else value
                for key, value in self.mapping.items()
            }
            self.render_columns()

    def download_template(self):
        try:
            table = self.table_var.get()
            if not table:
                raise AppError("Select a table.")
            path = save_csv_dialog(self.root, table + "_template.csv")
            if path:
                export_template(table, path)
                messagebox.showinfo(
                    tr("Success"), tr("Template saved."), parent=self.root
                )
        except Exception as error:
            error_box(error, self.root)

    def create_only(self):
        try:
            create_dataset(self.new_name.get().strip(), self.columns)
            messagebox.showinfo(
                tr("Success"),
                tr("Table created: {table}", table=self.new_name.get().strip()),
                parent=self.root,
            )
            self.select_created_table()
        except Exception as error:
            error_box(error, self.root)

    def select_created_table(self):
        self.table_var.set(self.new_name.get().strip())
        self.table_selector.configure(values=list_tables())
        self.mode.set("existing")
        self.change_mode()

    def import_file(self):
        try:
            if self.data is None:
                raise AppError("Select a CSV file first.")
            new = self.mode.get() == "new"
            table = self.new_name.get().strip() if new else self.table_var.get()
            if not table:
                raise AppError("Select a table.")
            count = import_data(
                self.data,
                table,
                self.username,
                self.mapping,
                self.columns if new else None,
            )
            messagebox.showinfo(
                tr("Success"),
                tr(
                    "Imported {count} rows into {table}. All changes committed together.",
                    count=count,
                    table=table,
                ),
                parent=self.root,
            )
            if new:
                self.select_created_table()
        except Exception as error:
            error_box(error, self.root)

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def refresh_tables(self):
        tables = list_tables()
        self.table_selector.configure(values=tables)
        if self.table_var.get() not in tables:
            self.table_var.set(tables[0] if tables else "")
        if self.mode.get() == "existing":
            self.update_columns()

    def open_databricks(self):
        from ui.databricks_window import DatabricksWindow

        window = tk.Toplevel(self.root)
        DatabricksWindow(window, self.username, self.root, self.refresh_tables)
        self.root.withdraw()

    def open_table_editor(self):
        from ui.table_editor import TableEditor

        window = tk.Toplevel(self.root)
        TableEditor(
            window, self.username, self.root, self.refresh_tables, self.table_var.get()
        )
        self.root.withdraw()
