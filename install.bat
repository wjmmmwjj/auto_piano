@echo off
setlocal
cd /d "%~dp0"
set "BASE_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SSLKEYLOGFILE="

call :find_python
if errorlevel 1 goto :fail

if not exist "%BASE_DIR%.venv311\Scripts\python.exe" (
    echo Creating Python 3.11 virtual environment...
    %PYTHON_CMD% -m venv "%BASE_DIR%.venv311"
    if errorlevel 1 goto :fail
)

set "VENV_PYTHON=%BASE_DIR%.venv311\Scripts\python.exe"

echo Upgrading pip / setuptools / wheel...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --upgrade pip "setuptools<82" wheel
if errorlevel 1 goto :fail

echo Installing PyTorch CUDA 12.1...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --index-url https://download.pytorch.org/whl/cu121 "torch>=2.0.0" "torchaudio>=2.0.0" "torchvision>=0.15.0"
if errorlevel 1 goto :fail

echo Installing project dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%BASE_DIR%playback\requirements.txt" pygame
if errorlevel 1 goto :fail

echo Installing Transkun...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --no-deps transkun
if errorlevel 1 goto :fail

echo.
echo Installation completed.
echo You can now run run_score.bat / run_visualizer.bat / sound.bat / tool.bat.
pause
exit /b 0

:find_python
if exist "%BASE_DIR%.venv311\Scripts\python.exe" (
    set "PYTHON_CMD=%BASE_DIR%.venv311\Scripts\python.exe"
    exit /b 0
)

py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)

winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Unable to install Python 3.11 automatically.
    echo Please install Python 3.11 manually, then run install.bat again.
    exit /b 1
)

py -3.11 -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 was not found.
    echo Please install Python 3.11 manually, then run install.bat again.
    exit /b 1
)

set "PYTHON_CMD=py -3.11"
exit /b 0

:fail
echo.
echo Installation failed. Check the messages above and try again.
pause
exit /b 1
