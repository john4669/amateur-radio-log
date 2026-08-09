@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo.
    echo The app has not been set up yet.
    echo Please run: setup.bat
    echo.
    pause
    exit /b 1
)

start "" "venv\Scripts\pythonw.exe" main.py
