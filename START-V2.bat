@echo off
cd /d "%~dp0v2"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\start.ps1"
pause
