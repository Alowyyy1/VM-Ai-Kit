<#
.SYNOPSIS
    Runs local smoke tests for AgentKit.
#>
[CmdletBinding()]
param(
    [string]$Config = "C:\AgentKit\agent.json",
    [switch]$Full
)

$root = Split-Path -Parent $PSScriptRoot
$cfgPath = if (Test-Path $Config) { $Config } else { Join-Path $root "config\agent.json" }

if (-not (Test-Path $cfgPath)) {
    Write-Warning "Configuration file not found: $cfgPath"
    return
}

$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$url = "http://127.0.0.1:$($cfg.port)/mcp"
$token = $cfg.token

Write-Host "[*] Running AgentKit MCP Selftest against $url..."
$py = if (Test-Path "C:\AgentKit\venv\Scripts\python.exe") { "C:\AgentKit\venv\Scripts\python.exe" } else { "python" }

$argsList = @((Join-Path $PSScriptRoot "test_mcp.py"), "--url", $url, "--token", $token)
if ($Full) { $argsList += "--full" }

& $py $argsList
