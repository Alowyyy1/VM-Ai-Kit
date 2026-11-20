@echo off
title VM Agent Kit - Start
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1" -Foreground
pause
