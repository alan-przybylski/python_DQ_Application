import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from database.connection import get_connection
from logic.datasets import list_tables, table_columns, quote
from logic.dq_engine import validate_rule, error_text
from logic.rules import archive_rule, save_rule
from logic.rule_library import list_rules
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
        tk.Button(toolbar, text=tr("Open rule"), command=self.open_rule).pack(
            side="left", padx=4
        )
        tk.Button(toolbar, text=tr("Refresh"), command=self.load_rules).pack(
            side="right", padx=4
        )
        filters = tk.Frame(root)
        filters.pack(fill="x", padx=24, pady=4)
        self.search = tk.StringVar()
        self.table_filter = tk.StringVar(value=tr("All tables"))
        self.status_filter = tk.StringVar(value=tr("All statuses"))
        tk.Label(filters, text=tr("Search rules")).pack(side="left", padx=(0, 8))
        search_entry = tk.Entry(filters, textvariable=self.search, width=28)
        search_entry.pack(side="left", padx=(0, 16))
        search_entry.bind("<KeyRelease>", lambda event: self.render_rules())
        self.table_picker = ttk.Combobox(
            filters, textvariable=self.table_filter, state="readonly", width=20
        )
        self.table_picker.pack(side="left", padx=8)
        self.table_picker.bind(
            "<<ComboboxSelected>>", lambda event: self.render_rules()
        )
        status_picker = ttk.Combobox(
            filters,
            textvariable=self.status_filter,
            values=[tr("All statuses"), tr("Active"), tr("Inactive")],
            state="readonly",
            width=17,
        )
        status_picker.pack(side="left", padx=8)
        status_picker.bind("<<ComboboxSelected>>", lambda event: self.render_rules())
        self.summary = tk.StringVar()
        tk.Label(root, textvariable=self.summary, anchor="w").pack(
            fill="x", padx=24, pady=6
        )
        self.tree_frame, self.tree = table_view(
            root,
            [
                ("id", "Rule", 65),
                ("description", "Description", 365),
                ("target_table", "Table", 200),
                ("status", "Status", 160),
                ("kpi", "Last KPI", 180),
            ],
            5,
        )
        self.tree_frame.pack(fill="both", expand=True, padx=24, pady=6)
        self.tree.column("description", stretch=True)
        self.tree.tag_configure("inactive", foreground="#526581", background="#EDF0F4")
        self.tree.tag_configure("active", foreground="#124F45", background="#F0FAF7")
        self.tree.bind("<Double-1>", self.open_rule)
        self.tree.bind("<Return>", self.open_rule)
        for column in self.tree["columns"]:
            self.tree.heading(
                column,
                command=lambda c=column: self.treeview_sort_column(self.tree, c, False),
            )
        tk.Label(
            root,
            text=tr(
                "Double-click a rule for its definition, results and version history. KPI refers to its current version only."
            ),
            anchor="w",
            wraplength=1020,
        ).pack(fill="x", padx=24, pady=8)
        self.load_rules()

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def load_rules(self):
        self.rules = list_rules()
        tables = sorted({row["target_table"] for row in self.rules})
        self.table_picker.configure(values=[tr("All tables"), *tables])
        self.render_rules()

    def render_rules(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        search, table, status = (
            self.search.get().casefold().strip(),
            self.table_filter.get(),
            self.status_filter.get(),
        )
        for row in self.rules:
            active = row["status"] == "ACTIVE"
            if table != tr("All tables") and table != row["target_table"]:
                continue
            if (
                status == tr("Active")
                and not active
                or status == tr("Inactive")
                and active
            ):
                continue
            if (
                search
                and search
                not in f"{row['id']} {row['description']} {row['target_table']} {row['rule_type']}".casefold()
            ):
                continue
            kpi = (
                "—"
                if not active
                else tr("No results")
                if row["result_id"] is None
                else tr("No checked rows")
                if row["kpi"] is None
                else f"{row['kpi']:.1f}%"
            )
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["description"],
                    row["target_table"],
                    "● " + tr("Active rule") if active else "○ " + tr("Inactive rule"),
                    kpi,
                ),
                tags=("active" if active else "inactive",),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self.summary.set(
            tr(
                "Showing {shown} of {total} rules · {active} active",
                shown=len(self.tree.get_children()),
                total=len(self.rules),
                active=sum(row["status"] == "ACTIVE" for row in self.rules),
            )
        )

    def selected_rule(self):
        selection = self.tree.selection()
        if not selection:
            raise AppError("Select a rule.")
        return int(selection[0])

    def open_rule(self, event=None):
        from ui.rule_details import RuleDetailsWindow

        try:
            rule_id = self.selected_rule()
            window = tk.Toplevel(self.root)
            try:
                self.details = RuleDetailsWindow(window, rule_id, self)
            except Exception:
                window.destroy()
                raise
        except Exception as error:
            error_box(error, self.root)

    def get_tables(self):
        return list_tables()

    def add_rule_window(self):
        self.rule_form()

    def rule_form(self, rule_id=None, initial_sql="", initial_table=""):
        values = ("", "", initial_table, "", initial_sql)
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
            generated_sql = f"SELECT id, {expression},\n       0 AS dq_check\nFROM {quote(table_name)};"
            sql_entry.delete("1.0", "end")
            sql_entry.insert("1.0", generated_sql)

        sql_entry.insert("1.0", sql)
        table_selector.bind("<<ComboboxSelected>>", example_sql)
        example_sql()
        tk.Label(
            form,
            text=tr(
                "Rule output must contain id, the tested field as the second column, and dq_check (0 = PASS, 1 = FAIL)."
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
            self.rule_form(self.selected_rule())
        except Exception as error:
            error_box(error, self.root)

    def load_archive_rules(self):
        # Retained public entry point; history is now loaded inside rule details.
        self.load_rules()

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
        if col == "kpi":
            numeric = [row for row in rows if row[0].endswith("%")]
            missing = [row for row in rows if not row[0].endswith("%")]
            numeric.sort(key=lambda pair: float(pair[0][:-1]), reverse=reverse)
            rows = numeric + missing
        else:
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
