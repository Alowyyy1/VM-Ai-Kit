[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("install_all", "install_antigravity", "install_opencode", "install_codex", "set_config", "test_connection")]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$HostDir = $PSScriptRoot
$CfgPath = Join-Path $HostDir "host_config.json"

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Load-HostConfig {
    $example = Join-Path $HostDir "host_config.example.json"
    if (-not (Test-Path -LiteralPath $CfgPath) -and (Test-Path -LiteralPath $example)) {
        Copy-Item -LiteralPath $example -Destination $CfgPath
    }
    if (Test-Path -LiteralPath $CfgPath) {
        return Get-Content -LiteralPath $CfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return [pscustomobject]@{
        vm_ip   = "192.168.1.100"
        vm_port = 37075
        token   = ""
    }
}

function Install-Antigravity($cfg) {
    $ip = $cfg.vm_ip
    $port = $cfg.vm_port
    $token = $cfg.token

    $mcpDir = Join-Path $env:USERPROFILE ".gemini\antigravity\mcp\vm-agent"
    $schemasSrc = Join-Path $HostDir "antigravity_schemas"
    if (Test-Path -LiteralPath $schemasSrc) {
        New-Item -ItemType Directory -Force -Path $mcpDir | Out-Null
        Get-ChildItem -LiteralPath $mcpDir -Filter "*.json" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        Copy-Item -Path (Join-Path $schemasSrc "*") -Destination $mcpDir -Recurse -Force
        $cnt = (Get-ChildItem -LiteralPath $mcpDir -Filter "*.json").Count
        Write-Host "[+] Antigravity schemas copied ($cnt tools) -> $mcpDir" -ForegroundColor Green
    }

    $antigravityCfg = Join-Path $env:USERPROFILE ".gemini\config\mcp_config.json"
    $json = if (Test-Path -LiteralPath $antigravityCfg) {
        Get-Content -LiteralPath $antigravityCfg -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        [pscustomobject]@{ mcpServers = [pscustomobject]@{} }
    }
    if (-not $json.mcpServers) {
        $json | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([pscustomobject]@{}) -Force
    }

    $entry = [ordered]@{
        url     = "http://${ip}:${port}/mcp"
        headers = [ordered]@{
            Authorization = "Bearer $token"
        }
    }
    $json.mcpServers | Add-Member -MemberType NoteProperty -Name "vm-agent" -Value $entry -Force
    Write-Utf8NoBom $antigravityCfg ($json | ConvertTo-Json -Depth 12)
    Write-Host "[+] Antigravity MCP config updated: $antigravityCfg" -ForegroundColor Green
}

function Install-OpenCode($cfg) {
    $ip = $cfg.vm_ip
    $port = $cfg.vm_port
    $token = $cfg.token

    $opencodeCfg = Join-Path $env:USERPROFILE ".config\opencode\opencode.json"
    $json = if (Test-Path -LiteralPath $opencodeCfg) {
        Get-Content -LiteralPath $opencodeCfg -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        [pscustomobject]@{}
    }
    if (-not $json.mcp) {
        $json | Add-Member -MemberType NoteProperty -Name "mcp" -Value ([pscustomobject]@{}) -Force
    }

    $entry = [ordered]@{
        type    = "remote"
        url     = "http://${ip}:${port}/mcp"
        oauth   = $false
        headers = [ordered]@{
            Authorization = "Bearer $token"
        }
        enabled = $true
    }
    if ($json.mcp.PSObject.Properties["servers"] -and $json.mcp.servers -and $json.mcp.servers.PSObject.Properties["vm-agent"]) {
        $json.mcp.servers.PSObject.Properties.Remove("vm-agent")
    }
    $json.mcp | Add-Member -MemberType NoteProperty -Name "vm-agent" -Value $entry -Force
    Write-Utf8NoBom $opencodeCfg ($json | ConvertTo-Json -Depth 16)
    Write-Host "[+] OpenCode MCP config updated: $opencodeCfg" -ForegroundColor Green
}

function Install-Codex($cfg) {
    $ip = $cfg.vm_ip
    $port = $cfg.vm_port
    $token = $cfg.token

    $codexCfg = Join-Path $env:USERPROFILE ".codex\config.toml"
    $content = if (Test-Path -LiteralPath $codexCfg) {
        Get-Content -LiteralPath $codexCfg -Raw -Encoding UTF8
    } else {
        ""
    }

    $block = "[mcp_servers.vm-agent]`r`nurl = 'http://${ip}:${port}/mcp'`r`nhttp_headers = { Authorization = 'Bearer $token' }"
    if ($content -match '(?m)^\[mcp_servers\.vm-agent\]\s*$') {
        $content = [regex]::Replace(
            $content,
            '(?ms)^\[mcp_servers\.vm-agent\].*?(?=\r?\n\[|\z)',
            $block
        )
    } else {
        $content = $content.TrimEnd() + "`r`n`r`n" + $block + "`r`n"
    }

    Write-Utf8NoBom $codexCfg $content
    Write-Host "[+] Codex config.toml updated: $codexCfg" -ForegroundColor Green
}

function Set-HostConfig {
    $cfg = Load-HostConfig
    Write-Host "Current settings:" -ForegroundColor Cyan
    Write-Host "  IP/Host: $($cfg.vm_ip)"
    Write-Host "  Port:    $($cfg.vm_port)"
    Write-Host "  Token:   $($cfg.token)"
    Write-Host ""

    $newIp = Read-Host "Enter VM/Testbed IP (Enter to keep $($cfg.vm_ip))"
    if ($newIp -and $newIp.Trim()) { $cfg.vm_ip = $newIp.Trim() }

    $newPort = Read-Host "Enter Port (Enter to keep $($cfg.vm_port))"
    if ($newPort -and $newPort.Trim()) { $cfg.vm_port = [int]$newPort.Trim() }

    $newToken = Read-Host "Enter Token (Enter to keep current)"
    if ($newToken -and $newToken.Trim()) { $cfg.token = $newToken.Trim() }

    Write-Utf8NoBom $CfgPath ($cfg | ConvertTo-Json -Depth 5)
    Write-Host "[+] Saved to $CfgPath" -ForegroundColor Green

    $apply = Read-Host "Apply to Antigravity, OpenCode, and Codex now? (Y/n)"
    if ([string]::IsNullOrWhiteSpace($apply) -or $apply -match '^[yY]') {
        Install-Antigravity $cfg
        Install-OpenCode $cfg
        Install-Codex $cfg
    }
}

function Test-AgentConnection($cfg) {
    $url = "http://$($cfg.vm_ip):$($cfg.vm_port)/healthz"
    Write-Host "[*] Checking $url..." -ForegroundColor Cyan
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
        Write-Host "[+] SUCCESS! VM-Ai-Kit agent is online." -ForegroundColor Green
        Write-Host "    Version:  $($resp.version)"
        Write-Host "    Hostname: $($resp.hostname)"
        Write-Host "    User:     $($resp.user)"
        Write-Host "    Session:  $($resp.session)"
        Write-Host "    Elevated: $($resp.elevated)"
        Write-Host "    Uptime:   $($resp.uptime_s)s"
    } catch {
        Write-Host "[-] FAILED to connect to VM-Ai-Kit agent!" -ForegroundColor Red
        Write-Host "    Error: $($_.Exception.Message)"
        Write-Host ""
        Write-Host "Checklist:" -ForegroundColor Yellow
        Write-Host "  1. Is the agent running on the target machine (START_AGENT.bat / VM_Ai_Kit_Agent task)?"
        Write-Host "  2. Is port $($cfg.vm_port) open/forwarded?"
        Write-Host "  3. Is vm_ip correct in host_config.json? (Use SET_IP_AND_TOKEN.bat)"
        exit 1
    }
}

$cfg = Load-HostConfig
switch ($Action) {
    "install_all" {
        Write-Host "Target: http://$($cfg.vm_ip):$($cfg.vm_port)/mcp" -ForegroundColor Cyan
        Install-Antigravity $cfg
        Install-OpenCode $cfg
        Install-Codex $cfg
    }
    "install_antigravity" { Install-Antigravity $cfg }
    "install_opencode"    { Install-OpenCode $cfg }
    "install_codex"       { Install-Codex $cfg }
    "set_config"          { Set-HostConfig }
    "test_connection"     { Test-AgentConnection $cfg }
}
