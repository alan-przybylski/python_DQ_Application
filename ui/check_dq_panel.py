import tkinter as tk
import queue
import json
import threading
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from database.connection import get_connection
from logic.datasets import list_tables
from logic.dq_engine import (
    run_checks,
    runs_for_table,
    run_details,
    trend_for_table,
    export_errors,
)
from logic.dq_report import draw_chart
from ui.common import header, footer, table_view, error_box, save_csv_dialog, environment_filter
from ui.theme import SURFACE, ACCENT, MUTED
from ui.utils import place_window


class CheckDqPanel:
    environment = None
    profile = None

    def __init__(self, root, username, role, data_quality_root, time_var, environment=None, profile=None):
        self.environment, self.profile = environment, profile
        self.root, self.username, self.role = root, username, role
        self.data_quality_root, self.time_var = data_quality_root, time_var
        self.rules_dict, self.runs, self.current = {}, [], None
        place_window(root)
        root.title("DQ Studio / " + tr("Quality report"))
        header(root, "Quality report", username)
        if environment is None:
            self.environment_picker = environment_filter(root, self.change_environment)
        if environment:
            tk.Label(root, text=('Databricks' if environment == 'databricks' else 'Local / SQLite') + (f' / {profile}' if profile else '')).pack(anchor='w', padx=20)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        body = tk.Frame(root)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=2, minsize=125)
        body.rowconfigure(4, weight=1, minsize=85)
        toolbar = tk.Frame(body)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tables = self.get_tables_to_dq_check()
        self.report_table = tk.StringVar(value=tables[0] if tables else "")
        tk.Label(toolbar, text=tr("Table")).pack(side="left", padx=(0, 6))
        selector = ttk.Combobox(
            toolbar,
            textvariable=self.report_table,
            values=tables,
            state="readonly",
            width=19,
        )
        selector.pack(side="left", padx=(0, 10))
        self.table_selector = selector
        selector.bind("<<ComboboxSelected>>", lambda event: self.refresh_report())
        self.run_choice = tk.StringVar()
        self.run_selector = ttk.Combobox(
            toolbar, textvariable=self.run_choice, state="readonly", width=28
        )
        self.run_selector.pack(side="left", padx=4)
        self.run_selector.bind("<<ComboboxSelected>>", lambda event: self.select_run())
        self.export_button = tk.Button(
            toolbar, text=tr("Export errors"), command=self.export_current
        )
        self.export_button.pack(side="right", padx=3)
        tk.Button(toolbar, text=tr("Run checks"), command=self.open_dq_dialog).pack(
            side="right", padx=3
        )
        tk.Button(toolbar, text=tr("Refresh"), command=self.refresh_report).pack(
            side="right", padx=3
        )
        cards = tk.Frame(body)
        cards.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.metrics = {}
        for index, (key, label) in enumerate(
            (
                ("rate", "Pass rate"),
                ("checks", "Checks"),
                ("failed", "Failed checks"),
                ("rules", "Rules completed"),
            )
        ):
            cards.columnconfigure(index, weight=1, uniform="metric")
            card = tk.Frame(cards, background=SURFACE)
            card.grid(row=0, column=index, sticky="ew", padx=(0, 8 if index < 3 else 0))
            tk.Label(
                card,
                text=tr(label),
                background=SURFACE,
                foreground=MUTED,
                font=("Segoe UI", 9),
            ).pack(anchor="w", padx=12, pady=(6, 0))
            value = tk.StringVar(value="—")
            self.metrics[key] = value
            tk.Label(
                card,
                textvariable=value,
                background=SURFACE,
                foreground=ACCENT if key != "failed" else "#BF4655",
                font=("Segoe UI", 19, "bold"),
            ).pack(anchor="w", padx=12, pady=(0, 4))
        self.chart_frame = tk.Frame(body, background=SURFACE)
        self.chart_frame.grid(row=2, column=0, sticky="nsew")
        filters = tk.Frame(body)
        filters.grid(row=3, column=0, sticky="ew", pady=(6, 4))
        tk.Label(
            filters,
            text=tr("Failed records for this run"),
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        self.search = tk.StringVar()
        tk.Entry(filters, textvariable=self.search, width=25).pack(
            side="right", padx=(8, 0)
        )
        tk.Label(filters, text=tr("Search errors")).pack(side="right")
        self.search.trace_add("write", lambda *args: self.render_errors())
        frame, self.error_tree = table_view(
            body,
            [
                ("rule_id", "Rule", 75),
                ("record_id", "Record", 95),
                ("field_name", "Field", 150),
                ("field_value", "Value", 235),
                ("error_message", "Message", 410),
            ],
            3,
        )
        frame.grid(row=4, column=0, sticky="nsew")
        self.error_tree.bind("<Double-1>", self.show_error_detail)
        self.status = tk.Label(
            body, anchor="w", justify="left", font=("Segoe UI", 9), wraplength=1040
        )
        self.status.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.status.bind("<Button-1>", self.show_execution_errors)
        self.refresh_report()
        self.root.bind('<<DQResultsImported>>',lambda event:self.refresh_report(),add='+')

    def go_back(self):
        self.root.destroy()
        self.data_quality_root.deiconify()

    def change_environment(self, environment):
        self.environment = environment
        tables = self.get_tables_to_dq_check()
        self.table_selector.configure(values=tables)
        if self.report_table.get() not in tables:
            self.report_table.set(tables[0] if tables else '')
        self.refresh_report()

    def get_tables_to_dq_check(self):
        from logic.workspaces import report_tables
        return report_tables(self.environment, self.profile)

    def get_active_rules_for_table(self, table_name, execution_mode='local'):
        connection = get_connection()
        try:
            return connection.execute(
                "SELECT id,description FROM dq_rules WHERE status='ACTIVE' AND target_table=?"
                + (" AND execution_mode='databricks'" if execution_mode=='databricks' else " AND sql_engine='sqlite'")
                + (" AND id IN (SELECT rule_id FROM dq_remote_links WHERE profile=?)" if self.profile else '') + " ORDER BY id",
                (table_name, self.profile) if self.profile else (table_name,),
            ).fetchall()
        finally:
            connection.close()

    def get_remote_rule_count(self, table_name):
        connection = get_connection()
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM dq_rules WHERE status='ACTIVE' AND execution_mode='databricks' AND target_table=?",
                (table_name,),
            ).fetchone()[0]
        finally:
            connection.close()

    def open_remote_sync(self):
        from ui.databricks_sync_window import DatabricksSyncWindow
        window = tk.Toplevel(self.root)
        DatabricksSyncWindow(window, self.username, self.role, self.root, self.time_var)

    def refresh_report(self, selected_run=None):
        try:
            table = self.report_table.get()
            self.runs = runs_for_table(table) if table else []
            from logic.workspaces import run_ids
            allowed_runs = run_ids(self.environment, self.profile)
            if allowed_runs is not None:
                self.runs = [run for run in self.runs if run['id'] in allowed_runs]
            self.run_selector.configure(
                values=[f"#{run['id']} / {'Databricks' if run['mode'] == 'databricks' else 'Local'} / {run['started_at']} / {tr(run['status'])}"
                        + (f" / {run['rule_description']}" if run.get('rule_description') else '') for run in self.runs]
            )
            index = next(
                (
                    index
                    for index, run in enumerate(self.runs)
                    if run["id"] == selected_run
                ),
                0,
            )
            if self.runs:
                self.run_selector.current(index)
            else:
                self.run_choice.set(tr("No runs yet"))
            for widget in self.chart_frame.winfo_children():
                widget.destroy()
            self.chart = draw_chart(
                self.chart_frame, trend_for_table(table, self.environment, self.profile) if table else []
            )
            self.select_run()
        except Exception as error:
            error_box(error, self.root)

    def select_run(self):
        index = self.run_selector.current()
        self.current = (
            run_details(self.runs[index]["id"]) if self.runs and index >= 0 else None
        )
        self.export_button.configure(state="normal" if self.current else "disabled")
        if self.current:
            total = self.current["passed"] + self.current["failed"]
            self.metrics["rate"].set(
                f"{100 * self.current['passed'] / total:.1f}%" if total else "—"
            )
            self.metrics["checks"].set(str(total))
            self.metrics["failed"].set(str(self.current["failed"]))
            self.metrics["rules"].set(
                f"{self.current['rules_completed']} / {self.current['rules_requested']}"
            )
            self.status.configure(
                text=f"#{self.current['id']} · {tr(self.current['status'])} · {self.current['completed_at']} · {self.current['username']}"
                + (' · Local / SQLite' if self.current['mode'] != 'databricks' else '')
                + (f" · Databricks · Delta v{self.current['remote']['source_version']}" if self.current.get('remote') else '')
                + (f" · run_id: {self.current['remote']['remote_run_id']}" if self.current.get('remote') else '')
                + (' · '+', '.join(f'{alias}: v{version}' for alias,version in json.loads(self.current['remote'].get('reference_versions') or '{}').items()) if self.current.get('remote') and self.current['remote'].get('reference_versions') not in (None,'{}') else '')
                + (
                    f" · {tr('Execution errors: {details}', details=len(self.current['execution_errors']))}"
                    if self.current["execution_errors"]
                    else ""
                )
            )
        else:
            for value in self.metrics.values():
                value.set("—")
            self.status.configure(
                text=tr(
                    "Legacy results have no run id. Run checks to start linked history."
                )
            )
        self.render_errors()

    def render_errors(self):
        self.error_tree.delete(*self.error_tree.get_children())
        query = self.search.get().casefold()
        for row in self.current["errors"] if self.current else []:
            values = [
                row[key] if row[key] is not None else ""
                for key in (
                    "rule_id",
                    "record_id",
                    "field_name",
                    "field_value",
                    "error_message",
                )
            ]
            if not query or query in " ".join(map(str, values)).casefold():
                self.error_tree.insert("", "end", values=values)

    def show_error_detail(self, event=None):
        selection = self.error_tree.selection()
        if selection:
            values = self.error_tree.item(selection[0], "values")
            labels = ("Rule", "Record", "Field", "Value", "Message")
            messagebox.showinfo(
                tr("Details"),
                "\n".join(
                    f"{tr(label)}: {value}" for label, value in zip(labels, values)
                ),
                parent=self.root,
            )

    def show_execution_errors(self, event=None):
        if self.current and self.current["execution_errors"]:
            messagebox.showerror(
                tr("Error"),
                "\n".join(
                    f"#{error['rule_id']} {error['description']}: {error['message']}"
                    for error in self.current["execution_errors"]
                ),
                parent=self.root,
            )

    def export_current(self):
        if not self.current:
            return
        path = save_csv_dialog(self.root, f"dq_run_{self.current['id']}_errors.csv")
        if path:
            try:
                count = export_errors(self.current["id"], path)
                messagebox.showinfo(
                    tr("Success"),
                    tr("Exported {count} rows.", count=count),
                    parent=self.root,
                )
            except Exception as error:
                error_box(error, self.root)

    def open_dq_dialog(self):
        dialog = tk.Toplevel(self.root)
        place_window(dialog)
        dialog.transient(self.root)
        dialog.title(tr("Run checks"))
        header(dialog, "Run checks")
        footer(dialog, dialog.destroy)
        form = tk.Frame(dialog)
        form.pack(expand=True, padx=24, pady=12)
        tables = self.get_tables_to_dq_check()
        self.selected_table = tk.StringVar(
            value=self.report_table.get()
            if self.report_table.get() in tables
            else tables[0]
            if tables
            else ""
        )
        tk.Label(form, text=tr("Table")).pack(anchor="w", pady=6)
        dropdown = ttk.Combobox(
            form,
            textvariable=self.selected_table,
            values=tables,
            state="readonly",
            width=38,
        )
        dropdown.pack(fill="x")
        tk.Label(form, text=tr('Execution location')).pack(anchor='w',pady=6)
        self.execution_location = tk.StringVar(value='Databricks' if self.environment == 'databricks' or (self.environment is None and self.get_remote_rule_count(self.selected_table.get())) else tr('Local'))
        location = ttk.Combobox(form,textvariable=self.execution_location,
                                values=([tr('Local'),'Databricks'] if self.environment is None else ['Databricks'] if self.environment == 'databricks' else [tr('Local')]),state='readonly',width=38)
        location.pack(fill='x')
        self.run_type = tk.StringVar(value="all")
        for value, label in (("all", "All rules"), ("single", "Single rule")):
            tk.Radiobutton(
                form,
                text=tr(label),
                variable=self.run_type,
                value=value,
                command=self.on_run_type_change,
            ).pack(anchor="w", pady=6)
        self.rule_var = tk.StringVar()
        self.rule_dropdown = ttk.Combobox(
            form, textvariable=self.rule_var, state="disabled", width=38
        )
        self.rule_dropdown.pack(fill="x", pady=8)
        execution_hint = tk.Label(form, wraplength=500, justify="left")
        execution_hint.pack(fill="x", pady=6)
        run_button = tk.Button(
            form, text=tr("Run checks"), command=lambda: self.run_dq_from_dialog(dialog)
        )
        run_button.pack(fill="x", pady=12)
        sync_button = tk.Button(form, text=tr("Databricks sync"), command=self.open_remote_sync)

        def update_rules(event=None):
            engine = 'databricks' if self.execution_location.get()=='Databricks' else 'local'
            rules = self.get_active_rules_for_table(self.selected_table.get(),engine)
            self.rules_dict = {
                f"#{rule_id} / {description}": rule_id for rule_id, description in rules
            }
            self.rule_dropdown.configure(values=list(self.rules_dict))
            self.rule_var.set(next(iter(self.rules_dict), tr("No active rules")))
            remote_count = self.get_remote_rule_count(self.selected_table.get())
            execution_hint.configure(text=tr(
                "Run checks executes rules at the selected location. Databricks results are downloaded automatically.",
            ))
            run_button.configure(state="normal" if rules else "disabled")
            if remote_count:
                sync_button.pack(fill="x", pady=4)
            else:
                sync_button.pack_forget()

        def change_table(event=None):
            if self.environment is None:
                self.execution_location.set('Databricks' if self.get_remote_rule_count(self.selected_table.get()) else tr('Local'))
            update_rules()
        dropdown.bind("<<ComboboxSelected>>", change_table)
        location.bind("<<ComboboxSelected>>",update_rules)
        update_rules()

    def on_run_type_change(self):
        self.rule_dropdown.configure(
            state="disabled" if self.run_type.get() == "all" else "readonly"
        )

    def run_dq_from_dialog(self, dialog):
        table = self.selected_table.get()
        if not table:
            error_box(AppError("Select a table."), dialog)
            return
        rule_id = self.rules_dict.get(self.rule_var.get())
        if self.run_type.get() == "single" and rule_id is None:
            error_box(AppError("No rule selected."), dialog)
            return
        mode = self.run_type.get()
        if self.execution_location.get()=='Databricks':
            self.run_cloud_from_dialog(dialog,table,rule_id if mode=='single' else None)
            return
        dialog.destroy()
        if mode == "all":
            self.run_all_dq_rules(table)
        else:
            self.run_selected_dq_rule(table, rule_id)

    def run_cloud_from_dialog(self,dialog,table,rule_id=None):
        from logic.databricks_sync import mappings
        from logic.databricks_manual import run_remote_checks
        link_id = None
        if rule_id is not None:
            link = next((l for l in mappings() if l['rule_id']==rule_id),None)
            if link is None:
                error_box(AppError('Save the mapping first.'),dialog)
                return
            link_id = link['id']
        def disable(widget):
            for child in widget.winfo_children():
                if isinstance(child,(tk.Button,ttk.Combobox,tk.Radiobutton)):
                    child.configure(state='disabled')
                disable(child)
        disable(dialog)
        progress=tk.Label(dialog,text=tr('Connecting to Databricks… Browser sign-in may be required.'))
        progress.pack(pady=8)
        events=queue.Queue()
        cancel=threading.Event()
        dialog.protocol('WM_DELETE_WINDOW',lambda:(cancel.set(),dialog.destroy()))
        def worker():
            try:
                events.put((True,run_remote_checks(self.username,link_id,cancel=cancel,table=table,profile=self.profile)))
            except Exception as error:
                events.put((False,str(error)))
        def poll():
            if not dialog.winfo_exists():
                return
            try:
                ok,value=events.get_nowait()
            except queue.Empty:
                dialog.after(150,poll)
                return
            dialog.destroy()
            self.report_table.set(table)
            self.refresh_report()
            if ok:
                messagebox.showinfo(tr('Success'),tr('Executed and imported {count} Databricks checks.',count=value),parent=self.root)
            else:
                messagebox.showerror(tr('Error'),value,parent=self.root)
        threading.Thread(target=worker,daemon=True).start()
        dialog.after(150,poll)

    def finish_run(self, table, rule_id=None):
        try:
            run_id = run_checks(table, self.username, rule_id,include_remote=True)
            self.report_table.set(table)
            self.refresh_report(run_id)
            details = run_details(run_id)
            notify = (
                messagebox.showwarning
                if details["status"] != "completed"
                else messagebox.showinfo
            )
            notify(
                tr("Warning" if details["status"] != "completed" else "Success"),
                tr(
                    "Run #{run_id}: {passed} passed, {failed} failed; {errors} execution errors.",
                    run_id=run_id,
                    passed=details["passed"],
                    failed=details["failed"],
                    errors=len(details["execution_errors"]),
                ),
                parent=self.root,
            )
            return run_id
        except Exception as error:
            error_box(error, self.root)

    def run_all_dq_rules(self, table):
        return self.finish_run(table)

    def run_selected_dq_rule(self, table, rule_id):
        return self.finish_run(table, rule_id)
