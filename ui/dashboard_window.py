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
        place_window(root)
        root.title("DQ Studio / " + tr("Workspace"))
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
            ("Import CSV", self.load_csv_and_log),
            ("Rule library", self.open_dq_panel),
            ("SQL editor", self.open_sql_editor),
            ("Quality report", self.open_quality_report),
            ("DQ tickets", self.open_tickets),
            ("Databricks sync", self.open_databricks_sync),
            ("Export table", self.open_export),
            ("Import history", self.open_file_history),
        ]
        if self.role == "superuser":
            choices.append(("Manage users", self.open_admin_panel))
        for index, (label, command) in enumerate(choices):
            tk.Button(
                actions,
                text=f"{index + 1:02d}   {tr(label)}",
                command=command,
                width=32,
            ).grid(row=index // 2, column=index % 2, sticky='ew', padx=6, pady=4)
        bottom = tk.Frame(root)
        bottom.pack(side="bottom", fill="x")
        tk.Button(bottom, text=tr("Exit"), command=self.exit_program).pack(
            side="left", padx=12, pady=6
        )
        tk.Button(bottom, text=tr("Sign out"), command=self.logout_user).pack(
            side="left", padx=4
        )
        self.time_var = tk.StringVar(master=root)
        self.clock_label = tk.Label(bottom, textvariable=self.time_var)
        self.clock_label.pack(side="right", padx=16)
        self.clock_id = None
        self.update_time()
        root.protocol("WM_DELETE_WINDOW", self.exit_program)
        self.sync_status = tk.StringVar(master=root)
        tk.Label(bottom,textvariable=self.sync_status,wraplength=550).pack(side='left',padx=8)
        from ui.databricks_sync_window import startup_sync

        self.sync_cancel = startup_sync(root,username,self.sync_status)

    def update_time(self):
        self.time_var.set(time.strftime("%H:%M:%S"))
        self.clock_id = self.root.after(1000, self.update_time)

    def open_window(self, window_class):
        window = tk.Toplevel(self.root)
        try:
            window_class(window, self.username, self.role, self.root, self.time_var)
            self.root.withdraw()
        except Exception as error:
            window.destroy()
            error_box(error, self.root)

    def open_admin_panel(self):
        from ui.admin_window import AdminWindow

        self.open_window(AdminWindow)

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
        from ui.data_quality import DataQualityWindow

        self.open_window(DataQualityWindow)

    def open_sql_editor(self):
        from ui.sql_workspace import SqlWorkspace

        self.open_window(SqlWorkspace)

    def open_file_history(self):
        from ui.file_history import FileHistory

        self.open_window(FileHistory)

    def open_quality_report(self):
        from ui.check_dq_panel import CheckDqPanel

        self.open_window(CheckDqPanel)

    def open_tickets(self):
        from ui.tickets_window import TicketsWindow

        self.open_window(TicketsWindow)

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
