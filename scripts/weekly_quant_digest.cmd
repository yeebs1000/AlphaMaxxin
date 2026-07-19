@echo off
REM AlphaMaxxin weekly Quant Lab digest — same pattern as daily_digest.cmd,
REM a different preset/topic/cadence. Not registered as a scheduled task yet.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\backend"
py -m app.digest weekly > "%~dp0weekly_quant_digest_last_run.log" 2>&1
