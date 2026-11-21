@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Full Host Install
cd /d "%~dp0"
echo ============================================================
echo    VIRTUALMACHINE AI KIT - HOST SETUP (3 IN 1)
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action install_all
echo.
pause
