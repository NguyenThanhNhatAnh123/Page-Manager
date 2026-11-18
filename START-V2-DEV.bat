@echo off
cd /d "%~dp0v2"
".venv\Scripts\python.exe" scripts\dev_windows.py start
if errorlevel 1 pause
