"""Resolve data files independently of the current working directory."""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
EXCELS_DIR = PROJECT_DIR / "excels"
DATA_DIR = PROJECT_DIR / "data"
DATABASE_PATH = DATA_DIR / "app.db"
