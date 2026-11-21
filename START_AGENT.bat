@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Start
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1" -Foreground
pause
