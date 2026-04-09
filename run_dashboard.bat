@echo off
setlocal
cd /d "%~dp0"
set "BASE_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SSLKEYLOGFILE="

if not exist "%BASE_DIR%.venv311\Scripts\python.exe" (
    echo Dependencies are not installed. Please run install.bat first.
    pause
    exit /b 1
)

echo Starting Auto Piano Dashboard on http://127.0.0.1:8765
start http://127.0.0.1:8765
"%BASE_DIR%.venv311\Scripts\python.exe" "%BASE_DIR%apps\dashboard.py" %*
if errorlevel 1 pause
exit /b %errorlevel%
