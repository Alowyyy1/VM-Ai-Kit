@echo off
title VM Agent Kit - Uninstall
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
pause
