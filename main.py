"""Launch the desktop app with private storage or an isolated portfolio demo."""

import argparse
import tkinter as tk

from config.db_config import config
from config.paths import DATA_DIR
from database.connection import initialize_database


def main():
    from config.i18n import load_language, tr

    load_language()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use data/demo.db instead of your private data/app.db.",
    )
    args = parser.parse_args()
    if args.demo:
        from scripts.seed_demo import create_demo_database

        demo_path = DATA_DIR / "demo.db"
        create_demo_database(demo_path)
        config["database"] = str(demo_path)
        from config import paths

        paths.EXCELS_DIR = DATA_DIR / "demo_exports"
        paths.EXCELS_DIR.mkdir(parents=True, exist_ok=True)
        print(
            tr(
                "Demo mode uses a separate database. New demo login: demo / Demo2026. Existing passwords are unchanged."
            )
        )
    initialize_database()
    # Import views after selecting storage, including the isolated demo export path.
    from ui.login_window import LoginWindow
    from ui.utils import place_window

    root = tk.Tk()
    place_window(root)
    LoginWindow(root)
    if args.demo:
        root.title("DQ Studio / " + tr("Demo — synthetic data only"))
    root.mainloop()


if __name__ == "__main__":
    main()
