from tkinter import messagebox
import tkinter as tk
from tkinter import ttk
from logic.login_functions import create_user, change_password, deactivate_user, get_all_users
from ui.utils import place_window

class AdminWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root = root
        self.username = username
        self.role = role
        self.dashboard_root = dashboard_root
        self.time_var = time_var

        # self.window_width = 400
        # self.window_height = 300
        self.root.title("DQ Studio / User management")
        place_window(self.root)
        # self.root.geometry(f"{self.window_width}x{self.window_height}")

        tk.Label(root, text=f"Logged in as: {username}", anchor="e").pack(fill="x", padx=10, pady=10)

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x")
        self.clock_label = tk.Label(bottom_frame, textvariable=self.time_var, font=("Helvetica", 10))
        self.clock_label.pack(side="right", padx=10, pady=5)

        # tk.Button(root, text="Nowy Użytkownik", command=self.add_user).pack(pady=5)
        # tk.Button(root, text="Zmień Hasło", command=self.change_password).pack(pady=5)
        # tk.Button(root, text="Deactivate User", command=self.deactivate_user).pack(pady=5)

        frame = tk.Frame(self.root)
        frame.pack(padx=24, pady=24, expand=True)

        button1 = tk.Button(frame, text="Create user", command=self.add_user)
        button2 = tk.Button(frame, text="Change password", command=self.change_password)
        button3 = tk.Button(frame, text="Deactivate User", command=self.deactivate_user)

        button1.grid(row=0, column=0, sticky="ew", pady=6)
        button2.grid(row=1, column=0, sticky="ew", pady=6)
        button3.grid(row=2, column=0, sticky="ew", pady=6)

        frame.grid_columnconfigure(0, weight=1, minsize=380)

        # POWRÓT
        tk.Button(bottom_frame, text="BACK", command=self.go_back).pack(side="left", padx=10, pady=5)
        self.root.protocol("WM_DELETE_WINDOW", self.go_back)  # wciśnięcie X w prawym górnym rogu działa jak BACK

    def go_back(self):
        self.root.destroy()               # zamykanie panelu admina
        self.dashboard_root.deiconify()   # przywracanie dashboardu

    def add_user(self):
        win = tk.Toplevel(self.root)
        win.title("Add a new user")
        place_window(win)
        win.transient(self.root)

        tk.Label(win, text="Username:").pack(pady=(48, 6))
        username_entry = tk.Entry(win, width=36)
        username_entry.pack()

        tk.Label(win, text="Password:").pack(pady=(16, 6))
        password_entry = tk.Entry(win, show="*", width=36)
        password_entry.pack()

        def submit():
            user = username_entry.get()
            password = password_entry.get()
            try:
                create_user(user, password, role="user")
                messagebox.showinfo("Success", f"User {user} has been created.")
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        tk.Button(win, text="Create user", command=submit).pack(pady=10)
        tk.Button(win, text="BACK", command=win.destroy).pack(side="bottom", anchor="sw", padx=10, pady=5)

    def change_password(self):
        users = get_all_users()

        win = tk.Toplevel(self.root)
        win.title("Change Password")
        place_window(win)
        win.transient(self.root)

        tk.Label(win, text="Select user:").pack(pady=(48, 6))
        selected_user = tk.StringVar()
        combo = ttk.Combobox(win, textvariable=selected_user, values=users, state="readonly", width=34)
        combo.pack(pady=5)
        if users:
            combo.current(0)

        tk.Label(win, text="New password:").pack(pady=5)
        new_password_entry = tk.Entry(win, show="*", width=36)
        new_password_entry.pack(pady=5)

        def submit():
            user = selected_user.get()
            new_password = new_password_entry.get()
            try:
                change_password(user, new_password)
                messagebox.showinfo("Success", f"Password for {user} has been changed successfully. \nAccount status: active")
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        tk.Button(win, text="Change password", command=submit).pack(pady=10)
        tk.Button(win, text="BACK", command=win.destroy).pack(side="bottom", anchor="sw", padx=10, pady=5)

    def deactivate_user(self):
        users = get_all_users()

        win = tk.Toplevel(self.root)
        win.title("Deactivate User")
        place_window(win)
        win.transient(self.root)

        tk.Label(win, text="Select user:", anchor="e").pack(pady=(48, 6))
        selected_user = tk.StringVar()
        combo = ttk.Combobox(win, textvariable=selected_user, values=users, state="readonly", width=34)
        combo.pack(pady=5)
        if users:
            combo.current(0)

        def submit():
            user = selected_user.get()
            try:
                deactivate_user(user)
                messagebox.showinfo("Success", f"The user {user} has been deactivated!")
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        tk.Button(win, text="Deactivate User", command=submit).pack(pady=5)
        tk.Button(win, text="BACK", command=win.destroy).pack(side="bottom", anchor="sw", padx=10, pady=5)
