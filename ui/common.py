"""Shared localized widgets and file dialogs."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from config.i18n import tr
from ui.theme import NAVY, SURFACE


def header(root, title, subtitle=""):
    frame = tk.Frame(root, background=NAVY)
    frame.pack(fill="x")
    tk.Label(
        frame,
        text="DQ / STUDIO",
        background=NAVY,
        foreground="#96C8CB",
        font=("Segoe UI", 10, "bold"),
    ).pack(side="left", padx=(20, 16), pady=15)
    tk.Label(
        frame,
        text=tr(title),
        background=NAVY,
        foreground=SURFACE,
        font=("Segoe UI", 17, "bold"),
    ).pack(side="left", pady=15)
    tk.Label(frame, text=subtitle, background=NAVY, foreground="#B2C4D5").pack(
        side="right", padx=20
    )
    return frame


def footer(root, back, clock=None):
    frame = tk.Frame(root)
    frame.pack(side="bottom", fill="x")
    tk.Button(frame, text=tr("Back"), command=back).pack(side="left", padx=12, pady=6)
    if clock is not None:
        tk.Label(frame, textvariable=clock).pack(side="right", padx=16)
    return frame


def environment_filter(root, changed):
    frame = tk.Frame(root)
    frame.pack(fill='x', padx=20, pady=6)
    tk.Label(frame, text=tr('Environment')).pack(side='left', padx=(0, 8))
    values = {tr('All environments'): None, 'Local / SQLite': 'local', 'Databricks': 'databricks'}
    choice = tk.StringVar(value=tr('All environments'))
    picker = ttk.Combobox(frame, textvariable=choice, values=list(values), state='readonly', width=24)
    picker.pack(side='left')
    picker.bind('<<ComboboxSelected>>', lambda event: changed(values[choice.get()]))
    return picker


def table_view(parent, columns, height=5):
    frame = tk.Frame(parent)
    vertical = ttk.Scrollbar(frame, orient="vertical")
    horizontal = ttk.Scrollbar(frame, orient="horizontal")
    tree = ttk.Treeview(
        frame,
        columns=[key for key, label, width in columns],
        show="headings",
        height=height,
        yscrollcommand=vertical.set,
        xscrollcommand=horizontal.set,
    )
    vertical.configure(command=tree.yview)
    horizontal.configure(command=tree.xview)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    for key, label, width in columns:
        tree.heading(key, text=tr(label))
        tree.column(key, width=width, minwidth=45, stretch=False, anchor="w")
    return frame, tree


def error_box(error, parent=None):
    messagebox.showerror(
        tr("Error"), tr("Operation failed: {detail}", detail=str(error)), parent=parent
    )


def save_csv_dialog(parent, name):
    return filedialog.asksaveasfilename(
        parent=parent,
        title=tr("Save CSV"),
        initialfile=name,
        defaultextension=".csv",
        filetypes=[(tr("CSV files"), "*.csv")],
    )
