@echo off
setlocal enabledelayedexpansion
title Setup VirtualMachine AI Kit for Codex
cd /d "%~dp0"

echo ============================================================
echo       УСТАНОВКА VIRTUALMACHINE AI KIT В CODEX               
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "$ip = $cfg.vm_ip; $port = $cfg.vm_port; $token = $cfg.token;" ^
    "$codexCfg = Join-Path $env:USERPROFILE '.codex\config.toml';" ^
    "if (-not (Test-Path (Split-Path $codexCfg))) { New-Item -ItemType Directory -Force -Path (Split-Path $codexCfg) | Out-Null };" ^
    "$content = if (Test-Path $codexCfg) { Get-Content $codexCfg -Raw } else { '' };" ^
    "$block = \"`r`n[mcp_servers.vm-agent]`r`nurl = 'http://${ip}:${port}/mcp'`r`nhttp_headers = { Authorization = 'Bearer $token' }`r`n\";" ^
    "if ($content -match '\[mcp_servers\.vm-agent\]') { $content = $content -replace '(?s)\[mcp_servers\.vm-agent\].*?(?=\r?\n\[|$)', $block.Trim() } else { $content = $content.TrimEnd() + \"`r`n\" + $block };" ^
    "Set-Content -Path $codexCfg -Value $content -Encoding UTF8;" ^
    "Write-Host \"[+] Codex config.toml обновлен: $codexCfg\" -ForegroundColor Green;" ^
    "Write-Host \"[+] URL: http://${ip}:${port}/mcp\" -ForegroundColor Cyan;"

echo.
echo Готово!
pause
