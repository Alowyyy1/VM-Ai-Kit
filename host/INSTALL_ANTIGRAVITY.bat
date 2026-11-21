@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Install Antigravity
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action install_antigravity
echo.
pause
