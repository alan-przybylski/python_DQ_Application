"""One library for local rules and Databricks definitions, separate from SQL editing."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from config.i18n import tr
from logic.cloud_rule_library import list_library_rules
from logic.databricks_profiles import load_profiles
from ui.common import header, footer, table_view, error_box
from ui.utils import place_window
from ui.data_quality import DataQualityWindow


class RuleLibraryWindow(DataQualityWindow):
    def __init__(self, root, username, role, parent, time_var, initial_profile=None):
        self.root, self.username, self.role, self.parent, self.time_var = root, username, role, parent, time_var
        self.cancel, self.events = threading.Event(), queue.Queue()
        self.busy, self.closed = False, False
        self.rules = []
        place_window(root, 1200, 800)
        root.title('DQ Studio / ' + tr('Rule library'))
        header(root, 'Rule library', username)
        footer(root, self.close, time_var)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.dq_refresh_menu = self.refresh
        profiles = load_profiles()
        self.profile = tk.StringVar(value=initial_profile or tr('All profiles'))
        bar = tk.Frame(root)
        bar.pack(fill='x', padx=20, pady=10)
        tk.Label(bar, text=tr('Environment')).pack(side='left', padx=(0, 8))
        self.environment_choice = tk.StringVar(value=tr('All environments'))
        self.environment_picker = ttk.Combobox(bar, textvariable=self.environment_choice,
            values=[tr('All environments'), 'Databricks', 'Local'], state='readonly', width=22)
        self.environment_picker.pack(side='left', padx=(0, 16))
        self.environment_picker.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        tk.Label(bar, text=tr('Connection profile')).pack(side='left', padx=(0, 8))
        self.picker = ttk.Combobox(bar, textvariable=self.profile, values=[tr('All profiles'), *profiles['profiles']], state='readonly', width=28)
        self.picker.pack(side='left')
        self.picker.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        self.buttons = []
        actions = [('Open SQL', self.open_sql), ('Run checks', self.run_rule), ('Refresh', self.refresh)]
        if role in ('superuser', 'admin'):
            actions = [('New local rule', self.new_local_rule), ('New cloud rule', self.new_rule), ('Edit rule', self.edit_rule), *actions]
        toolbar = tk.Frame(root)
        toolbar.pack(fill='x', padx=20, pady=(0, 8))
        for label, command in actions:
            button = tk.Button(toolbar, text=tr(label), command=command)
            button.pack(side='left', padx=(0, 6))
            self.buttons.append(button)
        frame, self.tree = table_view(root, [('id', 'Rule', 55), ('environment', 'Environment', 100), ('description', 'Description', 300),
            ('publication', 'Publication', 150), ('active', 'Status', 85), ('version', 'Version', 65),
            ('source', 'Source table', 250), ('kind', 'Definition type', 170)], 7)
        frame.pack(fill='both', expand=True, padx=20)
        self.tree.bind('<<TreeviewSelect>>', self.show_definition)
        self.tree.bind('<Double-1>', lambda event: self.open_sql())
        tk.Label(root, text=tr('Saved SQL definition (read-only)'), anchor='w').pack(fill='x', padx=20, pady=(8, 2))
        self.definition = tk.Text(root, height=6, wrap='none', font=('Consolas', 10), state='disabled')
        self.definition.pack(fill='both', expand=True, padx=20)
        self.status = tk.StringVar()
        tk.Label(root, textvariable=self.status, wraplength=1100, anchor='w', justify='left').pack(fill='x', padx=20, pady=10)
        if role in ('superuser', 'admin'):
            files = tk.Frame(root)
            files.pack(fill='x', padx=20)
            for label, command in [('Import local rule files', self.import_rule_files), ('Export local rule files', self.export_rule_files)]:
                button = tk.Button(files, text=tr(label), command=command)
                button.pack(side='left', padx=(0, 8))
                self.buttons.append(button)
        self.refresh()
        self.poll_id = root.after(100, self.poll)

    def refresh(self):
        if self.busy:
            return
        try:
            selected = self.tree.selection()
            environment = {'Databricks': 'databricks', 'Local': 'local'}.get(self.environment_choice.get())
            if environment == 'local':
                self.profile.set(tr('All profiles'))
            self.picker.configure(state='disabled' if environment == 'local' else 'readonly')
            profile = None if self.profile.get() == tr('All profiles') else self.profile.get()
            self.rules = list_library_rules(environment, profile)
            self.tree.delete(*self.tree.get_children())
            for rule in self.rules:
                self.tree.insert('', 'end', iid=str(rule['id']), values=(rule['id'], 'Databricks' if rule['environment'] == 'databricks' else 'Local', rule['display_description'],
                    tr(rule['publication_state']), tr('Active') if rule['display_active'] else tr('Inactive'),
                    rule['display_version'], rule['cloud_table'], tr('Linked local rule') if rule['environment'] == 'databricks' and rule['sql_engine'] != 'databricks' else 'Databricks SQL' if rule['environment'] == 'databricks' else 'SQLite'))
            if selected and self.tree.exists(selected[0]):
                self.tree.selection_set(selected[0])
            self.show_definition()
            self.status.set(tr('{count} rules. Filter by Local or Databricks, then select a rule.', count=len(self.rules)))
        except Exception as error:
            error_box(error, self.root)

    def selected_rule(self):
        selected = self.tree.selection()
        if not selected:
            raise ValueError(tr('Select a rule.'))
        return next(rule for rule in self.rules if str(rule['id']) == selected[0])

    def show_definition(self, event=None):
        self.definition.configure(state='normal')
        self.definition.delete('1.0', 'end')
        if self.tree.selection():
            self.definition.insert('1.0', self.selected_rule()['display_sql'])
        self.definition.configure(state='disabled')

    def open_editor(self, rule_id=None, profile=None):
        from ui.databricks_workspace import DatabricksWorkspace
        window = tk.Toplevel(self.root)
        try:
            editor = DatabricksWorkspace(window, self.username, self.role, self.root, self.time_var,
                                         initial_profile=profile or (self.profile.get() if self.profile.get() != tr('All profiles') else None), initial_rule=rule_id)
            self.root.withdraw()
            return editor
        except Exception as error:
            window.destroy()
            error_box(error, self.root)

    def new_rule(self):
        return self.open_editor()

    def new_local_rule(self):
        self.rule_form()

    def load_rules(self):
        self.refresh()

    def open_sql(self):
        try:
            rule = self.selected_rule()
            if rule['environment'] == 'databricks':
                return self.open_editor(rule['id'], rule['profile'])
            from ui.sql_workspace import SqlWorkspace
            window = tk.Toplevel(self.root)
            editor = SqlWorkspace(window, self.username, self.role, self.root, self.time_var)
            editor.editor.insert('1.0', rule['sql_query'])
            editor.highlight()
            self.root.withdraw()
            return editor
        except Exception as error:
            error_box(error, self.root)

    def edit_rule(self):
        try:
            rule = self.selected_rule()
            if rule['sql_engine'] == 'databricks':
                return self.open_editor(rule['id'], rule['profile'])
            from ui.rule_details import RuleDetailsWindow
            return RuleDetailsWindow(tk.Toplevel(self.root), rule['id'], self)
        except Exception as error:
            error_box(error, self.root)

    def run_rule(self):
        if self.busy:
            return
        try:
            rule = self.selected_rule()
            if not rule['display_active']:
                raise ValueError(tr('No active rules'))
            if rule['environment'] == 'databricks' and not rule.get('base_revision'):
                raise ValueError(tr('Publish the rule before running it in Databricks.'))
        except Exception as error:
            error_box(error, self.root)
            return
        profile = rule.get('profile')
        self.busy = True
        self.cancel.clear()
        for button in self.buttons: button.configure(state='disabled')
        self.picker.configure(state='disabled')
        self.environment_picker.configure(state='disabled')
        self.status.set(tr('Running query…'))
        def worker():
            from logic.databricks_manual import run_remote_checks
            try:
                if rule['environment'] == 'databricks':
                    count = run_remote_checks(self.username, rule['link_id'], cancel=self.cancel, profile=profile)
                    message = tr('Completed {count} checks.', count=count)
                else:
                    from logic.dq_engine import run_checks, run_details
                    run_id = run_checks(rule['target_table'], self.username, rule_id=rule['id'])
                    run = run_details(run_id)
                    message = tr('Run #{run}: {status} · {count} completed checks', run=run_id, status=tr(run['status']), count=run['rules_completed'])
                self.events.put((True, message))
            except Exception as error:
                self.events.put((False, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed: return
        try:
            ok, result = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons: button.configure(state='normal')
            self.picker.configure(state='readonly')
            self.environment_picker.configure(state='readonly')
            self.refresh()
            self.status.set(result)
        self.poll_id = self.root.after(100, self.poll)

    def close(self):
        self.closed = True
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
        self.parent.deiconify()
