import tkinter as tk
from tkinter import messagebox
from logic.login_functions import login_user
from ui.dashboard_window import DashboardWindow
from ui.utils import place_window
from ui.theme import MUTED, NAVY, SURFACE

class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("DQ Studio / Sign in")
        place_window(self.root)

        header = tk.Frame(root, background=NAVY)
        header.pack(fill="x")
        tk.Label(header, text="DQ / STUDIO", background=NAVY, foreground=SURFACE,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=36, pady=(24, 4))
        tk.Label(header, text="Make data quality visible.", background=NAVY, foreground=SURFACE,
                 font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=36, pady=(0, 10))
        tk.Label(header, text="IMPORT CSV   /   VALIDATE WITH SQL   /   TRACK RESULTS", background=NAVY,
                 foreground="#9CB8CF", font=("Segoe UI", 10)).pack(anchor="w", padx=36, pady=(0, 26))
        form = tk.Frame(root)
        form.pack(expand=True, padx=24, pady=24)
        tk.Label(form, text="Welcome back", font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(form, text="Sign in to your local workspace.", foreground=MUTED).pack(anchor="w", pady=(0, 20))
        tk.Label(form, text="Username:").pack(anchor="w", pady=(0, 6))
        self.username_entry = tk.Entry(form, width=36)
        self.username_entry.pack(fill="x")

        tk.Label(form, text="Password:").pack(anchor="w", pady=(16, 6))
        self.password_entry = tk.Entry(form, show="*", width=36)
        self.password_entry.pack(fill="x")

        tk.Button(form, text="Sign in  →", command=self.validate_login).pack(fill="x", pady=(24, 0))

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x")

        # EXIT pozycja
        tk.Button(bottom_frame, text="EXIT", command=self.exit_program_login).pack(side="left", padx=10, pady=5)
        tk.Label(bottom_frame, text="LOCAL SQLITE  •  DESKTOP WORKSPACE", foreground=MUTED,
                 font=("Segoe UI", 9)).pack(side="right", padx=20, pady=12)

    def validate_login(self):
        user = self.username_entry.get()
        pwd = self.password_entry.get()

        logged_user, role, error = login_user(user, pwd)

        if error:
            messagebox.showerror("Login Failed", error)
            return

        messagebox.showinfo("Success", f"Logged in as: {logged_user}")

        # Usunięcie okna logowania
        for widget in self.root.winfo_children():
            widget.destroy()

        # Przejście do głównego okna
        DashboardWindow(self.root, logged_user, role)

    def exit_program_login(self):
        self.root.destroy()
