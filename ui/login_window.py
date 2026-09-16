import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, language, set_language
from logic.login_functions import login_user
from ui.common import error_box
from ui.theme import MUTED, NAVY, SURFACE
from ui.utils import place_window


class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.render()

    def render(self, username="", password=""):
        self.root.title("DQ Studio / " + tr("Sign in"))
        place_window(self.root)
        banner = tk.Frame(self.root, background=NAVY)
        banner.pack(fill="x")
        tk.Label(
            banner,
            text="DQ / STUDIO",
            background=NAVY,
            foreground=SURFACE,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=36, pady=(24, 5))
        tk.Label(
            banner,
            text=tr("Make data quality visible."),
            background=NAVY,
            foreground=SURFACE,
            font=("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=36)
        tk.Label(
            banner,
            text=tr("Import CSV / SQL rules / Persistent results"),
            background=NAVY,
            foreground="#9CB8CF",
        ).pack(anchor="w", padx=36, pady=(10, 24))
        language_row = tk.Frame(self.root)
        language_row.pack(fill="x", padx=24, pady=8)
        self.language_var = tk.StringVar(value=language())
        selector = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            values=("EN", "PL"),
            state="readonly",
            width=5,
        )
        selector.pack(side="right")
        tk.Label(language_row, text=tr("Language")).pack(side="right", padx=8)
        selector.bind("<<ComboboxSelected>>", self.change_language)
        form = tk.Frame(self.root)
        form.pack(expand=True, padx=24, pady=12)
        tk.Label(form, text=tr("Welcome back"), font=("Segoe UI", 21, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            form, text=tr("Sign in to your local workspace."), foreground=MUTED
        ).pack(anchor="w", pady=(4, 20))
        tk.Label(form, text=tr("Username")).pack(anchor="w")
        self.username_entry = tk.Entry(form, width=36)
        self.username_entry.insert(0, username)
        self.username_entry.pack(fill="x", pady=(6, 12))
        tk.Label(form, text=tr("Password")).pack(anchor="w")
        self.password_entry = tk.Entry(form, show="*", width=36)
        self.password_entry.insert(0, password)
        self.password_entry.pack(fill="x", pady=(6, 12))
        tk.Button(form, text=tr("Sign in"), command=self.validate_login).pack(
            fill="x", pady=8
        )
        self.password_entry.bind("<Return>", lambda event: self.validate_login())
        bottom = tk.Frame(self.root)
        bottom.pack(side="bottom", fill="x")
        tk.Button(bottom, text=tr("Exit"), command=self.exit_program_login).pack(
            side="left", padx=12, pady=6
        )
        tk.Label(bottom, text=tr("Local SQLite workspace"), foreground=MUTED).pack(
            side="right", padx=20
        )

    def change_language(self, event=None):
        username, password = self.username_entry.get(), self.password_entry.get()
        try:
            set_language(self.language_var.get())
        except OSError as error:
            error_box(error, self.root)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.render(username, password)

    def validate_login(self):
        try:
            username, role, error = login_user(
                self.username_entry.get(), self.password_entry.get()
            )
            if error:
                messagebox.showerror(tr("Error"), error, parent=self.root)
                return
        except Exception as error:
            error_box(error, self.root)
            return
        for widget in self.root.winfo_children():
            widget.destroy()
        from ui.dashboard_window import DashboardWindow

        DashboardWindow(self.root, username, role)

    def exit_program_login(self):
        self.root.destroy()
