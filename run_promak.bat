@echo off
setlocal
title Promak

cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m promak
    exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Run install_windows.bat first.
    pause
    exit /b 1
)

echo The private environment is missing; run install_windows.bat first.
echo Trying with the system Python anyway...
python -m promak
if errorlevel 1 pause
exit /b 0
