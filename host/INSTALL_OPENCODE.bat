@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Install OpenCode
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action install_opencode
echo.
pause
