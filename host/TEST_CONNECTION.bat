@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Test Connection
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action test_connection
echo.
pause
