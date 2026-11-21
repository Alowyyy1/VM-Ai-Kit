@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title VM-Ai-Kit Agent Supervisor
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "PYTHONPATH=%ROOT%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

if not exist "%ROOT%\work" mkdir "%ROOT%\work"

:loop
echo [%date% %time%] [SUPERVISOR] Starting VM-Ai-Kit Agent... >> "%ROOT%\work\watchdog.log"
"%ROOT%\venv\Scripts\python.exe" -m vm_agent.server --config "%ROOT%\agent.json" >> "%ROOT%\work\agent_stdout.log" 2>> "%ROOT%\work\agent_err.log"
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] [SUPERVISOR] Agent process exited with code %EXIT_CODE%. Restarting in 3 seconds... >> "%ROOT%\work\watchdog.log"
timeout /t 3 /nobreak >nul
goto loop
