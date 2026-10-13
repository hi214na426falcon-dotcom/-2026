@echo off
rem Mr.2 Gold weekly backtest - started by Task Scheduler (see docs\automation.md)
rem Extra arguments are passed through, e.g.: run_weekly.bat --dry-run
setlocal
cd /d "%~dp0.."
if not exist reports mkdir reports
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PY=py -3"
where py >nul 2>nul || set "PY=python"
echo ===== %DATE% %TIME% ===== > reports\last_run.log
%PY% automation\run_backtests.py --config automation\config.json %* >> reports\last_run.log 2>&1
set RC=%ERRORLEVEL%
echo ===== exit code %RC% ===== >> reports\last_run.log
exit /b %RC%
