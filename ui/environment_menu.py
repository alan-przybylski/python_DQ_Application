"""Environment-specific navigation with explicit transfer destinations."""
import tkinter as tk
from tkinter import ttk
import webbrowser

from config.i18n import tr
from logic.databricks_profiles import load_profiles, select_profile
from logic.databricks_workspace import source_for_profile
from ui.common import header, footer, error_box
from ui.utils import place_window


class EnvironmentMenu:
    def __init__(self, root, username, role, parent, time_var, environment='local', section=None):
        self.root, self.username, self.role = root, username, role
        self.parent, self.time_var, self.environment, self.section = parent, time_var, environment, section
        place_window(root)
        root.dq_refresh_menu = self.render
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.render()

    def render(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        cloud = self.environment == 'databricks'
        title = 'Databricks' if cloud else 'Local / SQLite'
        self.root.title('DQ Studio / ' + title)
        self.profile = tk.StringVar(value=load_profiles()['selected'] if cloud else '')
        self.heading = header(self.root, title, self.username + (' / ' + self.profile.get() if cloud else ''))
        navigation = footer(self.root, self.close, self.time_var)
        if self.section is None:
            for child in navigation.winfo_children():
                if isinstance(child, tk.Button): child.configure(text=tr('Main menu'))
        else:
            tk.Button(navigation, text=tr('Main menu'), command=self.main_menu).pack(side='left')
        if cloud:
            saved = load_profiles()
            self.profile.set(saved['selected'])
            bar = tk.Frame(self.root)
            bar.pack(fill='x', padx=28, pady=14)
            tk.Label(bar, text=tr('Connection profile')).pack(side='left', padx=(0, 8))
            self.picker = ttk.Combobox(bar, textvariable=self.profile, values=list(saved['profiles']), state='readonly', width=32)
            self.picker.pack(side='left')
            self.picker.bind('<<ComboboxSelected>>', self.change_profile)
            tk.Button(bar, text=tr('Settings'), command=self.settings).pack(side='right')
        tk.Label(self.root, text=tr(self.section or ('Cloud data and checks' if cloud else 'Local data and checks')), font=('Segoe UI', 16, 'bold')).pack(pady=12)
        actions = tk.Frame(self.root)
        actions.pack(expand=True, padx=28, pady=12)
        self.buttons = {}
        for index, (label, command) in enumerate(self.choices()):
            button = tk.Button(actions, text=tr(label), command=command, width=38)
            button.grid(row=index // 2, column=index % 2, sticky='ew', padx=6, pady=7)
            self.buttons[label] = button

    def choices(self):
        if self.section == 'Data transfers' and self.environment == 'databricks':
            return [('Send local table to Databricks', self.transfer),
                    ('Create local snapshot from Databricks', self.snapshot),
                    ('Export cloud preview to CSV', lambda: self.editor('tables')),
                    ('Download all results', self.download)]
        if self.section == 'Import / export data':
            return [('Import CSV', self.import_csv), ('Export table', self.export),
                    ('Import history', self.history)]
        return [('Browse tables and columns', lambda: self.editor('tables')),
                ('SQL editor', self.editor), ('Rule library', self.rules),
                ('Runs and schedules' if self.environment == 'databricks' else 'Run checks', self.runs),
                ('Quality report', self.report),
                ('Data transfers' if self.environment == 'databricks' else 'Import / export data', self.transfers)]

    def open_window(self, cls, **kwargs):
        window = tk.Toplevel(self.root)
        try:
            view = cls(window, self.username, self.role, self.root, self.time_var, **kwargs)
            self.root.withdraw()
            return view
        except Exception as error:
            window.destroy()
            error_box(error, self.root)

    def change_profile(self, event=None):
        try:
            select_profile(self.profile.get())
            self.heading.winfo_children()[-1].configure(text=self.username + ' / ' + self.profile.get())
        except Exception as error:
            error_box(error, self.root)

    def settings(self):
        from ui.settings_window import SettingsWindow
        self.open_window(SettingsWindow)

    def editor(self, view='sql'):
        if self.environment == 'databricks':
            from ui.databricks_workspace import DatabricksWorkspace
            return self.open_window(DatabricksWorkspace, initial_profile=self.profile.get(), initial_view=view)
        from ui.sql_workspace import SqlWorkspace
        workspace = self.open_window(SqlWorkspace)
        if workspace and view == 'tables': workspace.schema.focus_set()
        return workspace

    def rules(self):
        if self.environment == 'databricks':
            return self.editor('rules')
        from ui.data_quality import DataQualityWindow
        self.open_window(DataQualityWindow)

    def report(self):
        from ui.check_dq_panel import CheckDqPanel
        return self.open_window(CheckDqPanel, environment=self.environment,
                                profile=(self.profile.get() or None) if self.environment == 'databricks' else None)

    def runs(self):
        if self.environment == 'databricks':
            return self.open_window(CloudRunsWindow, profile=self.profile.get() or None)
        report = self.report()
        if report: report.open_dq_dialog()

    def transfers(self):
        self.open_window(EnvironmentMenu, environment=self.environment,
                         section='Data transfers' if self.environment == 'databricks' else 'Import / export data')

    def transfer(self):
        from ui.cloud_window import CloudWindow
        self.open_window(CloudWindow)

    def snapshot(self):
        from ui.databricks_window import DatabricksWindow
        self.open_window(lambda root, user, role, parent, clock: DatabricksWindow(root, user, parent, lambda: None))

    def download(self):
        workspace = self.editor()
        if workspace: workspace.download()

    def import_csv(self):
        from ui.import_window import ImportWindow
        self.open_window(ImportWindow)

    def export(self):
        from ui.export_window import ExportWindow
        self.open_window(ExportWindow)

    def history(self):
        from ui.file_history import FileHistory
        self.open_window(FileHistory)

    def main_menu(self):
        main = self.parent.master
        self.root.destroy()
        self.parent.destroy()
        if hasattr(main, 'dq_refresh_menu'):
            main.dq_refresh_menu()
        main.deiconify()

    def close(self):
        self.root.destroy()
        if hasattr(self.parent, 'dq_refresh_menu'):
            self.parent.dq_refresh_menu()
        self.parent.deiconify()


from ui.check_dq_panel import CheckDqPanel


class CloudRunsWindow(CheckDqPanel):
    def __init__(self, root, username, role, parent, time_var, profile=None):
        super().__init__(root, username, role, parent, time_var, environment='databricks', profile=profile)
        tk.Button(root, text=tr('Manage schedules in Databricks'), command=self.open_schedules).pack(side='bottom', pady=5)

    def open_schedules(self):
        try:
            source = source_for_profile(self.profile or load_profiles()['selected'])
            webbrowser.open('https://' + source.hostname + '/jobs')
        except Exception as error:
            error_box(error, self.root)
