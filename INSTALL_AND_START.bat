@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title VirtualMachine AI Kit - Install and Start
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Requesting Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ============================================================
echo        VIRTUALMACHINE AI KIT - INSTALL AND START
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-vm.ps1"
if %errorlevel% neq 0 (
    echo [-] Installation failed with exit code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo                  NETWORK INTERFACES
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.' }).IPAddress;" ^
    "Write-Host 'Machine IPv4 addresses:' -ForegroundColor Cyan;" ^
    "foreach ($ip in $ips) { Write-Host ('  -> ' + $ip) -ForegroundColor Yellow };" ^
    "Write-Host '';" ^
    "Write-Host 'Connect from host using http://<IP>:37075/mcp (or 127.0.0.1:37075 with NAT port forward).' -ForegroundColor Gray;"

echo.
echo [*] Starting Agent in foreground (you can close this window; autostart runs in background on logon)...
if exist "C:\AgentKit\start-agent.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "C:\AgentKit\start-agent.ps1" -Foreground
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1" -Foreground
)
pause
