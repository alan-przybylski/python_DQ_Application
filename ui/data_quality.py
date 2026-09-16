import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from database.connection import get_connection
from logic.datasets import list_tables, table_columns, quote
from logic.dq_engine import validate_rule, error_text
from logic.rules import archive_rule, save_rule
from ui.common import header, footer, table_view, error_box
from ui.check_dq_panel import CheckDqPanel
from ui.utils import place_window


class DataQualityWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.username, self.role = root, username, role
        self.dashboard_root, self.time_var = dashboard_root, time_var
        place_window(root)
        root.title("DQ Studio / " + tr("Rule library"))
        header(root, "Rule library", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        toolbar = tk.Frame(root)
        toolbar.pack(fill="x", padx=20, pady=12)
        tk.Button(toolbar, text=tr("Add rule"), command=self.add_rule_window).pack(
            side="left", padx=4
        )
        tk.Button(
            toolbar, text=tr("Deactivate rule"), command=self.deactivate_dq_rule
        ).pack(side="left", padx=4)
        tk.Button(toolbar, text=tr("Quality report"), command=self.check_dq_panel).pack(
            side="right", padx=4
        )
        tk.Label(root, text=tr("Active rules"), font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=24
        )
        self.tree_frame, self.tree = table_view(
            root,
            [
                ("id", "Rule", 60),
                ("status", "Status", 95),
                ("version", "Version", 75),
                ("description", "Description", 240),
                ("rule_type", "Rule type", 120),
                ("target_table", "Table", 145),
                ("error_message", "Error message", 230),
                ("sql_query", "SQL query", 420),
            ],
            5,
        )
        self.tree_frame.pack(fill="both", expand=True, padx=24, pady=6)
        middle = tk.Frame(root)
        middle.pack(fill="x", padx=24, pady=4)
        tk.Label(middle, text=tr("Archived rules"), font=("Segoe UI", 12, "bold")).pack(
            side="left"
        )
        tk.Button(middle, text=tr("Modify rule"), command=self.modify_dq_rule).pack(
            side="right"
        )
        self.archive_frame, self.archive_tree = table_view(
            root,
            [
                ("rule_id", "Rule", 65),
                ("version", "Version", 80),
                ("status", "Status", 95),
                ("created_at", "Created", 170),
                ("description", "Description", 240),
                ("rule_type", "Rule type", 120),
                ("target_table", "Table", 145),
                ("deactivated_by", "Username", 140),
                ("deactivated_at", "Date", 170),
            ],
            4,
        )
        self.archive_frame.pack(fill="both", expand=True, padx=24, pady=6)
        for tree in (self.tree, self.archive_tree):
            for column in tree["columns"]:
                tree.heading(
                    column,
                    command=lambda t=tree, c=column: self.treeview_sort_column(
                        t, c, False
                    ),
                )
        self.load_rules()
        self.load_archive_rules()

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def load_rules(self):
        connection = get_connection()
        try:
            self.tree.delete(*self.tree.get_children())
            for row in connection.execute(
                "SELECT id,status,version,description,rule_type,target_table,error_message,sql_query FROM dq_rules WHERE status='ACTIVE' ORDER BY id"
            ):
                self.tree.insert("", "end", values=row)
        finally:
            connection.close()

    def get_tables(self):
        return list_tables()

    def add_rule_window(self):
        self.rule_form()

    def rule_form(self, rule_id=None):
        values = ("", "", "", "", "")
        if rule_id is not None:
            connection = get_connection()
            try:
                row = connection.execute(
                    "SELECT description,rule_type,target_table,error_message,sql_query,status FROM dq_rules WHERE id=?",
                    (rule_id,),
                ).fetchone()
                if not row:
                    raise AppError("Rule not found.")
                if row[5].upper() == "ACTIVE":
                    raise AppError("Deactivate the rule before modifying it.")
                values = row[:5]
            finally:
                connection.close()
        win = tk.Toplevel(self.root)
        place_window(win)
        win.transient(self.root)
        win.title(tr("Add rule" if rule_id is None else "Modify rule"))
        header(win, "Add rule" if rule_id is None else "Modify rule")
        footer(win, win.destroy)
        form = tk.Frame(win)
        form.pack(fill="both", expand=True, padx=40, pady=12)
        form.columnconfigure(1, weight=1)
        description, kind, table, message, sql = values
        self.form_table = tk.StringVar(value=table or next(iter(self.get_tables()), ""))
        description_var, kind_var, message_var = (
            tk.StringVar(value=description),
            tk.StringVar(value=kind),
            tk.StringVar(value=error_text(message)),
        )
        for index, (label, variable) in enumerate(
            (
                ("Description", description_var),
                ("Rule type", kind_var),
                ("Error message", message_var),
            )
        ):
            tk.Label(form, text=tr(label)).grid(
                row=index, column=0, sticky="w", padx=(0, 16), pady=8
            )
            tk.Entry(form, textvariable=variable, width=65).grid(
                row=index, column=1, sticky="ew", pady=8
            )
        tk.Label(form, text=tr("Table")).grid(row=3, column=0, sticky="w", pady=8)
        table_selector = ttk.Combobox(
            form,
            textvariable=self.form_table,
            values=self.get_tables(),
            state="readonly",
            width=45,
        )
        table_selector.grid(row=3, column=1, sticky="ew", pady=8)
        tk.Label(form, text=tr("SQL query")).grid(row=4, column=0, sticky="nw", pady=8)
        sql_entry = tk.Text(form, height=7, width=70, wrap="word")
        sql_entry.grid(row=4, column=1, sticky="nsew", pady=8)
        form.rowconfigure(4, weight=1)
        generated_sql = ""

        def example_sql(event=None):
            nonlocal generated_sql
            current = sql_entry.get("1.0", "end-1c").strip()
            if current and current != generated_sql:
                return
            table_name = self.form_table.get()
            if not table_name:
                return
            names = [column["name"] for column in table_columns(table_name)]
            field = next((name for name in names if name != "id"), None)
            expression = quote(field) if field else "id AS checked_value"
            generated_sql = f"SELECT id, {expression},\n       1 AS dq_check\nFROM {quote(table_name)};"
            sql_entry.delete("1.0", "end")
            sql_entry.insert("1.0", generated_sql)

        sql_entry.insert("1.0", sql)
        table_selector.bind("<<ComboboxSelected>>", example_sql)
        example_sql()
        tk.Label(
            form,
            text=tr(
                "Rule output must contain id, the tested field as the second column, and dq_check (0 or 1)."
            ),
            wraplength=780,
            justify="left",
            font=("Segoe UI", 9),
        ).grid(row=5, column=1, sticky="w", pady=4)

        def submit():
            try:
                save_rule(
                    description_var.get(),
                    kind_var.get(),
                    self.form_table.get(),
                    sql_entry.get("1.0", "end-1c"),
                    message_var.get(),
                    rule_id,
                )
                self.load_rules()
                self.load_archive_rules()
                messagebox.showinfo(tr("Success"), tr("Rule saved."), parent=win)
                win.destroy()
            except Exception as error:
                error_box(error, win)

        tk.Button(form, text=tr("Save changes"), command=submit).grid(
            row=6, column=1, sticky="e", pady=6
        )

    def deactivate_dq_rule(self):
        try:
            selection = self.tree.selection()
            if not selection:
                raise AppError("Select a rule.")
            archive_rule(self.tree.item(selection[0], "values")[0], self.username)
            self.load_rules()
            self.load_archive_rules()
            messagebox.showinfo(
                tr("Success"), tr("Rule deactivated and archived."), parent=self.root
            )
        except Exception as error:
            error_box(error, self.root)

    def modify_dq_rule(self):
        try:
            selection = self.archive_tree.selection()
            if not selection:
                raise AppError("Select a rule.")
            self.rule_form(self.archive_tree.item(selection[0], "values")[0])
        except Exception as error:
            error_box(error, self.root)

    def load_archive_rules(self):
        connection = get_connection()
        try:
            self.archive_tree.delete(*self.archive_tree.get_children())
            for row in connection.execute(
                "SELECT rule_id,version,status,created_at,description,rule_type,target_table,deactivated_by,deactivated_at FROM dq_rules_history ORDER BY history_id DESC"
            ):
                self.archive_tree.insert("", "end", values=row)
        finally:
            connection.close()

    def check_dq_panel(self):
        window = tk.Toplevel(self.root)
        try:
            CheckDqPanel(window, self.username, self.role, self.root, self.time_var)
            self.root.withdraw()
        except Exception as error:
            window.destroy()
            error_box(error, self.root)

    def treeview_sort_column(self, tree, col, reverse):
        rows = [(tree.set(item, col), item) for item in tree.get_children("")]
        try:
            rows.sort(key=lambda pair: float(pair[0]), reverse=reverse)
        except ValueError:
            rows.sort(reverse=reverse)
        for index, (_, item) in enumerate(rows):
            tree.move(item, "", index)
        tree.heading(
            col, command=lambda: self.treeview_sort_column(tree, col, not reverse)
        )

    def forbidden_commands(self, rule_text: str):
        validate_rule(
            rule_text,
            self.form_table.get()
            if hasattr(self, "form_table")
            else next(iter(self.get_tables()), ""),
        )
