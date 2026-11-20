@echo off
setlocal enabledelayedexpansion
title VirtualMachine AI Kit - Настройка IP и Токена
cd /d "%~dp0"

echo ============================================================
echo   VIRTUALMACHINE AI KIT - СМЕНА IP И ТОКЕНА ДЛЯ СВЯЗИ С VM  
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "Write-Host ('Текущий IP:    ' + $cfg.vm_ip);" ^
    "Write-Host ('Текущий Порт:  ' + $cfg.vm_port);" ^
    "Write-Host ('Текущий Токен: ' + $cfg.token);" ^
    "Write-Host '';" ^
    "$newIp = Read-Host ('Введите IP виртуалки (Enter чтобы оставить ' + $cfg.vm_ip + ')');" ^
    "if ($newIp) { $cfg.vm_ip = $newIp.Trim() };" ^
    "$newPort = Read-Host ('Введите Порт (Enter чтобы оставить ' + $cfg.vm_port + ')');" ^
    "if ($newPort) { $cfg.vm_port = [int]$newPort.Trim() };" ^
    "$newToken = Read-Host ('Введите Токен (Enter чтобы оставить текущий)');" ^
    "if ($newToken) { $cfg.token = $newToken.Trim() };" ^
    "$cfg | ConvertTo-Json | Set-Content $cfgPath -Encoding UTF8;" ^
    "Write-Host '';" ^
    "Write-Host '[+] Новые параметры сохранены в host_config.json!' -ForegroundColor Green;" ^
    "$apply = Read-Host 'Применить настройки сразу ко всем клиентам (Antigravity, OpenCode, Codex)? (Y/n)';" ^
    "if ($apply -eq '' -or $apply -match '^[yYдД]') {" ^
    "  & (Join-Path $PSScriptRoot 'INSTALL_ALL.bat');" ^
    "}"
