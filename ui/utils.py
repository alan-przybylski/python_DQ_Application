"""Shared window dimensions and presentation; no business logic."""

from ui.theme import apply_theme


def place_window(window, width=1100, height=720):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = min(width, max(1, screen_width - 40))
    height = min(height, max(1, screen_height - 100))
    x = (screen_width - width) // 2
    y = (screen_height - height) // 3
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.resizable(False, False)
    apply_theme(window)
