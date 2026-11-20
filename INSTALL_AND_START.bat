@echo off
setlocal enabledelayedexpansion
title VirtualMachine AI Kit - Installer & Service
cd /d "%~dp0"

:: Elevation check
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Запрос прав Администратора...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ============================================================
echo      VIRTUALMACHINE AI KIT - УСТАНОВКА И ЗАПУСК В VM        
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-vm.ps1"

echo.
echo ============================================================
echo                  СЕТЕВЫЕ НАСТРОЙКИ VM                       
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.' }).IPAddress;" ^
    "Write-Host 'IP-адреса этой виртуальной машины:' -ForegroundColor Cyan;" ^
    "foreach ($ip in $ips) { Write-Host '  -> ' -NoNewline; Write-Host $ip -ForegroundColor Yellow };" ^
    "Write-Host '';" ^
    "Write-Host 'ПРОБРОС ПОРТА (если используется NAT в VirtualBox/VMware/Hyper-V):' -ForegroundColor Magenta;" ^
    "Write-Host '  Host Port: 37075  --->  Guest Port: 37075 (TCP)';" ^
    "Write-Host 'Если сеть Мост (Bridged) - на основном ПК укажите IP этой виртуальной машины и порт 37075.';"

echo.
echo Запуск агента...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1" -Foreground
pause
