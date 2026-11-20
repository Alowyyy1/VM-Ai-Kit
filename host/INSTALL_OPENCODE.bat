@echo off
setlocal enabledelayedexpansion
title Setup VirtualMachine AI Kit for OpenCode
cd /d "%~dp0"

echo ============================================================
echo     УСТАНОВКА VIRTUALMACHINE AI KIT В OPENCODE              
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "$ip = $cfg.vm_ip; $port = $cfg.vm_port; $token = $cfg.token;" ^
    "$opencodeCfg = Join-Path $env:USERPROFILE '.config\opencode\opencode.json';" ^
    "if (-not (Test-Path (Split-Path $opencodeCfg))) { New-Item -ItemType Directory -Force -Path (Split-Path $opencodeCfg) | Out-Null };" ^
    "$json = if (Test-Path $opencodeCfg) { Get-Content $opencodeCfg -Raw | ConvertFrom-Json } else { [ordered]@{} };" ^
    "if (-not $json.mcp) { $json | Add-Member -MemberType NoteProperty -Name 'mcp' -Value ([ordered]@{}) };" ^
    "$entry = [ordered]@{ type = 'remote'; url = \"http://${ip}:${port}/mcp\"; oauth = $false; headers = [ordered]@{ Authorization = \"Bearer $token\" }; enabled = $true };" ^
    "if ($json.mcp.servers) { $json.mcp.servers | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force } else { $json.mcp | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force };" ^
    "$json | ConvertTo-Json -Depth 15 | Set-Content $opencodeCfg -Encoding UTF8;" ^
    "Write-Host \"[+] OpenCode конфиг обновлен: $opencodeCfg\" -ForegroundColor Green;" ^
    "Write-Host \"[+] URL: http://${ip}:${port}/mcp\" -ForegroundColor Cyan;"

echo.
echo Готово!
pause
