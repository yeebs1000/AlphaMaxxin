@echo off
REM AlphaMaxxin holdings watcher — fired every 15 min by Windows Task
REM Scheduler. Exits instantly when no held market is open.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\backend"
py -m app.watcher > "%~dp0watcher_last_run.log" 2>&1
