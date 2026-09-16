"""A small, dependency-free visual system for the existing Tkinter views."""

from tkinter import ttk

BACKGROUND = "#F2F5FA"
SURFACE = "#FFFFFF"
INK = "#172B4D"
MUTED = "#526581"
ACCENT = "#146C72"
NAVY = "#12243A"


def apply_theme(window):
    window.configure(background=BACKGROUND)
    for option, value in {
        "*Font": "{Segoe UI} 10",
        "*Background": BACKGROUND,
        "*Foreground": INK,
        "*Button.Background": ACCENT,
        "*Button.Foreground": SURFACE,
        "*Button.activeBackground": "#0D555A",
        "*Button.activeForeground": SURFACE,
        "*Button.relief": "flat",
        "*Button.borderWidth": 0,
        "*Button.padX": 18,
        "*Button.padY": 9,
        "*Button.cursor": "hand2",
        "*Entry.Background": SURFACE,
        "*Entry.relief": "solid",
        "*Entry.borderWidth": 1,
        "*Entry.highlightThickness": 1,
        "*Entry.highlightColor": ACCENT,
        "*Entry.highlightBackground": "#CCD6E4",
        "*Text.Background": SURFACE,
        "*Text.relief": "solid",
        "*Text.borderWidth": 1,
    }.items():
        window.option_add(option, value)
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=INK, rowheight=29, borderwidth=0, font=("Segoe UI", 9))
    style.configure("Treeview.Heading", background="#E3EBF3", foreground=INK,
                    font=("Segoe UI", 9, "bold"), relief="flat", padding=(8, 9))
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", SURFACE)])
    style.configure("TCombobox", padding=5, fieldbackground=SURFACE, foreground=INK)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])
    style.configure("TScrollbar", background="#B9C7D7", troughcolor=BACKGROUND,
                    borderwidth=0, arrowsize=13)
