@echo off
setlocal enabledelayedexpansion
title Setup VirtualMachine AI Kit - Full Host Install
cd /d "%~dp0"

echo ============================================================
echo   VIRTUALMACHINE AI KIT - ПОЛНАЯ УСТАНОВКА НА ХОСТ (3 В 1)   
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = Join-Path $PSScriptRoot 'host_config.json';" ^
    "$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { @{ vm_ip='127.0.0.1'; vm_port=37075; token='vm_agent_token_980154022847733770_re' } };" ^
    "Write-Host 'Текущие параметры подключения к VM:' -ForegroundColor Cyan;" ^
    "Write-Host ('  IP/Хост: ' + $cfg.vm_ip);" ^
    "Write-Host ('  Порт:    ' + $cfg.vm_port);" ^
    "Write-Host ('  Токен:   ' + $cfg.token);"

echo.
echo [1/3] Установка в Google Antigravity...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfg = Get-Content (Join-Path $PSScriptRoot 'host_config.json') -Raw | ConvertFrom-Json;" ^
    "$mcpDir = Join-Path $env:USERPROFILE '.gemini\antigravity\mcp\vm-agent';" ^
    "New-Item -ItemType Directory -Force -Path $mcpDir | Out-Null;" ^
    "Copy-Item (Join-Path $PSScriptRoot 'antigravity_schemas\*') $mcpDir -Recurse -Force;" ^
    "$antigravityCfg = Join-Path $env:USERPROFILE '.gemini\config\mcp_config.json';" ^
    "$json = if (Test-Path $antigravityCfg) { Get-Content $antigravityCfg -Raw | ConvertFrom-Json } else { [ordered]@{ mcpServers = [ordered]@{} } };" ^
    "$entry = [ordered]@{ url = ('http://' + $cfg.vm_ip + ':' + $cfg.vm_port + '/mcp'); headers = [ordered]@{ Authorization = ('Bearer ' + $cfg.token) } };" ^
    "$json.mcpServers | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force;" ^
    "$json | ConvertTo-Json -Depth 10 | Set-Content $antigravityCfg -Encoding UTF8;" ^
    "Write-Host '[+] Antigravity успешно настроен!' -ForegroundColor Green;"

echo.
echo [2/3] Установка в OpenCode...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfg = Get-Content (Join-Path $PSScriptRoot 'host_config.json') -Raw | ConvertFrom-Json;" ^
    "$opencodeCfg = Join-Path $env:USERPROFILE '.config\opencode\opencode.json';" ^
    "if (Test-Path $opencodeCfg) {" ^
    "  $json = Get-Content $opencodeCfg -Raw | ConvertFrom-Json;" ^
    "  $entry = [ordered]@{ type = 'remote'; url = ('http://' + $cfg.vm_ip + ':' + $cfg.vm_port + '/mcp'); oauth = $false; headers = [ordered]@{ Authorization = ('Bearer ' + $cfg.token) }; enabled = $true };" ^
    "  if ($json.mcp.servers) { $json.mcp.servers | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force } else { $json.mcp | Add-Member -MemberType NoteProperty -Name 'vm-agent' -Value $entry -Force };" ^
    "  $json | ConvertTo-Json -Depth 15 | Set-Content $opencodeCfg -Encoding UTF8;" ^
    "  Write-Host '[+] OpenCode успешно настроен!' -ForegroundColor Green;" ^
    "} else { Write-Warning 'OpenCode config not found at $opencodeCfg' };"

echo.
echo [3/3] Установка в Codex...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfg = Get-Content (Join-Path $PSScriptRoot 'host_config.json') -Raw | ConvertFrom-Json;" ^
    "$codexCfg = Join-Path $env:USERPROFILE '.codex\config.toml';" ^
    "if (Test-Path $codexCfg) {" ^
    "  $content = Get-Content $codexCfg -Raw;" ^
    "  $block = \"`r`n[mcp_servers.vm-agent]`r`nurl = 'http://\" + $cfg.vm_ip + \":\" + $cfg.vm_port + \"/mcp'`r`nhttp_headers = { Authorization = 'Bearer \" + $cfg.token + \"' }`r`n\";" ^
    "  if ($content -match '\[mcp_servers\.vm-agent\]') { $content = $content -replace '(?s)\[mcp_servers\.vm-agent\].*?(?=\r?\n\[|$)', $block.Trim() } else { $content = $content.TrimEnd() + \"`r`n\" + $block };" ^
    "  Set-Content -Path $codexCfg -Value $content -Encoding UTF8;" ^
    "  Write-Host '[+] Codex config.toml успешно настроен!' -ForegroundColor Green;" ^
    "} else { Write-Warning 'Codex config not found at $codexCfg' };"

echo.
echo ============================================================
echo   ГОТОВО! VIRTUALMACHINE AI KIT ЗАРЕГИСТРИРОВАН В:          
echo   1. Antigravity                                            
echo   2. OpenCode                                               
echo   3. Codex                                                  
echo ============================================================
pause
