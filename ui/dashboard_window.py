import tkinter as tk
from tkinter import messagebox, filedialog
from ui.admin_window import AdminWindow
import time
from logic.csv_upload import load_csv_and_log
from ui.data_quality import DataQualityWindow
from ui.file_history import FileHistory
from ui.utils import place_window
from ui.theme import NAVY, SURFACE



class DashboardWindow:
    def __init__(self, root, username, role):
        self.root = root
        self.username = username
        self.role = role

        # self.window_width = 400
        # self.window_height = 300
        # self.root.geometry(f"{self.window_width}x{self.window_height}")
        place_window(self.root)

        self.root.title("DQ Studio / Workspace")



        # Pasek użytkownika
        header = tk.Frame(root, background=NAVY)
        header.pack(fill="x")
        tk.Label(header, text="DQ / STUDIO", background=NAVY, foreground="#96C8CB",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=36, pady=(24, 8))
        tk.Label(header, text="Your data. A clearer picture.", background=NAVY, foreground=SURFACE,
                 font=("Segoe UI", 27, "bold")).pack(anchor="w", padx=36)
        tk.Label(header, text=f"Workspace  /  {username}  /  {role}", background=NAVY,
                 foreground="#B2C4D5").pack(anchor="w", padx=36, pady=(12, 26))

        # Panel Admina tylko dla admina
        # if role == "admin":
        #     tk.Button(root, text="Panel Admina", command=self.open_admin_panel).pack(pady=5)

        frame = tk.Frame(self.root)
        frame.pack(padx=24, pady=24, expand=True)
        frame.grid_columnconfigure(0, minsize=380)
        tk.Label(frame, text="Choose your next step", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 14))

        if role == "admin":
            button1 = tk.Button(frame, text="04   Manage users", command=self.open_admin_panel)
            button1.grid(row=4, column=0, sticky="nsew", pady=(5, 0))

        button2 = tk.Button(frame, text="02   Rules & quality results", command=self.open_dq_panel)
        button3 = tk.Button(frame, text="01   Import a CSV dataset", command=self.load_csv_and_log)
        button4 = tk.Button(frame, text="03   Browse import history", command=self.open_file_history)

        button2.grid(row=2, column=0, sticky="nsew", pady=(0,5))
        button3.grid(row=1, column=0, sticky="nsew", pady=(0,5))
        button4.grid(row=3, column=0, sticky="nsew", pady=(0,5))

        frame.grid_columnconfigure(0, weight=1)

        #BUTTONS
        # tk.Button(root, text="Data Quality", command=self.open_dq_panel).pack(pady=5)
        # tk.Button(root, text="Upload CSV", command=self.load_csv_and_log).pack(pady=5)
        # tk.Button(root, text="File History", command=self.open_file_history).pack(pady=5)

        # ZEGAR + EXIT (Frame bottom)

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side = "bottom", fill="x")

        # EXIT pozycja
        tk.Button(bottom_frame, text="EXIT", command=self.exit_program).pack(side="left", padx=10, pady=5)
        # LOGOUT
        tk.Button(bottom_frame, text="LOGOUT", command=self.logout_user).pack(side="left", padx=15, pady=5)
        self.root.protocol("WM_DELETE_WINDOW", self.logout_user)
        #ZEGAR pozycja
        self.time_var = tk.StringVar()
        # self.clock_frame = tk.Frame(root)
        # self.clock_frame.pack(side="bottom", fill="x")
        self.clock_label = tk.Label(bottom_frame, textvariable=self.time_var, font=("Helvetica", 10))
        self.clock_label.pack(side="right", anchor = "se", padx=10, pady=5)

        self.update_time()

    def update_time(self):
        current_time = time.strftime('%H:%M:%S')
        self.time_var.set(current_time)
        self.root.after(1000, self.update_time)

    def open_admin_panel(self):
        # Ukrywamy dashboard
        self.root.withdraw()

        # Tworzymy nowe okno admina
        admin_window = tk.Toplevel()
        admin_app = AdminWindow(admin_window, self.username, self.role, self.root, self.time_var)

    def exit_program(self):
        self.root.destroy()

    def load_csv_and_log(self):
        file_path = filedialog.askopenfilename(
            title="Choose CSV file",
            filetypes=(("CSV Files", "*.csv"), ("All Files", "*.*"))
        )

        if not file_path:
            messagebox.showerror("Error", "No file was selected")
            return

        # przekazanie wybranego pliku i nazwy tabeli
        log, success = load_csv_and_log(file_path, "customers", self.username)

        if success:
            messagebox.showinfo("CSV Uploaded", log)
        else:
            messagebox.showinfo("CSV Upload Failed", "An error occurred and no data was added to the database.")

    def open_dq_panel(self):
        self.root.withdraw()
        dq_panel = tk.Toplevel()
        dq_app = DataQualityWindow(dq_panel, self.username, self.role, self.root, self.time_var)

    def open_file_history(self):
        self.root.withdraw()
        file_history_window= tk.Toplevel()
        file_history_app = FileHistory(file_history_window, self.username, self.role, self.root, self.time_var)

    def logout_user(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        messagebox.showinfo("Logout", f"Logged out successfully,\nsee you later, {self.username}!")

        from ui.login_window import LoginWindow
        LoginWindow(self.root)
