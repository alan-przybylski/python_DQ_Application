"""Windowed Windows launcher with persistent, local startup diagnostics."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
import os
import runpy
import sys
import traceback

PROJECT_DIR = Path(__file__).resolve().parents[1]


def show_error(message):
    # Native dialog still works if Tkinter itself is missing or cannot load.
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, message, "DQ Studio", 0x10)


def launch(project_dir=None):
    project = Path(project_dir or PROJECT_DIR).resolve()
    log_path = project / "data" / "launcher.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # One log per most recent launch, not an unbounded file.
        with log_path.open("w", encoding="utf-8", buffering=1) as log:
            with redirect_stdout(log), redirect_stderr(log):
                print(f"DQ Studio startup: {datetime.now().isoformat()}")
                try:
                    os.chdir(project)
                    sys.path.insert(0, str(project))
                    sys.argv = [str(project / "main.py"), *sys.argv[1:]]
                    runpy.run_path(str(project / "main.py"), run_name="__main__")
                except SystemExit as error:
                    if error.code not in (None, 0):
                        raise
                except Exception:
                    traceback.print_exc()
                    raise
    except (Exception, SystemExit):
        show_error(
            "Could not start DQ Studio / Nie mozna uruchomic DQ Studio.\n\n"
            f"Diagnostic log / Log diagnostyczny:\n{log_path}\n\n"
            "For missing dependencies, run in the project folder:\n"
            "Przy brakujacych zaleznosciach uruchom w folderze projektu:\n"
            "uv sync --frozen\n\n"
            "If the log is unavailable, check folder permissions and start main.py "
            "from PowerShell."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())
