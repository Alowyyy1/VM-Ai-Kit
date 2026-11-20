@echo off
setlocal enabledelayedexpansion
title Setup VirtualMachine AI Kit for Antigravity
cd /d "%~dp0"

echo ============================================================
echo   УСТАНОВКА VIRTUALMACHINE AI KIT В GOOGLE ANTIGRAVITY      
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "$ip = $cfg.vm_ip; $port = $cfg.vm_port; $token = $cfg.token;" ^
    "$mcpDir = Join-Path $env:USERPROFILE '.gemini\antigravity\mcp\vm-agent';" ^
    "$schemasSrc = Join-Path $PSScriptRoot 'antigravity_schemas';" ^
    "if (Test-Path $schemasSrc) { New-Item -ItemType Directory -Force -Path $mcpDir | Out-Null; Copy-Item -Path \"$schemasSrc\*\" -Destination $mcpDir -Recurse -Force; Write-Host \"[+] Схемы инструментов (95 шт) скопированы в: $mcpDir\" -ForegroundColor Green };" ^
    "$antigravityCfg = Join-Path $env:USERPROFILE '.gemini\config\mcp_config.json';" ^
    "if (-not (Test-Path (Split-Path $antigravityCfg))) { New-Item -ItemType Directory -Force -Path (Split-Path $antigravityCfg) | Out-Null };" ^
    "$json = if (Test-Path $antigravityCfg) { Get-Content $antigravityCfg -Raw | ConvertFrom-Json } else { [ordered]@{ mcpServers = [ordered]@{} } };" ^
    "if (-not $json.mcpServers) { $json | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value ([ordered]@{}) };" ^
    "$entry = [ordered]@{ url = \"http://${ip}:${port}/mcp\"; headers = [ordered]@{ Authorization = \"Bearer $token\" } };" ^
    "$json.mcpServers | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force;" ^
    "$json | ConvertTo-Json -Depth 10 | Set-Content $antigravityCfg -Encoding UTF8;" ^
    "Write-Host \"[+] Antigravity MCP конфиг обновлен: $antigravityCfg\" -ForegroundColor Green;" ^
    "Write-Host \"[+] URL: http://${ip}:${port}/mcp\" -ForegroundColor Cyan;"

echo.
echo Готово!
pause
