@echo off
REM ===================================================================
REM  Promak - run the test suite on this computer
REM
REM  Double-click this file. It installs what the tests need inside the
REM  project's own .venv (nothing is touched outside this folder), runs
REM  every test and leaves the window open so the result can be read.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Promak - tests

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo.
    echo The project's .venv was not found next to this file.
    echo Run install_windows.bat first, then try again.
    echo.
    pause
    exit /b 1
)

echo.
echo ===================================================================
echo  1/3  Checking the components the tests need
echo ===================================================================
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install --upgrade pytest "Pillow>=10.0" "vtracer>=0.6" --quiet
if errorlevel 1 (
    echo.
    echo Something could not be installed. The tests will still run, and
    echo the ones that need the missing piece will simply be skipped.
    echo.
)

echo.
echo ===================================================================
echo  2/3  What is installed
echo ===================================================================
"%PY%" -c "import importlib.util as u; [print(('  OK      ' if u.find_spec(m) else '  MISSING ') + m) for m in ['PySide6','PIL','vtracer','yt_dlp','faster_whisper','imageio_ffmpeg','pytest']]"

echo.
echo ===================================================================
echo  3/3  Running the tests
echo ===================================================================
"%PY%" -m pytest -q
set "RESULT=%ERRORLEVEL%"

echo.
if "%RESULT%"=="0" (
    echo ===================================================================
    echo  Everything passed.
    echo ===================================================================
) else (
    echo ===================================================================
    echo  Something failed. Copy the lines above and send them to Claude.
    echo ===================================================================
)
echo.
pause
endlocal
