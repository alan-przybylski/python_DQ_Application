import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from database.connection import get_connection
import time
from ui.check_dq_panel import CheckDqPanel
from ui.utils import place_window

class FileHistory():
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root = root
        self.username = username
        self.role = role
        self.dashboard_root = dashboard_root
        self.time_var = time_var

        self.root.title("DQ Studio / Import history")
        #self.root.geometry("900x800")
        place_window(self.root)

        tk.Label(root, text=f"Logged in as: {username}", anchor="e").pack(fill="x", padx=10, pady=5)

        # Zegar
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x")
        self.clock_label = tk.Label(bottom_frame, textvariable=self.time_var, font=("Helvetica", 10))
        self.clock_label.pack(side="right", padx=10, pady=5)

        tk.Button(bottom_frame, text="BACK", command=self.go_back).pack(side="left", padx=10, pady=5)
        self.root.protocol("WM_DELETE_WINDOW", self.go_back)  # wciśnięcie X w prawym górnym rogu działa jak BACK

        # TREEVIEW FILE HISTORY
        tk.Label(root, text="File Upload History", font=("Helvetica", 12, "bold")).pack(pady=(10, 0))
        self.tree_frame = tk.Frame(root)
        self.tree_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.tree_scroll_y = tk.Scrollbar(self.tree_frame, orient="vertical")
        self.tree_scroll_y.pack(side="right", fill="y")
        self.tree_scroll_x = tk.Scrollbar(self.tree_frame, orient="horizontal")
        self.tree_scroll_x.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(
            self.tree_frame,
            columns=("id", "table_name", "file_name", "row_count", "loaded_by", "loaded_at"),
            yscrollcommand=self.tree_scroll_y.set,
            xscrollcommand=self.tree_scroll_x.set,
            show="headings"
        )
        self.tree.pack(fill="both", expand=True)
        self.tree_scroll_y.config(command=self.tree.yview)
        self.tree_scroll_x.config(command=self.tree.xview)

        # Ustawienia szerokości kolumn
        column_widths = {
            "id": 60,
            "table_name": 150,
            "file_name": 270,
            "row_count": 100,
            "loaded_by": 120,
            "loaded_at": 160
        }

        for col in self.tree["columns"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths[col], anchor=tk.CENTER, stretch=False)

            self.import_data_load_log()


    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def import_data_load_log(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM data_load_log")
            rows = cursor.fetchall()

            self.tree.delete(*self.tree.get_children())

            for row in rows:
                self.tree.insert("", "end", values=row)

        except sqlite3.Error as e:
            messagebox.showerror("Error", f"Database error: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals() and conn is not None:
                conn.close()

    def on_close():
        screen2.withdraw()
        screen.update()
        screen.deiconify()
