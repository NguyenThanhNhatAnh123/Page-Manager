@echo off
powershell.exe -NoProfile -File "%~dp0v2\server\windows\Install-Native.ps1" -Action Check %*
if errorlevel 1 exit /b 1
