@echo off
powershell.exe -NoProfile -File "%~dp0v2\server\Windows-Host.ps1" %*
if errorlevel 1 exit /b 1
