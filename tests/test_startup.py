"""Exercise demo startup wiring without opening a desktop or touching private data."""

import os
from pathlib import Path
import subprocess
import sys


def test_demo_startup_isolates_database_and_exports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    program = r"""
import hashlib
from pathlib import Path
import sys
import config.paths as paths
from config.db_config import config

paths.DATA_DIR = Path(sys.argv[1])
paths.DATABASE_PATH = paths.DATA_DIR / "app.db"
private = paths.DATABASE_PATH
private.write_bytes(b"private sentinel - do not touch")
before = hashlib.sha256(private.read_bytes()).hexdigest()
config["database"] = str(private)

import main
class FakeRoot:
    def title(self, value): pass
    def mainloop(self): pass
main.tk.Tk = FakeRoot
import ui.utils
ui.utils.place_window = lambda window: None
import types
login_stub = types.ModuleType('ui.login_window')
login_stub.LoginWindow = lambda window: None
sys.modules['ui.login_window'] = login_stub
sys.argv = ["main.py", "--demo"]
main.main()
assert Path(config["database"]) == paths.DATA_DIR / "demo.db"
assert paths.EXCELS_DIR == paths.DATA_DIR / "demo_exports"
assert hashlib.sha256(private.read_bytes()).hexdigest() == before
"""
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
