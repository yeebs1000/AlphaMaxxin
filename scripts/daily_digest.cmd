@echo off
REM AlphaMaxxin daily digest — run by Windows Task Scheduler on this machine so
REM it can reach the local brokers (moomoo OpenD / IB Gateway). Reads keys from
REM the repo-root .env. Logs to scripts\digest_last_run.log for troubleshooting.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\backend"
py -m app.digest > "%~dp0digest_last_run.log" 2>&1
