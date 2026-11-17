@echo off
setlocal
set "PM_PYTHON=%~dp0..\meta-page-manager\.venv\Scripts\python.exe"
if not exist "%PM_PYTHON%" (
  echo Run START-PAGE-MANAGER.bat first to prepare Python dependencies.
  pause
  exit /b 1
)
"%PM_PYTHON%" -I -B "%~dp0manage_users.py" bootstrap
if errorlevel 1 (
  echo Account setup did not complete. Read the message above.
  pause
  exit /b 1
)
echo Credentials saved privately in via-auth\data\initial-users.txt
echo Sign in at http://127.0.0.1:8010/auth/login
pause
