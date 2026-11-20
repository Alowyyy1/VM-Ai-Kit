@echo off
setlocal enabledelayedexpansion
title VirtualMachine AI Kit - Проверка связи с VM
cd /d "%~dp0"

echo ============================================================
echo   ПРОВЕРКА ПОДКЛЮЧЕНИЯ К VIRTUALMACHINE AI KIT (PORT 37075)  
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "$url = \"http://$($cfg.vm_ip):$($cfg.vm_port)/healthz\";" ^
    "Write-Host \"[*] Проверка адреса: $url...\" -ForegroundColor Cyan;" ^
    "try {" ^
    "    $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5;" ^
    "    Write-Host '[+] УСПЕШНО! VirtualMachine AI Kit работает и отвечает.' -ForegroundColor Green;" ^
    "    Write-Host ('    Версия сервиса: ' + $resp.version);" ^
    "    Write-Host ('    Имя машины VM:  ' + $resp.hostname);" ^
    "    Write-Host ('    Пользователь:   ' + $resp.user);" ^
    "    Write-Host ('    Session ID:     ' + $resp.session);" ^
    "    Write-Host ('    Elevated Admin: ' + $resp.elevated);" ^
    "    Write-Host ('    Uptime:         ' + $resp.uptime_s + ' сек');" ^
    "} catch {" ^
    "    Write-Host '[-] ОШИБКА: Не удалось подключиться к VM Agent!' -ForegroundColor Red;" ^
    "    Write-Host ('    Причина: ' + $_.Exception.Message);" ^
    "    Write-Host '';" ^
    "    Write-Host 'Чек-лист:' -ForegroundColor Yellow;" ^
    "    Write-Host '  1. Запущен ли INSTALL_AND_START.bat внутри виртуальной машины?';" ^
    "    Write-Host '  2. Проброшен ли порт 37075 в настройках VirtualBox / VMware?';" ^
    "    Write-Host '     (Host: 127.0.0.1:37075 -> Guest: 37075)';" ^
    "    Write-Host '  3. Если режим Bridged, указан ли правильный IP виртуалки в host_config.json?';" ^
    "    Write-Host '     (Запустите SET_IP_AND_TOKEN.bat для изменения)';" ^
    "}"

echo.
pause
