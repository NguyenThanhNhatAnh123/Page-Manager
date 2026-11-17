@echo off
cd /d "%~dp0"
if exist "v2\.venv\Scripts\python.exe" (
  "v2\.venv\Scripts\python.exe" "v2\scripts\connect_codespace.py"
) else (
  python "v2\scripts\connect_codespace.py"
)
pause
