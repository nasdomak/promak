@echo off
setlocal enabledelayedexpansion
title Promak - installation

echo ============================================
echo   Promak - installation
echo ============================================
echo.

cd /d "%~dp0"

rem =========================================================================
rem  Find a real Python 3, even when it is not on PATH.
rem  Order: py launcher, PATH, then the usual installation folders.
rem  The Microsoft Store stub never answers "--version", so it is skipped.
rem =========================================================================
set "PYCMD="

py -3 --version >nul 2>nul && set "PYCMD=py -3"
if defined PYCMD echo Found Python through the "py" launcher.

if not defined PYCMD (
    python --version >nul 2>nul && set "PYCMD=python"
    if defined PYCMD echo Found Python on PATH.
)

if not defined PYCMD call :search_python
if not defined PYCMD goto :no_python

for /f "tokens=*" %%v in ('%PYCMD% --version 2^>^&1') do set "PYVER=%%v"
echo Using !PYVER!
echo.

echo [1/4] Creating the private environment ^(folder .venv^)...
if not exist ".venv\Scripts\python.exe" (
    %PYCMD% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo [X] The environment could not be created.
    goto :failed
)

echo [2/4] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 goto :failed

echo [3/4] Installing Promak and its components...
echo       ^(this downloads around 1 GB the first time, please wait^)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo [4/4] Checking that everything really works...
".venv\Scripts\python.exe" -c "import PySide6, yt_dlp, faster_whisper, PIL, vtracer; from promak.core.dependencies import check_dependencies, image_dependencies; [print('   ', d.label, '->', 'OK' if d.available else 'MISSING') for d in check_dependencies() + image_dependencies()]"
if errorlevel 1 (
    echo.
    echo [X] The components were installed but cannot be loaded.
    goto :failed
)

echo.
echo ============================================
echo   Installation completed.
echo   Start the program with:  run_promak.bat
echo ============================================
echo.
pause
exit /b 0


rem -------------------------------------------------------------------------
:search_python
echo Python is not on PATH; looking for it in the usual folders...
set "FOUND="
for %%R in (
    "%LOCALAPPDATA%\Programs\Python"
    "%ProgramFiles%\Python312"
    "%ProgramFiles%\Python311"
    "%ProgramFiles%\Python310"
    "%ProgramFiles%\Python313"
    "%ProgramFiles(x86)%\Python312"
    "%ProgramFiles(x86)%\Python311"
    "C:\Python313"
    "C:\Python312"
    "C:\Python311"
    "C:\Python310"
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\miniconda3"
    "%ProgramData%\anaconda3"
    "%LOCALAPPDATA%\Programs\Microsoft VS Code\python"
) do (
    if not defined FOUND (
        if exist %%~R (
            for /f "delims=" %%P in ('dir /b /s /a-d "%%~R\python.exe" 2^>nul') do (
                if not defined FOUND (
                    echo %%P | find /i "WindowsApps" >nul || set "FOUND=%%P"
                )
            )
        )
    )
)
if defined FOUND (
    echo Found Python at: !FOUND!
    set PYCMD="!FOUND!"
)
exit /b 0


rem -------------------------------------------------------------------------
:no_python
echo.
echo [X] No working Python 3 was found on this computer.
echo.
echo     If you are sure Python is installed, it is probably not visible
echo     to Windows. Do this:
echo.
echo       1. Press Start, type "Manage app execution aliases"
echo          and turn OFF the two entries named "python.exe" / "python3.exe".
echo       2. Or reinstall Python from https://www.python.org/downloads/
echo          ticking "Add python.exe to PATH" on the first screen.
echo.
echo     Then close every window and run this file again.
echo.
echo     To tell the developer what is going on, open PowerShell and run:
echo         where.exe python
echo         py -0p
echo.
pause
exit /b 1


rem -------------------------------------------------------------------------
:failed
echo.
echo [X] Installation failed. Read the message above, check the internet
echo     connection and run this file again.
echo.
pause
exit /b 1
