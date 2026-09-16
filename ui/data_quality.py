import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from database.connection import get_connection
import time
import json
from ui.check_dq_panel import CheckDqPanel
from ui.utils import place_window
import re

class DataQualityWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root = root
        self.username = username
        self.role = role
        self.dashboard_root = dashboard_root
        self.time_var = time_var

        self.root.title("DQ Studio / Rule library")
        #self.root.geometry("1600x800")
        place_window(self.root)

        tk.Label(root, text=f"Logged in as: {username}", anchor="e").pack(fill="x", padx=10, pady=5)

        # Zegar
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x")
        self.clock_label = tk.Label(bottom_frame, textvariable=self.time_var, font=("Helvetica", 10))
        self.clock_label.pack(side="right", padx=10, pady=5)

        tk.Button(bottom_frame, text="BACK", command=self.go_back).pack(side="left", padx=10, pady=5)
        self.root.protocol("WM_DELETE_WINDOW", self.go_back)  # wciśnięcie X w prawym górnym rogu działa jak BACK

        # TOP FRAME - przyciski
        top_frame = tk.Frame(self.root)
        top_frame.pack(side="top", fill="x", padx=10, pady=5)

        #left frame
        left_frame = tk.Frame(top_frame)
        left_frame.pack(side="left", anchor="w", padx=10, pady=5)
        tk.Button(left_frame, text="Add Rule", command=self.add_rule_window).pack(side="left", padx=5)
        tk.Button(left_frame, text="Deactivate Rule", command=self.deactivate_dq_rule).pack(side="left", padx=5)

        #right frame
        right_frame = tk.Frame(top_frame)
        right_frame.pack(side="right", padx=10, pady=5)
        tk.Button(right_frame, text="Check DQ", command=self.check_dq_panel).pack(side="right", padx=15, pady=10)


        # TREEVIEW LIVE RULES
        tk.Label(root, text="Live Rules", font=("Helvetica", 12, "bold")).pack(pady=(10, 0))
        self.tree_frame = tk.Frame(root)
        self.tree_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self.tree_scroll_y = tk.Scrollbar(self.tree_frame, orient="vertical")
        self.tree_scroll_y.pack(side="right", fill="y")
        self.tree_scroll_x = tk.Scrollbar(self.tree_frame, orient="horizontal")
        self.tree_scroll_x.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(
            self.tree_frame,
            columns=("id", "status", "created_at", "activated_at", "version", "description", "rule_type", "target_table", "error_message", "sql_query"),
            height=6,
            yscrollcommand=self.tree_scroll_y.set,
            xscrollcommand=self.tree_scroll_x.set,
            show="headings"
        )
        self.tree.pack(fill="both", expand=True)
        self.tree_scroll_y.config(command=self.tree.yview)
        self.tree_scroll_x.config(command=self.tree.xview)

        live_column_widths = {
            "id": 60,
            "status": 90,
            "created_at": 150,
            "activated_at": 150,
            "version": 80,
            "description": 240,
            "rule_type": 120,
            "target_table": 140,
            "error_message": 240,
            "sql_query": 360,
        }

        for col in self.tree["columns"]:
            self.tree.heading(col, text=col, command=lambda _col=col: self.treeview_sort_column(self.tree, _col, False))
            self.tree.column(col, width=live_column_widths[col], anchor=tk.CENTER, stretch=False)

        self.load_rules()

        middle_frame = tk.Frame(self.root)
        middle_frame.pack(fill="x", padx=10, pady=(8,5))
        tk.Button(middle_frame, text="Modify Rule", command=self.modify_dq_rule).pack(side="left", padx=5)

        # TREEVIEW ARCHIVED RULES
        tk.Label(root, text="Archived Rules", font=("Helvetica", 12, "bold")).pack(pady=(10, 0))
        self.archive_frame = tk.Frame(root)
        self.archive_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self.archive_scroll_y = tk.Scrollbar(self.archive_frame, orient="vertical")
        self.archive_scroll_y.pack(side="right", fill="y")
        self.archive_scroll_x = tk.Scrollbar(self.archive_frame, orient="horizontal")
        self.archive_scroll_x.pack(side="bottom", fill="x")

        self.archive_tree = ttk.Treeview(
            self.archive_frame,
            columns=(#"history_id",
                     "rule_id", "version", "status", "created_at", "description", "rule_type", "target_table", "rule_params", "deactivated_by", "deactivated_at"),
            height=6,
            yscrollcommand=self.archive_scroll_y.set,
            xscrollcommand=self.archive_scroll_x.set,
            show="headings"
        )
        self.archive_tree.pack(fill="both", expand=True)
        self.archive_scroll_y.config(command=self.archive_tree.yview)
        self.archive_scroll_x.config(command=self.archive_tree.xview)

        archive_column_widths = {
            #"history_id": 20,
            "rule_id": 70,
            "version": 80,
            "status": 90,
            "created_at": 150,
            "description": 240,
            "rule_type": 120,
            "target_table": 140,
            "rule_params": 320,
            "deactivated_by": 140,
            "deactivated_at": 150,
        }


        for col in self.archive_tree["columns"]:
            self.archive_tree.heading(col, text=col, command=lambda _col=col: self.treeview_sort_column(self.archive_tree, _col, False))
            self.archive_tree.column(col, width=archive_column_widths[col], anchor=tk.CENTER, stretch=False)

        self.load_archive_rules()

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def load_rules(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, status, created_at, activated_at, version, description, rule_type, target_table, error_message, sql_query FROM dq_rules WHERE status = 'active'")
            rows = cursor.fetchall()

            for row in rows:
                self.tree.insert("", "end", values=row)

        except sqlite3.Error as e:
            messagebox.showerror("Error", f"Database error: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals() and conn is not None:
                conn.close()

#####################################################
    def get_tables(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            all_tables = [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

        excluded = {"dq_rules", "dq_rules_history", "data_load_log", "dq_results", "dq_field_results", "users"}  #TABLICE DO EXCLUDE
        return [t for t in all_tables if t not in excluded]
    def add_rule_window(self):
        win = tk.Toplevel(self.root)
        win.title("Add new DQ Rule")
        place_window(win)
        win.transient(self.root)

        tk.Label(win, text="Description:").pack(pady=(24, 4))
        desc_entry = tk.Entry(win, width=50)
        desc_entry.pack()

        tk.Label(win, text="Rule Type:").pack(pady=(10, 4))
        type_entry = tk.Entry(win, width=50)
        type_entry.pack()

        tk.Label(win, text="Error Message:").pack(pady=(10, 4))
        error_message_entry = tk.Entry(win, width=50)
        error_message_entry.pack()

        ##------------ target
        tk.Label(win, text="Target Table:").pack(pady=(10, 4))
        tables = self.get_tables()  # Dynamiczne pobranie tabel z DB
        target_table = tk.StringVar()

        table_dropdown = ttk.Combobox(win, values=tables, textvariable=target_table, state="readonly", width=48)
        table_dropdown.pack()
        ##------------ target koniec

        if tables:
            table_dropdown.current(0)

        tk.Label(win, text="SQL Query:").pack(pady=(10, 4))
        sql_entry = tk.Text(win, height=5, width=60)
        sql_entry.pack()

        def submit():
            desc = desc_entry.get()
            rule_type = type_entry.get()
            sql_query = sql_entry.get("1.0", "end-1c")
            new_error_message = error_message_entry.get()  # <-- poprawione

            target_table_name = target_table.get()
            if not target_table_name:
                messagebox.showerror("Error", "Select a target table")
                return

            # Serializacja do JSON dla kolumny MySQL JSON
            error_message_json = json.dumps(new_error_message)

            try:
                self.forbidden_commands(sql_query)
            except ValueError as ve:
                messagebox.showerror("Invalid SQL Query", str(ve))
                return

            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO dq_rules (description, rule_type, target_table, error_message, sql_query, version) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (desc, rule_type, target_table_name, error_message_json, sql_query, "1.0")
                )
                conn.commit()

                # Odświeżenie drzewa
                self.tree.delete(*self.tree.get_children())
                self.load_rules()
                win.destroy()

            except sqlite3.Error as e:
                messagebox.showerror("DB Error", str(e))
            finally:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals() and conn is not None:
                    conn.close()

        tk.Button(win, text="Add new DQ Rule", command=submit).pack(pady=10)
        tk.Button(win, text="BACK", command=win.destroy).pack(side="bottom", anchor="sw", padx=10, pady=5)

    def deactivate_dq_rule(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "No rule was selected")
            return

        rule_id = self.tree.item(selected[0], "values")[0]

        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Pobierz aktywnego rula
            cursor.execute("""
                SELECT id, status, version, description, rule_type, target_table, error_message, sql_query, created_at
                FROM dq_rules
                WHERE id=? AND status='ACTIVE'
            """, (rule_id,))
            row = cursor.fetchone()

            if not row:
                messagebox.showinfo("Info", "This rule is already inactive")
                return

            rid, status, version, desc, rule_type, target_table, error_message, sql_query, created_at = row

            # --- wersja do archiwizacji ---
            archived_version = version if version else "1.0"

            # --- JSON rule_params ---
            import json
            rule_params_json = json.dumps({
                "sql_query": sql_query,
                "description": desc,
                "error_message": error_message,
            })

            # --- Archiwizacja ---
            cursor.execute("""
                INSERT INTO dq_rules_history
                (rule_id, version, status, created_at, description, rule_type, target_table, rule_params,
                 deactivated_by, deactivated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                        ?, datetime('now', 'localtime'))
            """, (
                rid, archived_version, "INACTIVE",
                created_at,
                desc,
                rule_type,
                target_table,
                rule_params_json,
                self.username
            ))

            # --- Update rula ---
            cursor.execute("""
                UPDATE dq_rules
                SET status='INACTIVE'
                WHERE id=?
            """, (rid,))

            conn.commit()

            messagebox.showinfo("Info", "Rule has been deactivated and archived")

        except sqlite3.Error as e:
            messagebox.showerror("DB Error", str(e))

        finally:
            cursor.close()
            conn.close()

            # Odśwież oba drzewa
            self.tree.delete(*self.tree.get_children())
            self.load_rules()

            self.archive_tree.delete(*self.archive_tree.get_children())
            self.load_archive_rules()

    def modify_dq_rule(self):
        selected = self.archive_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Select Rule from Archived Rules")
            return

        # Pierwsza kolumna to rule_id w drzewie
        rule_id = self.archive_tree.item(selected[0], "values")[0]

        # Pobierz dane z ARCHIWUM (najnowsza wersja)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT history_id, rule_id, description, rule_type, target_table, rule_params, version
            FROM dq_rules_history
            WHERE rule_id=?
            ORDER BY history_id DESC
            LIMIT 1
        """, (rule_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            messagebox.showerror("Error", "Rule not found in database")
            return

        history_id, rule_id, current_desc, current_type, target_table, rule_params_json, archived_version = row

        # JSON rule_params -> SQL
        params = json.loads(rule_params_json)
        current_sql = params.get("sql_query", "")

        # ---- OKNO MODYFIKACJI ----
        win = tk.Toplevel(self.root)
        win.title("Modify DQ Rule")
        place_window(win)
        win.transient(self.root)

        tk.Label(win, text="Description:").pack(pady=(24, 4))
        desc_entry = tk.Entry(win, width=50)
        desc_entry.insert(0, current_desc)
        desc_entry.pack()

        tk.Label(win, text="Rule Type:").pack(pady=(10, 4))
        type_entry = tk.Entry(win, width=50)
        type_entry.insert(0, current_type)
        type_entry.pack()

        tk.Label(win, text="SQL Query:").pack(pady=(10, 4))
        sql_entry = tk.Text(win, height=5, width=60)
        sql_entry.insert("1.0", current_sql)
        sql_entry.pack()

        params = json.loads(rule_params_json)
        current_error_message = params.get("error_message", "DQ rule failed")

        tk.Label(win, text="Error Message:").pack(pady=(10, 4))
        error_entry = tk.Entry(win, width=50)
        error_entry.insert(0, str(current_error_message))  # <--- tu konwersja do string
        error_entry.pack()

        def save_changes():
            # Pobranie wartości z pól
            new_desc = desc_entry.get()
            new_type = type_entry.get()
            new_sql = sql_entry.get("1.0", "end-1c")
            new_error_message = error_entry.get()
            new_error_message_json = json.dumps(new_error_message)

            try:
                self.forbidden_commands(new_sql)
            except ValueError as ve:
                messagebox.showerror("Error", str(ve))
                return

            try:
                conn = get_connection()
                cursor = conn.cursor()

                # Sprawdzenie, czy reguła nie jest już aktywna
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM dq_rules
                    WHERE id=? AND status='ACTIVE'
                """, (rule_id,))
                active_count = cursor.fetchone()[0]

                if active_count > 0:
                    messagebox.showerror("Error",
                                         f"Rule {rule_id} is already active and cannot be modified from archive.")
                    return

                # Inkrementacja wersji
                major, minor = archived_version.split(".")
                minor = int(minor) + 1
                new_version = f"{major}.{minor}"

                # Aktualizacja live rule w dq_rules
                cursor.execute("""
                    UPDATE dq_rules
                    SET description=?,
                        rule_type=?,
                        sql_query=?,
                        error_message=?,
                        status='ACTIVE',
                        version=?,
                        activated_at=datetime('now', 'localtime')
                    WHERE id=?
                """, (new_desc, new_type, new_sql, new_error_message, new_version, rule_id))

                conn.commit()
                messagebox.showinfo("Info", f"Rule {rule_id} has been updated successfully")

                # Odświeżenie drzewa z live rules
                self.tree.delete(*self.tree.get_children())
                self.load_rules()

                # Zamknięcie okna
                win.destroy()

            except sqlite3.Error as e:
                messagebox.showerror("DB Error", str(e))
            finally:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals() and conn is not None:
                    conn.close()

        tk.Button(win, text="Save changes", command=save_changes).pack(pady=10)
        tk.Button(win, text="BACK", command=win.destroy).pack(side="bottom", anchor="sw", padx=10, pady=5)

    def load_archive_rules(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT rule_id, version, status, created_at, description, rule_type, target_table, rule_params, deactivated_by, deactivated_at
                FROM dq_rules_history
            """)
            rows = cursor.fetchall()

            for row in rows:
                self.archive_tree.insert("", "end", values=row)

        except sqlite3.Error as e:
            messagebox.showerror("Error", f"Database error: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals() and conn is not None:
                conn.close()

    def check_dq_panel(self):
        self.root.withdraw()
        new_window = tk.Toplevel(self.root)
        CheckDqPanel(new_window, self.username, self.role, self.root, self.time_var)

    def treeview_sort_column(self, tree, col, reverse):
        data_list = [(tree.set(k, col), k) for k in tree.get_children('')]
        try:
            data_list.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            data_list.sort(key=lambda t: t[0], reverse=reverse)

        #Przestawiam wiersze
        for index, (val, k) in enumerate(data_list):
            tree.move(k, '', index)

        #Odwracam kolejność z kolejnym kliknięciem
        tree.heading(col, command=lambda: self.treeview_sort_column(tree, col, not reverse))


    ### WALIDACJA SQL QUERY czyli dodanie zakazanych komend

    def forbidden_commands(self, rule_text: str):

        forbidden_keywords = ['DROP', 'DELETE', 'ALTER', 'TRUNCATE', 'INSERT', 'UPDATE', 'CREATE', 'RENAME']
        #allowed_characters_regex = r'^[A-Za-z0-9_ ,\.\(\)]+$'

        rule_upper = rule_text.upper()
        for keyword in forbidden_keywords:
            if keyword in rule_upper:
                raise ValueError(f"Forbidden keyword: {keyword}, you MUST NOT use this!")


            # if not re.match(allowed_characters_regex, rule_text):
            #     raise ValueError(f"Forbidden keyword: {rule_text}, you MUST NOT use this!")
            # return True
