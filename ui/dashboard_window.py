import tkinter as tk
import time

from config.i18n import tr
from logic.accounts import normalize_role
from ui.common import error_box
from ui.theme import NAVY, SURFACE
from ui.utils import place_window


class DashboardWindow:
    def __init__(self, root, username, role):
        self.root, self.username, self.role = root, username, normalize_role(role)
        root.dq_sign_out = self.logout_user
        root.dq_refresh_menu = self.render
        self.time_var = tk.StringVar(master=root)
        self.sync_status = tk.StringVar(master=root)
        self.clock_id = None
        self.render()
        self.update_time()
        root.protocol("WM_DELETE_WINDOW", self.exit_program)
        from ui.databricks_sync_window import startup_sync
        self.sync_cancel = startup_sync(root, username, self.sync_status)

    def render(self):
        root, username = self.root, self.username
        for widget in root.winfo_children():
            widget.destroy()
        place_window(root)
        root.title("DQ Studio / " + tr("Main menu"))
        banner = tk.Frame(root, background=NAVY)
        banner.pack(fill="x")
        tk.Label(
            banner,
            text="DQ / STUDIO",
            background=NAVY,
            foreground="#96C8CB",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=36, pady=(22, 8))
        tk.Label(
            banner,
            text=tr("Your data. A clearer picture."),
            background=NAVY,
            foreground=SURFACE,
            font=("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=36)
        tk.Label(
            banner,
            text=f"{username} / {self.role}",
            background=NAVY,
            foreground="#B2C4D5",
        ).pack(anchor="w", padx=36, pady=(12, 24))
        actions = tk.Frame(root)
        actions.pack(expand=True, padx=24, pady=16)
        choices = [
            ("Databricks", lambda: self.open_environment('databricks')),
            ("Local", lambda: self.open_environment('local')),
            ("Rule library", self.open_dq_panel),
            ("Quality report", self.open_quality_report),
            ("DQ tickets", self.open_tickets),
            ("Settings", self.open_settings),
        ]
        if self.role == "superuser":
            choices.append(("Manage users", self.open_admin_panel))
        self.buttons = {}
        for index, (label, command) in enumerate(choices):
            button = tk.Button(
                actions,
                text=f"{index + 1:02d}   {tr(label)}",
                command=command,
                width=32,
            )
            button.grid(row=index // 2, column=index % 2, sticky='ew', padx=6, pady=4)
            self.buttons[label] = button
        bottom = tk.Frame(root)
        bottom.pack(side="bottom", fill="x")
        tk.Button(bottom, text=tr("Exit"), command=self.exit_program).pack(
            side="left", padx=12, pady=6
        )
        tk.Button(bottom, text=tr("Sign out"), command=self.logout_user).pack(
            side="left", padx=4
        )
        self.clock_label = tk.Label(bottom, textvariable=self.time_var)
        self.clock_label.pack(side="right", padx=16)
        tk.Label(bottom,textvariable=self.sync_status,wraplength=550).pack(side='left',padx=8)

    def update_time(self):
        self.time_var.set(time.strftime("%H:%M:%S"))
        self.clock_id = self.root.after(1000, self.update_time)

    def open_window(self, window_class, **kwargs):
        window = tk.Toplevel(self.root)
        try:
            view = window_class(window, self.username, self.role, self.root, self.time_var, **kwargs)
            self.root.withdraw()
            return view
        except Exception as error:
            window.destroy()
            error_box(error, self.root)

    def open_admin_panel(self):
        from ui.admin_window import AdminWindow

        self.open_window(AdminWindow)

    def open_environment(self, environment):
        from ui.environment_menu import EnvironmentMenu
        return self.open_window(EnvironmentMenu, environment=environment)

    def open_settings(self):
        from ui.settings_window import SettingsWindow
        return self.open_window(SettingsWindow)

    def exit_program(self):
        self.sync_cancel.set()
        if self.clock_id:
            self.root.after_cancel(self.clock_id)
        self.root.destroy()

    def load_csv_and_log(self):
        from ui.import_window import ImportWindow

        self.open_window(ImportWindow)

    def open_export(self):
        from ui.export_window import ExportWindow

        self.open_window(ExportWindow)

    def open_dq_panel(self):
        from ui.rule_library_window import RuleLibraryWindow
        return self.open_window(RuleLibraryWindow)

    def open_sql_editor(self):
        from ui.sql_workspace import SqlWorkspace

        self.open_window(SqlWorkspace)

    def open_file_history(self):
        from ui.file_history import FileHistory

        self.open_window(FileHistory)

    def open_quality_report(self):
        from ui.check_dq_panel import CheckDqPanel

        return self.open_window(CheckDqPanel)

    def open_tickets(self):
        from ui.tickets_window import TicketsWindow

        return self.open_window(TicketsWindow)

    def open_databricks_sync(self):
        from ui.databricks_sync_window import DatabricksSyncWindow

        self.open_window(DatabricksSyncWindow)

    def logout_user(self):
        self.sync_cancel.set()
        if self.clock_id:
            self.root.after_cancel(self.clock_id)
        for widget in self.root.winfo_children():
            widget.destroy()
        from ui.login_window import LoginWindow

        LoginWindow(self.root)
