@echo off
chcp 65001 >nul
title VirtualMachine AI Kit - Uninstall
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
pause
