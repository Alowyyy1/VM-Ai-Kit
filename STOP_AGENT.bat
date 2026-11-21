@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Stop
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-agent.ps1"
pause
