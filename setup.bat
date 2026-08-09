@echo off
echo ============================================
echo  Amateur Radio Contact Log - First Time Setup
echo ============================================
echo.
cd /d "%~dp0"

REM Find a Python launcher (prefer the py launcher, fall back to python)
set "PYCMD="
where py >nul 2>&1 && set "PYCMD=py"
if not defined PYCMD ( where python >nul 2>&1 && set "PYCMD=python" )
if not defined PYCMD (
    echo ERROR: Python 3 is not installed or not on PATH.
    echo Install it from https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^).
    echo.
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
%PYCMD% -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create the virtual environment.
    pause
    exit /b 1
)

echo [2/3] Installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [3/3] Setup complete!
echo.
echo ============================================
echo  You can now launch the app by running:
echo  RadioLog.bat
echo ============================================
echo.
pause
