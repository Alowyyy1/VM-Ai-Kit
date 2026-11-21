@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title VirtualMachine AI Kit - Installer and Service
cd /d "%~dp0"

:: Elevation check
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ============================================================
echo         VIRTUALMACHINE AI KIT - INSTALL AND START           
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-vm.ps1"

echo.
echo ============================================================
echo                    VM NETWORK SETTINGS                      
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.' }).IPAddress;" ^
    "Write-Host 'VM IPv4 addresses:' -ForegroundColor Cyan;" ^
    "foreach ($ip in $ips) { Write-Host '  -> ' -NoNewline; Write-Host $ip -ForegroundColor Yellow };" ^
    "Write-Host '';" ^
    "Write-Host 'PORT FORWARDING (NAT mode in VirtualBox/VMware):' -ForegroundColor Magenta;" ^
    "Write-Host '  Host Port: 37075  --->  Guest Port: 37075 (TCP)';" ^
    "Write-Host 'If using Bridged Adapter, use the VM IP above directly on host.';"

echo.
echo Starting Agent...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1" -Foreground
pause
