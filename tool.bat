@echo off
setlocal
cd /d "%~dp0"
set "BASE_DIR=%~dp0"
set "SSLKEYLOGFILE="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%BASE_DIR%.venv311\Scripts\python.exe" (
    echo Dependencies are not installed. Please run install.bat first.
    pause
    exit /b 1
)

"%BASE_DIR%.venv311\Scripts\python.exe" "%BASE_DIR%apps\piano_motor_tuner.py"
if errorlevel 1 pause
endlocal & exit /b %errorlevel%
