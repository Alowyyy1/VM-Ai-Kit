@echo off
title VM Agent Kit - Stop
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-agent.ps1"
pause
