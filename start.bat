@echo off
REM Double-click this file to set up (first time) and launch AlphaMaxxin.
REM Packages are isolated in .venv; administrator access is unnecessary.

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" setup.py
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found on this computer.
        echo Download it from https://www.python.org/downloads/ and run this again.
        echo IMPORTANT: during install, tick the box that says "Add Python to PATH".
        pause
        exit /b 1
    )
    python setup.py
)
set "ALPHAMAXXIN_SETUP_EXIT=%errorlevel%"
pause
exit /b %ALPHAMAXXIN_SETUP_EXIT%
