@echo off
setlocal
title Promak - debug mode

rem Starts Promak with a visible console, so any error message stays on
rem screen instead of disappearing. Use this file when the normal
rem run_promak.bat opens nothing, and send the text below to support.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The private environment is missing. Run install_windows.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Promak in debug mode...
echo ------------------------------------------------------------
".venv\Scripts\python.exe" -m promak
echo ------------------------------------------------------------
echo Promak has exited with code %errorlevel%.
echo.
echo The full log file is here:
echo   %APPDATA%\Promak\logs\promak.log
echo.
pause
