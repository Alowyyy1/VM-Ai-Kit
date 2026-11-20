<#
.SYNOPSIS
    Starts the AgentKit MCP bridge server.
.PARAMETER Foreground
    Runs the agent in the current console window instead of the background.
#>
[CmdletBinding()]
param(
    [switch]$Foreground
)

$Root = $PSScriptRoot
$cfgFile = if (Test-Path "$Root\agent.json") { "$Root\agent.json" } else { "$Root\config\agent.json" }
if (-not (Test-Path $cfgFile)) {
    Write-Warning "agent.json not found in $Root. Run install-vm.ps1 first."
    return
}

$cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json
$port = $cfg.port
$py = if (Test-Path "$Root\venv\Scripts\python.exe") { "$Root\venv\Scripts\python.exe" } else { "python.exe" }

# Check if already running
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) {
        Write-Host "[+] AgentKit is already running on port $port." -ForegroundColor Green
        return
    }
} catch {}

$workDir = if ($cfg.work_dir) { $cfg.work_dir } else { Join-Path $Root "work" }
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$logFile = Join-Path $workDir "agent.log"

Write-Host "[*] Launching AgentKit MCP server on port $port..." -ForegroundColor Cyan

if ($Foreground) {
    Write-Host "[*] Running in foreground. Press Ctrl+C to stop."
    & $py -m vm_agent.server --config $cfgFile
} else {
    $startArgs = "-m vm_agent.server --config `"$cfgFile`""
    Start-Process -FilePath $py -ArgumentList $startArgs -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError $logFile
    Start-Sleep -Seconds 2

    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) {
            Write-Host "[+] AgentKit successfully started in background on port $port!" -ForegroundColor Green
            Write-Host "[+] Log output: $logFile"
        }
    } catch {
        Write-Warning "Agent started, but health check failed. Check logs at: $logFile"
    }
}
