@echo off
cd /d "%~dp0"
if exist ".venv\bin\python.exe" (
    ".venv\bin\python.exe" main.py
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
)
pause
