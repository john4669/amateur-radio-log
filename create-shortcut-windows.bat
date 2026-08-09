@echo off
REM Creates a Windows desktop shortcut for W0BCQ Logger.
REM Run this once from the project folder.
setlocal
cd /d "%~dp0"

REM Project folder without the trailing backslash
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

REM Resolve the real Desktop via PowerShell so OneDrive-redirected
REM Desktops (C:\Users\<you>\OneDrive\Desktop) are handled correctly.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $desktop 'W0BCQ Logger.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath='%APP_DIR%\RadioLog.bat'; $s.WorkingDirectory='%APP_DIR%'; $s.IconLocation='%APP_DIR%\icon.ico'; $s.Description='Log amateur radio contacts and export ADIF for N3FJP AC Log'; $s.Save(); Write-Output ('Desktop shortcut created: ' + $lnk)"

pause
