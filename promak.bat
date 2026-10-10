@echo off
rem Promak from the command line, for scripts and the Windows Task Scheduler.
rem   promak.bat resize "D:\Photos" --out "D:\Web" --longest 1600
rem   promak.bat --help
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" (
    echo The private environment is missing. Run install_windows.bat first.
    exit /b 2
)
"%HERE%.venv\Scripts\python.exe" -m promak %*
exit /b %errorlevel%
