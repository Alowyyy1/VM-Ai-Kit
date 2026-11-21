@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Set IP and Token
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action set_config
echo.
pause
