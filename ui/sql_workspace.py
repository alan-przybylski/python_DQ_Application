"""A focused SQL workbench: browse, preview, then create a rule."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config.db_config import config
from config.i18n import tr
from logic.datasets import list_tables, table_columns, quote
from logic.sql_workspace import preview_query
from ui.common import header, footer, table_view
from ui.theme import ACCENT, MUTED, SURFACE
from ui.utils import place_window


class SqlWorkspace:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.username, self.role = root, username, role
        self.dashboard_root, self.time_var = dashboard_root, time_var
        self.cancel = threading.Event()
        self.messages = queue.Queue()
        self.running = False
        self.closed = False
        self.nodes = {}
        place_window(root, 1200, 800)
        root.resizable(True, True)
        root.title("DQ Studio / " + tr("SQL editor"))
        header(root, "SQL editor", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        tk.Label(root, text=tr("1. Choose a table   →   2. Run SQL   →   3. Create a rule"),
                 anchor="w", foreground=MUTED).pack(fill="x", padx=20, pady=10)
        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        sidebar, work = tk.Frame(panes), tk.Frame(panes)
        panes.add(sidebar, weight=1)
        panes.add(work, weight=4)
        tk.Label(sidebar, text=tr("Dataset tables"), font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Button(sidebar, text=tr("Refresh"), command=self.refresh).pack(anchor="w", pady=6)
        tree_box = tk.Frame(sidebar)
        tree_box.pack(fill="both", expand=True)
        self.schema = ttk.Treeview(tree_box, show="tree", selectmode="browse", height=8)
        scroll = ttk.Scrollbar(tree_box, command=self.schema.yview)
        self.schema.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.schema.pack(fill="both", expand=True)
        self.schema.bind("<Double-1>", self.insert_name)
        tk.Label(sidebar, text=tr("Double-click to insert a table or column."),
                 wraplength=210, justify="left", foreground=MUTED).pack(anchor="w", pady=8)
        tk.Button(sidebar, text=tr("Preview table"), command=self.table_query).pack(fill="x", pady=3)
        tk.Button(sidebar, text=tr("Rule template"), command=lambda: self.table_query(rule=True)).pack(fill="x", pady=3)
        tk.Label(work, text=tr("SQL query") + "  ·  dq_check: 0 = PASS, 1 = FAIL",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        vertical = ttk.Panedwindow(work, orient="vertical")
        vertical.pack(fill="both", expand=True)
        top, bottom = tk.Frame(vertical), tk.Frame(vertical)
        vertical.add(top, weight=2)
        vertical.add(bottom, weight=3)
        editor_frame = tk.Frame(top)
        editor_frame.pack(fill="both", expand=True, pady=6)
        self.editor = tk.Text(editor_frame, height=9, width=70, wrap="none", undo=True,
                              font=("Consolas", 11), padx=12, pady=10, background=SURFACE)
        y = ttk.Scrollbar(editor_frame, command=self.editor.yview)
        x = ttk.Scrollbar(editor_frame, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.editor.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        self.editor.tag_configure("keyword", foreground=ACCENT)
        self.editor.bind("<KeyRelease>", self.highlight)
        self.editor.bind("<Control-Return>", self.run)
        toolbar = tk.Frame(top)
        toolbar.pack(fill="x", pady=6)
        self.run_button = tk.Button(toolbar, text=tr("Run SQL · Ctrl+Enter"), command=self.run)
        self.run_button.pack(side="left")
        self.stop_button = tk.Button(toolbar, text=tr("Cancel"), command=self.cancel.set, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        tk.Button(toolbar, text=tr("Create rule"), command=self.create_rule).pack(side="right")
        tk.Label(top, text=tr("Runs selected SQL, or the whole editor. Read-only · up to 500 rows · 10 seconds."),
                 anchor="w", wraplength=760, foreground=MUTED).pack(fill="x", pady=(0, 8))
        self.status = tk.StringVar(value=tr("Choose a table and preview its data, or write your own SELECT."))
        tk.Label(bottom, textvariable=self.status, anchor="w", justify="left",
                 wraplength=760).pack(fill="x", pady=8)
        self.result_frame, self.results = table_view(bottom, [], 8)
        self.result_frame.pack(fill="both", expand=True)
        self.refresh()
        self.poll_id = root.after(100, self.poll)

    def refresh(self):
        try:
            self.schema.delete(*self.schema.get_children())
            self.nodes.clear()
            for table in list_tables():
                item = self.schema.insert("", "end", text=table, open=True)
                self.nodes[item] = (table, table)
                for col in table_columns(table):
                    child = self.schema.insert(item, "end", text=f"{col['name']}  ·  {col['type']}")
                    self.nodes[child] = (table, col["name"])
            children = self.schema.get_children()
            if children:
                self.schema.selection_set(children[0])
        except Exception as error:
            self.status.set(str(error))

    def selected_table(self):
        selected = self.schema.selection()
        return self.nodes[selected[0]][0] if selected else ""

    def insert_name(self, event=None):
        selected = self.schema.selection()
        if selected:
            self.editor.insert("insert", quote(self.nodes[selected[0]][1]))
            self.editor.focus_set()
            self.highlight()

    def table_query(self, rule=False):
        table = self.selected_table()
        if not table:
            self.status.set(tr("Select a table."))
            return
        if self.editor.get("1.0", "end-1c").strip() and not messagebox.askyesno(
            tr("SQL editor"), tr("Replace the current SQL?"), parent=self.root
        ):
            return
        if rule:
            names = [col["name"] for col in table_columns(table)]
            if "id" not in names:
                self.status.set(tr("A rule needs an id column. Write SQL that returns an id alias."))
                return
            field = next((name for name in names if name != "id"), None)
            expression = quote(field) if field else 'id AS checked_value'
            sql = f"SELECT id, {expression},\n       CASE WHEN {quote(field or 'id')} IS NULL THEN 1 ELSE 0 END AS dq_check\nFROM {quote(table)};"
        else:
            sql = f"SELECT *\nFROM {quote(table)};"
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", sql)
        self.highlight()
        if not rule:
            self.run()

    def query_text(self):
        try:
            return self.editor.get("sel.first", "sel.last")
        except tk.TclError:
            return self.editor.get("1.0", "end-1c")

    def highlight(self, event=None):
        self.editor.tag_remove("keyword", "1.0", "end")
        for match in re.finditer(r"\b(SELECT|FROM|WHERE|AS|CASE|WHEN|THEN|ELSE|END|IS|NOT|NULL|AND|OR|JOIN|ON|GROUP|BY|ORDER|LIMIT|WITH|DISTINCT|HAVING|LEFT|DESC|ASC)\b",
                                 self.editor.get("1.0", "end-1c"), re.I):
            self.editor.tag_add("keyword", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def run(self, event=None):
        if self.running:
            return "break"
        sql = self.query_text()
        if not sql.strip():
            self.status.set(tr("Write a query first."))
            return "break"
        self.running = True
        self.cancel.clear()
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.results.delete(*self.results.get_children())
        self.status.set(tr("Running query…"))
        database = config["database"]

        def worker():
            try:
                self.messages.put((True, preview_query(sql, self.cancel, database)))
            except Exception as error:
                self.messages.put((False, str(error)))

        threading.Thread(target=worker, daemon=True).start()
        return "break"

    def poll(self):
        if self.closed:
            return
        try:
            ok, result = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.running = False
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            if ok:
                keys = [str(i) for i in range(len(result.columns))]
                self.results.configure(columns=keys)
                for key, name in zip(keys, result.columns):
                    self.results.heading(key, text=name)
                    self.results.column(key, width=160, minwidth=60, stretch=False)
                for row in result.rows:
                    self.results.insert("", "end", values=["NULL" if v is None else str(v)[:2000] for v in row])
                self.status.set(tr("{count} rows · {seconds:.2f} s", count=len(result.rows), seconds=result.seconds)
                                + (" · " + tr("First 500 rows; narrow your query to see more.") if result.truncated else ""))
            else:
                self.status.set(result)
        self.poll_id = self.root.after(100, self.poll)

    def create_rule(self):
        sql = self.query_text()
        if not sql.strip():
            self.status.set(tr("Write a query first."))
            return
        from ui.data_quality import DataQualityWindow

        window = tk.Toplevel(self.root)
        library = DataQualityWindow(window, self.username, self.role, self.root, self.time_var)
        library.rule_form(initial_sql=sql, initial_table=self.selected_table())

    def go_back(self):
        self.closed = True
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
        self.dashboard_root.deiconify()
