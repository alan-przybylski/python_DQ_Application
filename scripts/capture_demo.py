"""Capture actual application windows using only temporary synthetic data (Windows)."""

import argparse
from pathlib import Path
import sys
import tempfile
import tkinter as tk

from PIL import ImageGrab

from config.db_config import config
from config.paths import PROJECT_DIR
from scripts.seed_demo import create_demo_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "docs/images")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Window-only capture currently requires Windows.")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dq-portfolio-") as temporary:
        old_database = config["database"]
        config["database"] = str(create_demo_database(Path(temporary) / "demo.db"))
        from ui.login_window import LoginWindow
        from ui.dashboard_window import DashboardWindow
        from ui.data_quality import DataQualityWindow
        from ui.check_dq_panel import CheckDqPanel
        from ui.file_history import FileHistory
        from ui.import_window import ImportWindow
        from logic.datasets import read_csv, import_data
        from logic.dq_engine import run_checks
        from config.i18n import set_language

        set_language("EN", persist=False)
        import_data(
            read_csv(PROJECT_DIR / "samples/customers_with_issues.csv"),
            "customers",
            "demo",
        )
        run_checks("customers", "demo")

        root = tk.Tk()
        frames = []
        callback_errors = []
        root.report_callback_exception = lambda *error: callback_errors.append(error)
        clock = tk.StringVar(master=root, value="DEMO / SYNTHETIC DATA")

        def capture(window, filename):
            window.lift()
            window.update_idletasks()
            rendered = tk.BooleanVar(master=window, value=False)
            window.after(400, rendered.set, True)
            window.wait_variable(rendered)
            frame = ImageGrab.grab(window=window.winfo_id())
            frame.save(args.output / filename)
            frames.append(frame)

        try:
            LoginWindow(root)
            capture(root, "login.png")
            for widget in root.winfo_children():
                widget.destroy()
            dashboard = DashboardWindow(root, "demo", "admin")
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(callback)
            dashboard.time_var.set("DEMO / SYNTHETIC DATA")
            capture(root, "workspace.png")
            rules_root = tk.Toplevel(root)
            DataQualityWindow(rules_root, "demo", "admin", root, clock)
            capture(rules_root, "rules.png")
            results_root = tk.Toplevel(root)
            CheckDqPanel(results_root, "demo", "admin", root, clock)
            capture(results_root, "results.png")
            history_root = tk.Toplevel(root)
            FileHistory(history_root, "demo", "admin", root, clock)
            capture(history_root, "history.png")
            import_root = tk.Toplevel(root)
            importer = ImportWindow(import_root, "demo", "superuser", root, clock)
            importer.mode.set("new")
            importer.new_name.set("new_customers")
            importer.change_mode()
            from unittest.mock import patch

            with patch(
                "ui.import_window.filedialog.askopenfilename",
                return_value=str(PROJECT_DIR / "samples/customers_with_issues.csv"),
            ):
                importer.choose_file()
            capture(import_root, "import.png")
            if callback_errors:
                raise RuntimeError(callback_errors)
            frames[0].save(
                args.output / "walkthrough.gif",
                save_all=True,
                append_images=frames[1:],
                duration=2200,
                loop=0,
            )
        finally:
            root.destroy()
            config["database"] = old_database
        print(f"Captured 6 application views and walkthrough: {args.output.resolve()}")


if __name__ == "__main__":
    main()
