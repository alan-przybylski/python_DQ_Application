import pandas as pd
import sqlite3
from sqlite3 import Error
from database.connection import get_connection
from config.paths import EXCELS_DIR
from tkinter import messagebox  # jeśli chcesz komunikat w GUI


import pandas as pd
import sqlite3
from sqlite3 import Error
from database.connection import get_connection
from tkinter import messagebox
import os

def load_csv_and_log(csv_file, table_name, username):
    log = []
    success = True
    error_shown = False

    folder = str(EXCELS_DIR)
    full_path = os.path.join(folder, csv_file)
    filename_only = os.path.basename(full_path)

    try:
        df = pd.read_csv(full_path, sep=None, engine='python', encoding='cp1250')
        row_count = len(df)
        log.append(f"Loaded {row_count} rows from {filename_only}.")

        df.columns = [col.strip().replace(';','') for col in df.columns]
        df = df.apply(lambda col: col.str.replace(';','', regex=False) if col.dtype == 'object' else col)
        log.append(f"Columns: {list(df.columns)}")

        conn = get_connection()
        cursor = conn.cursor()

        for _, row in df.iterrows():
            try:
                columns = ', '.join(df.columns)
                placeholders = ', '.join(['?'] * len(row))
                update_stmt = ', '.join([f'{col}=excluded.{col}' for col in df.columns if col != 'id'])

                sql = f"""
                    INSERT INTO {table_name} ({columns})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_stmt};
                """

                cursor.execute(sql, tuple(None if pd.isna(value) else value for value in row))
                conn.commit()
            except Error as e:
                success = False
                log.append(f"SQL error in row: {row.to_dict()}")
                log.append(str(e))
                if not error_shown:
                    messagebox.showerror("Error", f"SQL error in a row:\n{e}")
                    error_shown = True
                break

        if success:
            try:
                cursor.execute("""
                    INSERT INTO data_load_log (table_name, file_name, row_count, loaded_by)
                    VALUES (?, ?, ?, ?)
                """, (table_name, filename_only, row_count, username))
                conn.commit()
                log.append("The log entry has been saved in data_load_log.")
            except Error as e:
                success = False
                log.append(f"SQLite error when inserting into data_load_log: {e}")
                if not error_shown:
                    messagebox.showerror("Error", f"Error inserting into data_load_log:\n{e}")
                    error_shown = True

    except Exception as e:
        success = False
        log.append(f"Critical error: {e}")
        if not error_shown:
            messagebox.showerror("Error", f"The following error occurred:\n{e}")
            error_shown = True

    finally:
        if 'conn' in locals() and conn is not None:
            cursor.close()
            conn.close()
            log.append("Connection with DB closed.")

    return "\n".join(log), success  # <-- zwracamy log i flagę sukcesu
