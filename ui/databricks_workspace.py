"""A distinct cloud SQL editor; no local dataset selection or implicit transfers."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr
from database.connection import get_connection, dict_row_factory
from integrations.databricks_contract import name, revision
from integrations.plain_sql import native_sql
from logic import databricks_workspace as cloud
from logic.databricks_profiles import load_profiles
from ui.common import header, footer, table_view, error_box
from ui.utils import place_window


class DatabricksWorkspace:
    def __init__(self, root, username, role, parent, time_var):
        self.root, self.username, self.role, self.parent, self.time_var = root, username, role, parent, time_var
        self.cancel, self.messages = threading.Event(), queue.Queue()
        self.running, self.closed = False, False
        self.nodes, self.saved = {}, []
        place_window(root, 1200, 800)
        root.title('DQ Studio / Databricks SQL')
        header(root, 'Databricks SQL', username)
        footer(root, self.close, time_var)
        root.protocol('WM_DELETE_WINDOW', self.close)
        bar = tk.Frame(root)
        bar.pack(fill='x', padx=20, pady=8)
        profiles = load_profiles()
        self.profile = tk.StringVar(value=profiles['selected'])
        self.catalog, self.schema = tk.StringVar(), tk.StringVar()
        tk.Label(bar, text=tr('Connection profile')).pack(side='left')
        picker = ttk.Combobox(bar, textvariable=self.profile, values=list(profiles['profiles']), state='readonly', width=22)
        picker.pack(side='left', padx=6)
        picker.bind('<<ComboboxSelected>>', self.profile_changed)
        for caption, variable in [('Catalog', self.catalog), ('Schema', self.schema)]:
            tk.Label(bar, text=tr(caption)).pack(side='left')
            tk.Entry(bar, textvariable=variable, width=18).pack(side='left', padx=6)
        tk.Button(bar, text=tr('Browse cloud tables'), command=self.browse).pack(side='left')
        tk.Label(root, text=tr('Databricks SQL runs in the selected warehouse. Use catalog.schema.table and ordinary JOINs.'), anchor='w').pack(fill='x', padx=20)
        panes = ttk.Panedwindow(root, orient='horizontal')
        panes.pack(fill='both', expand=True, padx=20, pady=8)
        left, right = tk.Frame(panes), tk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=4)
        self.tables = ttk.Treeview(left, show='tree', height=8)
        self.tables.pack(fill='both', expand=True)
        self.tables.bind('<Double-1>', self.insert_table)
        tk.Button(left, text=tr('Preview table'), command=self.preview_table).pack(fill='x')
        tk.Label(left, text=tr('Cloud rule drafts and published rules'), wraplength=220).pack(pady=5)
        self.rule_choice = tk.StringVar()
        self.rules = ttk.Combobox(left, textvariable=self.rule_choice, state='readonly', width=27)
        self.rules.pack(fill='x')
        self.rules.bind('<<ComboboxSelected>>', self.load_rule)
        tk.Button(left, text=tr('Refresh'), command=self.refresh_rules).pack(fill='x')
        self.editor = tk.Text(right, height=9, wrap='none', undo=True, font=('Consolas', 11))
        self.editor.pack(fill='both', expand=True)
        self.editor.bind('<Control-Return>', self.run)
        actions = tk.Frame(right)
        actions.pack(fill='x', pady=6)
        tk.Button(actions, text=tr('Run SQL · Ctrl+Enter'), command=self.run).pack(side='left')
        tk.Button(actions, text=tr('Cancel'), command=self.cancel.set).pack(side='left', padx=4)
        if role in ('superuser', 'admin'):
            tk.Button(actions, text=tr('Save as new cloud rule'), command=self.save_rule).pack(side='left', padx=4)
            tk.Button(actions, text=tr('Publish saved rule'), command=self.publish).pack(side='left', padx=4)
            tk.Button(left, text=tr('Save cloud changes'), command=lambda: self.save_rule(edit=True)).pack(fill='x')
        tk.Label(right, text=tr('Read-only preview · up to 500 rows · query timeout 60 seconds'), anchor='w').pack(fill='x')
        frame, self.results = table_view(right, [], 5)
        frame.pack(fill='both', expand=True)
        controls = tk.Frame(root)
        controls.pack(fill='x', padx=20)
        tk.Button(controls, text=tr('Run selected in Databricks'), command=self.run_rule).pack(side='left')
        tk.Button(controls, text=tr('Download all results'), command=self.download).pack(side='left', padx=6)
        tk.Button(controls, text=tr('Quality report'), command=self.report).pack(side='left')
        self.status = tk.StringVar()
        tk.Label(root, textvariable=self.status, wraplength=1100, anchor='w', justify='left').pack(fill='x', padx=20, pady=8)
        self.profile_changed()
        self.poll_id = root.after(100, self.poll)

    def profile_changed(self, event=None):
        settings = load_profiles()['profiles'].get(self.profile.get(), {})
        self.catalog.set(settings.get('catalog', ''))
        self.schema.set(settings.get('schema', ''))
        self.tables.delete(*self.tables.get_children())
        self.nodes.clear()
        self.refresh_rules()

    def refresh_rules(self):
        c = get_connection()
        c.row_factory = dict_row_factory
        try:
            self.saved = c.execute('''SELECT r.*,l.id AS link_id,l.base_revision FROM dq_rules r
                JOIN dq_remote_links l ON l.rule_id=r.id WHERE r.sql_engine='databricks' AND l.profile=? ORDER BY r.id''', (self.profile.get(),)).fetchall()
        finally:
            c.close()
        from logic.databricks_sync import definition
        labels = []
        for rule in self.saved:
            _, payload = definition(rule['link_id'])
            state = tr('Published') if rule['base_revision'] == revision(payload) else tr('Pending publication') if rule['base_revision'] else tr('Draft')
            labels.append(f"#{rule['id']} · {state} · {tr('Active') if rule['status'] == 'ACTIVE' else tr('Inactive')} · {rule['description']}")
        self.rules.configure(values=labels)
        self.rule_choice.set('')

    def selected_rule(self):
        index = self.rules.current()
        if index < 0:
            raise ValueError(tr('Select a rule.'))
        return self.saved[index]

    def load_rule(self, event=None):
        if self.editor.get('1.0', 'end-1c').strip() and not messagebox.askyesno(tr('SQL editor'), tr('Replace the current SQL?'), parent=self.root):
            return
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', self.selected_rule()['sql_query'])

    def start(self, operation, completed):
        if self.running:
            return
        self.running = True
        self.cancel.clear()
        self.status.set(tr('Running query…'))
        self.disabled_controls = []
        def freeze(widget):
            for child in widget.winfo_children():
                if isinstance(child, (tk.Button, tk.Entry, ttk.Combobox)) and not (isinstance(child, tk.Button) and child.cget('text') == tr('Cancel')):
                    self.disabled_controls.append((child, child.cget('state')))
                    child.configure(state='disabled')
                freeze(child)
        freeze(self.root)
        def worker():
            try:
                self.messages.put((True, operation(), completed))
            except Exception as error:
                self.messages.put((False, str(error), completed))
        threading.Thread(target=worker, daemon=True).start()

    def browse(self):
        profile, catalog, schema = self.profile.get(), self.catalog.get(), self.schema.get()
        def completed(tables):
            if profile != self.profile.get() or catalog != self.catalog.get() or schema != self.schema.get():
                return
            self.tables.delete(*self.tables.get_children())
            self.nodes.clear()
            for table, columns in tables.items():
                item = self.tables.insert('', 'end', text=table)
                self.nodes[item] = name(catalog, schema, table)
                for column, kind in columns:
                    child = self.tables.insert(item, 'end', text=f'{column} · {kind}')
                    self.nodes[child] = name(column)
            self.status.set(f'{profile} / {catalog}.{schema} · {len(tables)}')
        self.start(lambda: cloud.browse(profile, catalog, schema, self.cancel), completed)

    def insert_table(self, event=None):
        selected = self.tables.selection()
        if selected:
            self.editor.insert('insert', self.nodes[selected[0]])

    def preview_table(self):
        selected = self.tables.selection()
        if not selected:
            return
        item = self.tables.parent(selected[0]) or selected[0]
        sql = 'SELECT * FROM ' + self.nodes[item]
        profile = self.profile.get()
        self.start(lambda: cloud.preview_query(profile, sql, self.cancel), self.show_preview)

    def run(self, event=None):
        sql, profile = self.editor.get('1.0', 'end-1c'), self.profile.get()
        self.start(lambda: cloud.preview_query(profile, sql, self.cancel), self.show_preview)
        return 'break'

    def show_preview(self, preview):
        self.results.delete(*self.results.get_children())
        keys = [str(i) for i in range(len(preview.columns))]
        self.results.configure(columns=keys)
        for key, column in zip(keys, preview.columns):
            self.results.heading(key, text=column)
            self.results.column(key, width=160, stretch=False)
        for row in preview.rows:
            self.results.insert('', 'end', values=['NULL' if value is None else str(value)[:2000] for value in row])
        self.status.set(tr('{count} rows · {seconds:.2f} s', count=len(preview.rows), seconds=preview.seconds)
                        + (' · ' + tr('First 500 rows; narrow your query to see more.') if preview.truncated else ''))

    def save_rule(self, edit=False):
        if self.running:
            return
        try:
            sql, deps = native_sql(self.editor.get('1.0', 'end-1c'))
            existing = self.selected_rule() if edit else None
        except Exception as error:
            error_box(error, self.root)
            return
        profile = self.profile.get()
        dialog = tk.Toplevel(self.root)
        dialog.title(tr('Save cloud changes') if edit else tr('Save as new cloud rule'))
        fields = {}
        for caption in ('Description', 'Message'):
            tk.Label(dialog, text=tr(caption)).pack(anchor='w', padx=16)
            fields[caption] = tk.Entry(dialog, width=65)
            fields[caption].pack(fill='x', padx=16, pady=4)
            if existing:
                fields[caption].insert(0, existing['description'] if caption == 'Description' else existing['error_message'] or '')
        tk.Label(dialog, text=tr('Source table')).pack(anchor='w', padx=16)
        sources = list(deps.values())
        source = ttk.Combobox(dialog, values=[name(*parts) for parts in sources], state='readonly', width=62)
        source.pack(padx=16, pady=4)
        source.current(0)
        if existing:
            source.current(next((i for i, parts in enumerate(sources) if name(*parts) == existing['target_table']), 0))
        severity = ttk.Combobox(dialog, values=['low', 'medium', 'high'], state='readonly')
        severity.set(existing['severity'] if existing else 'medium')
        severity.pack(pady=4)
        active = tk.BooleanVar(dialog, value=existing['status'] == 'ACTIVE' if existing else True)
        tk.Checkbutton(dialog, text=tr('Active'), variable=active).pack(pady=4)
        tk.Label(dialog, text=tr('Changes, including deactivation, affect scheduled jobs only after publication.'), wraplength=500).pack(padx=16)
        def save():
            try:
                cloud.save_draft(self.username, profile, sources[source.current()], fields['Description'].get(), sql,
                                 fields['Message'].get(), severity.get(), rule_id=existing['id'] if existing else None, active=active.get())
                dialog.destroy()
                self.refresh_rules()
                self.status.set(tr('Draft saved locally. Select it and publish to include it in cloud jobs.'))
            except Exception as error:
                error_box(error, dialog)
        tk.Button(dialog, text=tr('Save'), command=save).pack(pady=12)

    def publish(self):
        try:
            rule = self.selected_rule()
            if self.editor.get('1.0', 'end-1c').strip() != rule['sql_query'].strip():
                raise ValueError(tr('Editor differs from the saved rule. Save a new rule or load the selected rule before publishing.'))
        except Exception as error:
            error_box(error, self.root)
            return
        def completed(_):
            self.refresh_rules()
            self.status.set(tr('Rule published to Databricks. Scheduled jobs will use this definition.'))
        self.start(lambda: cloud.publish_draft(rule['link_id'], self.username, self.cancel), completed)

    def run_rule(self):
        from logic.databricks_manual import run_remote_checks
        try:
            rule = self.selected_rule()
            if not rule['base_revision']:
                raise ValueError(tr('Publish the rule before running it in Databricks.'))
        except Exception as error:
            error_box(error, self.root)
            return
        self.start(lambda: run_remote_checks(self.username, rule['link_id'], cancel=self.cancel), lambda result: self.status.set(str(result)))

    def download(self):
        from logic.databricks_sync import synchronize
        profile = self.profile.get()
        self.start(lambda: synchronize(self.username, cancel=self.cancel, detailed=True, profile=profile), lambda result: self.status.set(result.message()))

    def report(self):
        from ui.check_dq_panel import CheckDqPanel
        CheckDqPanel(tk.Toplevel(self.root), self.username, self.role, self.root, self.time_var, environment='databricks', profile=self.profile.get())

    def poll(self):
        if self.closed:
            return
        try:
            ok, result, completed = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.running = False
            for control, state in self.disabled_controls:
                if control.winfo_exists():
                    control.configure(state=state)
            if ok:
                try:
                    completed(result)
                except Exception as error:
                    self.status.set(str(error))
            else:
                self.status.set(result)
        self.poll_id = self.root.after(100, self.poll)

    def close(self):
        self.closed = True
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
        self.parent.deiconify()
