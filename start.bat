@echo off
REM Double-click this file to set up (first time) and launch AlphaMaxxin.
REM If nothing happens when you double-click, right-click this file and
REM choose "Run as administrator", or open a Command Prompt and run:
REM     python setup.py

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python was not found on this computer.
    echo Download it from https://www.python.org/downloads/ and run this again.
    echo IMPORTANT: during install, tick the box that says "Add Python to PATH".
    pause
    exit /b 1
)

python setup.py
pause
