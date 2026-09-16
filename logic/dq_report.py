import tkinter as tk
from datetime import date
from tkinter import messagebox, Scale, HORIZONTAL
import sqlite3
from database.connection import get_connection
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


#Globalne funkcje poniżej (class utrudniało):
def get_data_from_dq_results():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rule_id, id as test_number,
                   DATE(timestamp) AS day,
                   ROUND((100.0 * SUM(passed_count) / NULLIF(SUM(passed_count) + SUM(failed_count), 0)),2) AS pass_percent
            FROM dq_results
            GROUP BY rule_id, DATE(timestamp), id
            ORDER BY rule_id, DATE(timestamp), id;
        """)
        data = cursor.fetchall()
        return [(rule_id, test_number, date.fromisoformat(day), percent)
                for rule_id, test_number, day, percent in data]
    except sqlite3.Error as e:
        messagebox.showerror("Database Error", f"Error: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn and conn is not None:
            conn.close()


def draw_chart(frame, data):
    if not data:
        return

    fig = Figure(figsize=(6, 4), dpi=100)
    ax = fig.add_subplot(111)

    rules = {}
    for rule_id, test_number, day, pass_percent in data:
        day_str = day.strftime('%Y-%m-%d')
        rules.setdefault(rule_id, []).append((day_str, pass_percent))

    for rule_id, points in rules.items():
        days, percents = zip(*points)

        # TUTAJ WYBIERAM RODZAJ WYKRESU
        ax.plot(days, percents, marker="o", label=f"{rule_id}")  #LINIOWY
        #ax.bar(days, percents, label=f"{rule_id}")   #Słupkowy (kiepski)
        #ax.scatter(days, percents, marker="o", label=f"{rule_id}")  #PUNKTOWY

    ax.set_title("Daily Pass Percent per Rule")
    ax.set_xlabel("Day")
    ax.set_ylabel("Pass Percent")
    ax.legend()
    #ax.set_xlim(days[0], days[-1])   #USTAWIANIE ZAKRESU DNI NA WYKRESIE

    canvas = FigureCanvasTkAgg(fig, master=frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

# def scale_chart(val):
#     for widget in chart_frame.winfo_children():
#         widget.destroy()
#     draw_chart(chart_frame, data, last)
