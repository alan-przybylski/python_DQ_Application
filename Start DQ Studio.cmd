@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo DQ Studio: Python environment not found.
    echo Srodowisko Python nie zostalo przygotowane.
    echo.
    echo Open PowerShell in the project folder and run:
    echo uv sync --frozen
    echo.
    pause
    exit /b 1
)
if not exist "%~dp0scripts\launch_desktop.py" (
    echo DQ Studio: launcher files are missing. Restore the complete project.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\launch_desktop.py" %*
exit /b 0
