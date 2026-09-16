import tkinter as tk
from tkinter import messagebox, ttk, Scale, HORIZONTAL
import sqlite3
from numpy.ma.extras import row_stack

from database.connection import get_connection, dict_row_factory
from config.paths import EXCELS_DIR
import json
from datetime import datetime
import csv
import os
from ui.utils import place_window
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from logic.dq_report import draw_chart, get_data_from_dq_results

class CheckDqPanel:
    def __init__(self, root, username, role, data_quality_root, time_var):
        self.root = root
        self.username = username
        self.role = role
        self.data_quality_root = data_quality_root
        self.time_var = time_var
        self.rules_dict = {}

        self.root.title("DQ Studio / Quality results")
        #self.root.geometry("800x400")
        place_window(self.root)

        tk.Label(self.root, text=f"Logged in as: {self.username}", anchor="e").pack(fill="x", padx=10, pady=5)
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side="bottom", fill="x")
        self.clock_label = tk.Label(bottom_frame, textvariable=self.time_var, font=("Helvetica", 10))
        self.clock_label.pack(side="right", padx=10, pady=5)
        tk.Button(bottom_frame, text="BACK", command=self.go_back).pack(side="left", padx=10, pady=5)
        self.root.protocol("WM_DELETE_WINDOW", self.go_back)   #wciśnięcie X w prawym górnym rogu działa jak BACK

        top_frame = tk.Frame(self.root)
        top_frame.pack(padx=10, pady=10, fill="x")

        tk.Button(top_frame, text="Run DQ Check", command=self.open_dq_dialog).grid(row=0, column=0, sticky="nsew")
        #tk.Button(top_frame, text="Choose DQ Rule", command=self.get_tables_to_dq_check).grid(row=0, column=1, sticky="nsew")
        #tk.Button(top_frame, text="Deactivate User").grid(row=0, column=2, sticky="nsew")

        for i in range(3):
            top_frame.grid_columnconfigure(i, weight=1)

        #REPORT FRAME
        kpi_frame = tk.Frame(self.root)
        kpi_frame.pack(fill="both", expand=True, padx=16, pady=12)

        #chart_container = tk.Frame(kpi_frame)
        #chart_container.pack(fill="both", expand=True)

        data = get_data_from_dq_results()

        draw_chart(kpi_frame, data)


    def go_back(self):
        self.root.destroy()
        self.data_quality_root.deiconify()

    def get_tables_to_dq_check(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            all_tables = [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

        excluded = {"dq_rules", "dq_rules_history", "data_load_log", "dq_results", "dq_field_results", "users"}
        return [t for t in all_tables if t not in excluded]

    def get_active_rules_for_table(self, table_name):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, description FROM dq_rules WHERE status='ACTIVE' AND target_table=?", (table_name,))
        #rules = [r[0] for r in cursor.fetchall()]  # tylko id
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        if rows:
            return rows
        else:
            return

    def open_dq_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Run DQ Rules")
        place_window(dialog)
        dialog.transient(self.root)
        # POTESTUJ TO BO FAJNIE GDYBY DZIAŁAŁO ! place_window(self.root, width=400, height=300)

        # Dropdown tabel
        available_tables = self.get_tables_to_dq_check()
        self.selected_table = tk.StringVar(value=available_tables[0] if available_tables else "")
        tk.Label(dialog, text="Select table to check:").pack(pady=(40, 6))
        table_dropdown = ttk.Combobox(dialog, values=available_tables, textvariable=self.selected_table, state="readonly", width=40)
        table_dropdown.pack(pady=5)

        # Wybór typu uruchomienia
        tk.Label(dialog, text="Choose run type:").pack(pady=10)
        self.run_type = tk.StringVar(value="single")
        tk.Radiobutton(dialog, text="Single Rule", variable=self.run_type, value="single", command=self.on_run_type_change).pack()
        tk.Radiobutton(dialog, text="All Rules", variable=self.run_type, value="all", command=self.on_run_type_change).pack()

        # Dropdown dla pojedynczej reguły
        tk.Label(dialog, text="Choose single rule").pack(pady=(15,0))
        self.rule_var = tk.IntVar()
        self.rule_dropdown = tk.OptionMenu(dialog, self.rule_var, [])
        self.rule_dropdown.pack(pady=10)

        tk.Button(dialog, text="BACK", command=dialog.destroy).pack(side="bottom", anchor="sw", padx=10, pady=10)

        def update_rules(*args):
            table = self.selected_table.get()
            rules = self.get_active_rules_for_table(table)  # [(id, description), ...]
            menu = self.rule_dropdown["menu"]
            menu.delete(0, "end")
            self.rules_dict.clear()

            if rules:
                first_id, first_desc = rules[0]
                self.rule_var.set(first_id)

                for rule_id, description in rules:
                    self.rules_dict[rule_id] = description
                    menu.add_command(
                        label=f"{rule_id} - {description}",
                        command=lambda rid=rule_id: self.rule_var.set(rid)
                    )
            else:
                self.rule_var.set(0)
                menu.add_command(label="No active rules", command=lambda: self.rule_var.set(0))

        update_rules()
        self.selected_table.trace_add("write", lambda *args: update_rules())

        tk.Button(dialog, text="Run", command=lambda: self.run_dq_from_dialog(dialog)).pack(pady=10)

    def run_dq_from_dialog(self, dialog):
        table = self.selected_table.get()
        run_type = self.run_type.get()
        dialog.destroy()

        if run_type == "all":
            self.run_all_dq_rules(table)
        else:
            rule_id = self.rule_var.get()
            if rule_id == 0:
                messagebox.showerror("Error", "No rule selected.")
                return
            self.run_selected_dq_rule(table, rule_id)

    def run_all_dq_rules(self, table):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.row_factory = dict_row_factory
        all_records_for_csv = []

        try:
            # Pobranie aktywnych reguł
            cursor.execute(
                "SELECT id, sql_query, version, target_table, error_message "
                "FROM dq_rules WHERE status='ACTIVE' AND target_table=?",
                (table,)
            )
            rules = cursor.fetchall()

            if not rules:
                messagebox.showinfo("Info", f"No active rules for table {table}.")
                return

            total_rules = len(rules)
            rules_executed = 0
            results_summary = []

            for rule in rules:
                rule_id = rule['id']
                sql_query = rule['sql_query']
                rule_version = rule['version']
                table = rule['target_table']
                rule_error_message = rule.get('error_message') or "DQ check failed"

                # Wykonanie zapytania SQL reguły
                try:
                    cursor.execute(sql_query)
                    records = cursor.fetchall()
                except sqlite3.Error as e:
                    messagebox.showerror("SQL Error", f"Error executing rule {rule_id}:\n{e}")
                    continue

                if not records:
                    messagebox.showinfo("Info", f"Rule {rule_id} returned no records.")
                    continue

                # Liczymy passed i failed
                failed_count = sum(1 for r in records if r.get('dq_check', 1) == 0)
                passed_count = sum(1 for r in records if r.get('dq_check', 1) == 1)

                # Wstawienie do dq_results
                try:
                    cursor.execute(
                        """
                        INSERT INTO dq_results
                        (rule_id, rule_version, failed_count, passed_count)
                        VALUES (?, ?, ?, ?)
                        """,
                        (rule_id, rule_version, failed_count, passed_count)
                    )
                except sqlite3.Error as e:
                    messagebox.showerror("SQL Error", f"Error inserting DQ results for rule {rule_id}:\n{e}")
                    continue

                # Wstawienie do dq_field_results i przygotowanie rekordów do CSV
                for record in records:
                    record_id = str(record.get('id', 'unknown'))
                    test_result = record.get('dq_check', 1)
                    message = "DQ check passed" if test_result == 1 else rule_error_message

                    checked_field_name = list(record.keys())[1]
                    field_value = record.get(checked_field_name, "")

                    try:
                        cursor.execute(
                            """
                            INSERT INTO dq_field_results
                            (rule_id, rule_version, record_id, field_name, field_value, test_result, error_message, target_table)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (
                                rule_id,
                                rule_version,
                                record_id,
                                checked_field_name,
                                str(field_value) if field_value is not None else "",
                                test_result,
                                message,
                                table
                            )
                        )
                    except sqlite3.Error as e:
                        messagebox.showerror(
                            "SQL Error",
                            f"Error inserting field result for rule {rule_id}, record {record_id}:\n{e}"
                        )

                    # Dodajemy do listy rekordów do CSV
                    record_for_csv = {
                        'rule_id': rule_id,
                        'record_id': record_id,
                        'checked_field': checked_field_name,
                        'field_value': field_value,
                        'test_result': test_result,
                        'error_message': message
                    }
                    all_records_for_csv.append(record_for_csv)

                conn.commit()
                rules_executed += 1
                results_summary.append(f"Rule {rule_id}: Passed {passed_count}, Failed {failed_count}")

            # Podsumowanie
            overall_status = "SUCCESS" if all("Passed" in r for r in results_summary) else "CHECK FAILED"
            messagebox.showinfo(
                "DQ Check Summary",
                f"Rules executed: {rules_executed}/{total_rules}\n"
                f"Total rows in CSV: {len(all_records_for_csv)}\n\n" +
                "\n".join(results_summary) +
                f"\n\nOverall Status: {overall_status}"
            )

            # Tworzenie CSV dla wszystkich reguł

            if all_records_for_csv:
                folder_path = os.path.dirname(EXCELS_DIR)
                excels = os.path.join(folder_path, "excels")
                csv_file = os.path.join(excels, "all_dq_rules_result.csv")
                fieldnames = ['rule_id', 'record_id', 'checked_field', 'field_value', 'test_result', 'error_message']
                #folder_path = os.path.dirname(csv_file)

                try:
                    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        for record in all_records_for_csv:
                            writer.writerow(record)
                    messagebox.showinfo("Export Complete",
                                        f"All rules - {len(all_records_for_csv)} records exported to CSV.")
                    #os.startfile(folder_path)
                    os.startfile(excels)

                except Exception as e:
                    messagebox.showerror("CSV Error", f"Error exporting CSV:\n{e}")

        finally:
            cursor.close()
            conn.close()

    def run_selected_dq_rule(self, table, rule_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.row_factory = dict_row_factory

        try:
            cursor.execute(
                "SELECT sql_query, version, target_table, error_message FROM dq_rules WHERE id=? AND status='ACTIVE'",
                (rule_id,)
            )
            row = cursor.fetchone()
            if not row:
                messagebox.showerror("Error", f"Rule {rule_id} not found or inactive.")
                return

            sql_query = row['sql_query']
            rule_version = row['version']
            rule_error_message = row.get('error_message') or "DQ check failed"

            # Wykonanie zapytania SQL reguły
            try:
                cursor.execute(sql_query)
                records = cursor.fetchall()
            except sqlite3.Error as e:
                messagebox.showerror("SQL Error", f"Error executing rule {rule_id}:\n{e}")
                return

            if not records:
                messagebox.showinfo("Info", f"Rule {rule_id} returned no records.")
                return

            failed_count = sum(1 for r in records if r.get('dq_check', 1) == 0)
            passed_count = sum(1 for r in records if r.get('dq_check', 1) == 1)

            # WSTAWIENIE DO dq_results
            try:
                cursor.execute(
                    """
                    INSERT INTO dq_results
                    (rule_id, rule_version, failed_count, passed_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (rule_id, rule_version, failed_count, passed_count)
                )
            except sqlite3.Error as e:
                messagebox.showerror("SQL Error", f"Error inserting DQ results for rule {rule_id}:\n{e}")

            #WSTAWIENIE DO dq_field_results
            for record in records:
                record_id = str(record.get('id', 'unknown'))
                test_result = record.get('dq_check', 1)
                message = "DQ check passed" if test_result == 1 else rule_error_message

                #Wybieram tylko drugą kolumnę SELECTa
                checked_field = list(record.keys())[1]
                field_value = record.get(checked_field, "")

                try:
                    cursor.execute(
                        """
                        INSERT INTO dq_field_results
                        (rule_id, rule_version, record_id, field_name, field_value, test_result, error_message, target_table)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            rule_id,
                            rule_version,
                            record_id,
                            checked_field,
                            str(field_value) if field_value is not None else "",
                            test_result,
                            message,
                            table
                        )
                    )
                except sqlite3.Error as e:
                    messagebox.showerror(
                        "SQL Error",
                        f"Error inserting field result for rule {rule_id}, record {record_id}:\n{e}"
                    )

            conn.commit()
            messagebox.showinfo("DQ Result",
                                f"Rule {rule_id} executed.\nPassed: {passed_count}, Failed: {failed_count}")

            #CSV generate function
            for record in records:
                test_result = record.get('dq_check', 1)
                record['error_message'] = "DQ check passed" if test_result == 1 else rule_error_message

            # Tworzenie CSV

            folder_path = os.path.dirname(EXCELS_DIR)
            excels = os.path.join(folder_path, "excels")
            csv_file = os.path.join(excels, f"dq_rule_{rule_id}_results.csv")

            fieldnames = list(records[0].keys())  # już zawiera error_message
            try:
                with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for record in records:
                        writer.writerow(record)
                messagebox.showinfo("Export Complete", f"Rule {rule_id} - {len(records)} records exported to CSV.")
            except Exception as e:
                messagebox.showerror("CSV Error", f"Error exporting rule {rule_id} to CSV:\n{e}")

            os.startfile(excels)
            #os.path.join(folder_path, "excels"))

        finally:
            cursor.close()
            conn.close()

    def on_run_type_change(self):
        if self.run_type.get() == "all":
            #Dropdown locked dla all rules
            self.rule_dropdown.configure(state="disabled")
            #messagebox.showinfo("Info", "Dropdown is disabled in ALL RULES mode.")
        else:
            #Dropdown unlock dla single
            self.rule_dropdown.configure(state="normal")
