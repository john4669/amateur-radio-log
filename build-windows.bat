@echo off
REM ============================================================
REM  Build the W0BCQ Logger Windows executable with PyInstaller.
REM  Run this from the project folder AFTER booting into Windows.
REM  Output: dist\W0BCQ_Logger\W0BCQ_Logger.exe
REM ============================================================
setlocal

REM -- The venv copied from the Linux partition is unusable on
REM -- Windows, so always rebuild a fresh Windows virtualenv.
echo === Removing any stale venv ===
if exist venv rmdir /s /q venv

echo === Creating Windows virtualenv (Python 3.x via py launcher) ===
py -m venv venv || goto :err

echo === Installing dependencies ===
call venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :err
REM pillow lets PyInstaller auto-convert the PNG app icon to .ico at build time.
pip install -r requirements.txt pyinstaller pillow || goto :err

echo === Building executable ===
pyinstaller --noconfirm W0BCQ_Logger.spec || goto :err

echo.
echo === BUILD COMPLETE ===
echo Executable: dist\W0BCQ_Logger\W0BCQ_Logger.exe
goto :eof

:err
echo.
echo *** BUILD FAILED ***
exit /b 1
