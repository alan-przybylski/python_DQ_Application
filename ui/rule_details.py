"""One rule, three views: current definition, recorded results, immutable versions."""

import difflib
import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr
from logic.accounts import normalize_role
from logic.rule_library import rule_details
from logic.rules import archive_rule
from logic.rule_deletion import delete_rule
from ui.common import header, footer, table_view, error_box
from ui.utils import place_window


def readonly_text(parent, content="", height=8, expand=True):
    frame = tk.Frame(parent)
    frame.pack(fill="both" if expand else "x", expand=expand, pady=6)
    scroll = ttk.Scrollbar(frame)
    scroll.pack(side="right", fill="y")
    text = tk.Text(
        frame,
        height=height,
        wrap="word",
        font=("Consolas", 10),
        yscrollcommand=scroll.set,
    )
    text.pack(fill="both", expand=True)
    scroll.configure(command=text.yview)
    text.insert("1.0", content)
    text.configure(state="disabled")
    return text


class RuleDetailsWindow:
    def __init__(self, root, rule_id, library):
        self.root, self.rule_id, self.library = root, rule_id, library
        self.data = rule_details(rule_id)
        place_window(root)
        root.transient(library.root)
        root.title("DQ Studio / " + tr("Rule #{rule}", rule=rule_id))
        header(root, "Rule details", f"#{rule_id}")
        footer(root, self.close)
        root.protocol("WM_DELETE_WINDOW", self.close)
        current = self.data["current"]
        title = " ".join((current["description"] or "—").split())
        tk.Label(
            root,
            text=title[:120] + ("…" if len(title) > 120 else ""),
            font=("Segoe UI", 15, "bold"),
            wraplength=1020,
            anchor="w",
        ).pack(fill="x", padx=24, pady=(10, 4))
        tk.Label(
            root,
            text=f"{current['target_table']}  ·  {tr('Version')} {current['version']}  ·  {tr('Severity')}: {current['severity'].title()}  ·  {tr('Active rule') if current['status'] == 'ACTIVE' else tr('Inactive rule')}",
            anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 8))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=8)
        self.pages = []
        for label in ("Definition", "Results", "Version history"):
            page = tk.Frame(self.notebook, padx=12, pady=8)
            self.notebook.add(page, text=tr(label))
            self.pages.append(page)
        self.definition(self.pages[0], current)
        self.results(self.pages[1])
        self.history(self.pages[2])

    def definition(self, page, current):
        metadata = f"{tr('Description')}: {current['description'] or '—'}\n{tr('Rule type')}: {current['rule_type']}\n{tr('Error message')}: {current['error_message'] or '—'}"
        readonly_text(page, metadata, height=3, expand=False)
        tk.Label(page, text=tr("SQL query") + "  ·  dq_check: 0 = PASS, 1 = FAIL", anchor="w").pack(fill="x")
        sql = current['sql_query'] or ''
        if current.get('execution_mode') == 'databricks':
            from logic.databricks_sync import mappings
            link = next((row for row in mappings() if row['rule_id']==self.rule_id),None)
            if link:
                sql = '-- Databricks SQL template\n'+link['remote_sql']
        readonly_text(page, sql)
        if current.get('execution_mode') == 'databricks':
            tk.Label(page,text=tr('Changes to mapped rules take effect in Databricks only after publishing.'),wraplength=950,anchor='w').pack(fill='x')
        actions = tk.Frame(page)
        actions.pack(fill="x", pady=4)
        active = current["status"] == "ACTIVE"
        tk.Button(
            actions,
            text=tr("Deactivate rule"),
            state="normal" if active else "disabled",
            command=self.deactivate,
        ).pack(side="left")
        tk.Button(
            actions,
            text=tr("Modify rule"),
            state="disabled" if active else "normal",
            command=self.modify,
        ).pack(side="left", padx=12)
        if normalize_role(self.library.role) == "superuser":
            tk.Button(
                actions,
                text=tr("Delete rule permanently"),
                background="#A32836",
                activebackground="#7E1D29",
                command=self.delete,
            ).pack(side="right")
        tk.Label(
            page,
            text=tr(
                "Deactivate before editing. Saving an edited rule creates its next active version."
            ),
            anchor="w",
            wraplength=980,
        ).pack(fill="x", pady=4)

    def results(self, page):
        result = self.data["result"]
        if not result:
            tk.Label(
                page,
                text=tr(
                    "This version has no recorded results. Older versions are not substituted."
                ),
                wraplength=950,
            ).pack(anchor="w", pady=12)
            return
        passed, failed = result["passed_count"] or 0, result["failed_count"] or 0
        total = passed + failed
        kpi = f"{100 * passed / total:.1f}%" if total else tr("No checked rows")
        tk.Label(
            page,
            text=tr(
                "Last recorded result: {date} · KPI {kpi} · Passed {passed} · Failed {failed}",
                date=result["timestamp"],
                kpi=kpi,
                passed=passed,
                failed=failed,
            ),
            wraplength=980,
            anchor="w",
        ).pack(fill="x", pady=8)
        if result["run_id"] is None:
            tk.Label(
                page,
                text=tr(
                    "Legacy result without a run ID: error records cannot be linked reliably."
                ),
                wraplength=980,
            ).pack(anchor="w", pady=8)
            return
        tk.Label(
            page,
            text=tr(
                "Run #{run}. Up to 500 failed records shown; use Quality report for complete export.",
                run=result["run_id"],
            ),
            wraplength=980,
            anchor="w",
        ).pack(fill="x", pady=4)
        frame, self.error_tree = table_view(
            page,
            [
                ("record_id", "Record ID", 110),
                ("field_name", "Field", 160),
                ("field_value", "Value", 230),
                ("error_message", "Error message", 420),
            ],
            6,
        )
        frame.pack(fill="both", expand=True, pady=6)
        for error in self.data["errors"]:
            self.error_tree.insert("", "end", values=tuple(error.values()))

    def history(self, page):
        bar = tk.Frame(page)
        bar.pack(fill="x", pady=4)
        tk.Label(bar, text=tr("Version")).pack(side="left", padx=(0, 8))
        versions = self.data["versions"]
        labels = [
            f"{v['version']} · {tr('Current version') if v['current'] else tr('Archived version')} · {v['event_time'] or '—'}"
            for v in versions
        ]
        self.version_picker = ttk.Combobox(
            bar, values=labels, state="readonly", width=60
        )
        self.version_picker.pack(side="left")
        self.version_picker.current(0)
        self.version_picker.bind("<<ComboboxSelected>>", self.show_version)
        self.compare = tk.BooleanVar(value=False)
        tk.Checkbutton(
            page,
            text=tr("Compare selected SQL with current version"),
            variable=self.compare,
            command=self.show_version,
        ).pack(anchor="w", pady=4)
        self.version_meta = readonly_text(page, height=3, expand=False)
        self.version_text = readonly_text(page)
        self.version_text.tag_configure(
            "removed", background="#FFE4E4", foreground="#8F2525"
        )
        self.version_text.tag_configure(
            "added", background="#DEF3E6", foreground="#185B37"
        )
        self.show_version()

    def show_version(self, event=None):
        selected = self.data["versions"][self.version_picker.current()]
        self.version_meta.configure(state="normal")
        self.version_meta.delete("1.0", "end")
        self.version_meta.insert(
            "1.0",
            f"{selected['description'] or '—'}\n{tr('Table')}: {selected['target_table']} · {tr('Rule type')}: {selected['rule_type']} · {tr('Severity')}: {selected.get('severity', 'medium').title()}\n{tr('Error message')}: {selected.get('error_message') or '—'}",
        )
        self.version_meta.configure(state="disabled")
        old = selected.get("sql_query")
        current = self.data["current"]["sql_query"] or ""
        self.version_text.configure(state="normal")
        self.version_text.delete("1.0", "end")
        if old is None:
            self.version_text.insert(
                "end", tr("SQL was not stored for this historical version.")
            )
        elif self.compare.get():
            lines = list(
                difflib.unified_diff(
                    old.splitlines(),
                    current.splitlines(),
                    fromfile=str(selected["version"]),
                    tofile=str(self.data["current"]["version"]),
                    lineterm="",
                )
            )
            if not lines:
                self.version_text.insert(
                    "end", tr("SQL is identical to the current version.")
                )
            for line in lines:
                tag = (
                    "added"
                    if line.startswith("+")
                    else "removed"
                    if line.startswith("-")
                    else ""
                )
                self.version_text.insert("end", line + "\n", (tag,) if tag else ())
        else:
            self.version_text.insert("end", old)
        self.version_text.configure(state="disabled")

    def deactivate(self):
        if not messagebox.askyesno(
            tr("Confirm"),
            tr(
                "Deactivate rule #{rule}? Its history and results will remain.",
                rule=self.rule_id,
            ),
            parent=self.root,
        ):
            return
        try:
            archive_rule(self.rule_id, self.library.username)
            self.close()
        except Exception as error:
            error_box(error, self.root)

    def modify(self):
        try:
            self.library.rule_form(self.rule_id)
            self.close()
        except Exception as error:
            error_box(error, self.root)

    def close(self):
        self.root.destroy()
        self.library.load_rules()

    def delete(self):
        current = self.data["current"]
        if not messagebox.askyesno(
            tr("Confirm permanent deletion"),
            tr(
                "Permanently delete rule #{rule}: {description}?\n\nThis removes ALL its versions, KPI, results and execution errors. Runs containing only this rule are removed; shared runs retain other rules' results and their totals are updated.\n\nThis cannot be undone in the app. Existing exported files and backups are not removed.",
                rule=self.rule_id,
                description=current["description"] or "—",
            ),
            parent=self.root,
            icon="warning",
            default="no",
        ):
            return
        try:
            delete_rule(self.rule_id, self.library.username, current["version"])
            self.close()
            messagebox.showinfo(
                tr("Success"),
                tr("Rule and its history permanently deleted."),
                parent=self.library.root,
            )
        except Exception as error:
            error_box(
                error, self.root if self.root.winfo_exists() else self.library.root
            )
