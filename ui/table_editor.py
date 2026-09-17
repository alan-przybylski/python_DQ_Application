import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from logic.datasets import list_tables, table_columns, TYPES
from logic.table_editor import edit_column
from ui.common import header, footer, table_view, error_box
from ui.utils import place_window


class TableEditor:
    def __init__(self, root, username, parent, on_close, selected=""):
        self.root, self.parent, self.on_close = root, parent, on_close
        place_window(root)
        root.title("DQ Studio / " + tr("Edit table columns"))
        header(root, "Edit table columns", username)
        footer(root, self.go_back)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        bar = tk.Frame(root)
        bar.pack(fill="x", padx=24, pady=12)
        tk.Label(bar, text=tr("Table")).pack(side="left", padx=(0, 12))
        tables = list_tables()
        self.table = tk.StringVar(
            value=selected if selected in tables else (tables[0] if tables else "")
        )
        selector = ttk.Combobox(
            bar, textvariable=self.table, values=tables, state="readonly", width=28
        )
        selector.pack(side="left")
        selector.bind("<<ComboboxSelected>>", lambda event: self.reload())
        tk.Label(
            root,
            text=tr(
                "Backups before changes. Referenced columns and id are protected. CSV templates update automatically."
            ),
            wraplength=1020,
            justify="left",
        ).pack(anchor="w", padx=24, pady=4)
        frame, self.tree = table_view(
            root,
            [
                ("name", "Column", 260),
                ("type", "Type", 160),
                ("required", "Required", 140),
            ],
            8,
        )
        frame.pack(fill="both", expand=True, padx=24, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        form = tk.Frame(root)
        form.pack(fill="x", padx=24, pady=8)
        self.name = tk.StringVar()
        self.kind = tk.StringVar(value="TEXT")
        self.required = tk.BooleanVar()
        tk.Label(form, text=tr("Column name")).grid(row=0, column=0, sticky="w")
        tk.Entry(form, textvariable=self.name, width=30).grid(
            row=1, column=0, padx=(0, 12)
        )
        tk.Label(form, text=tr("Type")).grid(row=0, column=1, sticky="w")
        ttk.Combobox(
            form, textvariable=self.kind, values=TYPES, state="readonly", width=12
        ).grid(row=1, column=1, padx=8)
        tk.Checkbutton(form, variable=self.required, text=tr("Required")).grid(
            row=1, column=2, padx=8
        )
        actions = tk.Frame(root)
        actions.pack(fill="x", padx=24, pady=8)
        for label, action in [
            ("Add column", "add"),
            ("Save column changes", "modify"),
            ("Delete selected column", "drop"),
        ]:
            tk.Button(
                actions, text=tr(label), command=lambda a=action: self.apply(a)
            ).pack(side="left", padx=(0, 10))
        self.reload()

    def reload(self):
        self.columns = table_columns(self.table.get()) if self.table.get() else []
        self.tree.delete(*self.tree.get_children())
        for index, column in enumerate(self.columns):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    column["name"],
                    column["type"],
                    "✓" if column["required"] else "—",
                ),
            )
        self.name.set("")

    def select(self, event=None):
        selected = self.tree.selection()
        if selected:
            column = self.columns[int(selected[0])]
            self.name.set(column["name"])
            self.kind.set(column["type"])
            self.required.set(column["required"])

    def apply(self, action):
        try:
            selected = self.tree.selection()
            column = self.columns[int(selected[0])]["name"] if selected else None
            if action != "add" and not column:
                raise AppError("Select a column.")
            if action == "drop":
                prompt = tr(
                    "Delete {column} from {table}, including all its values? A database backup will be kept.",
                    column=column,
                    table=self.table.get(),
                )
            else:
                prompt = tr(
                    "Apply column change to {table}: {old} -> {name} ({kind}, required={required})? A backup will be kept; unsafe conversions will be rejected.",
                    table=self.table.get(),
                    old=column if action != "add" else "—",
                    name=self.name.get().strip(),
                    kind=self.kind.get(),
                    required=tr("Yes") if self.required.get() else tr("No"),
                )
            if not messagebox.askyesno(tr("Confirm"), prompt, parent=self.root):
                return
            backup = edit_column(
                self.table.get(),
                action,
                column,
                self.name.get().strip(),
                self.kind.get(),
                self.required.get(),
            )
            self.reload()
            messagebox.showinfo(
                tr("Success"),
                tr("Changes saved. Backup: {path}", path=backup),
                parent=self.root,
            )
        except Exception as error:
            error_box(error, self.root)

    def go_back(self):
        self.root.destroy()
        self.on_close()
        self.parent.deiconify()
