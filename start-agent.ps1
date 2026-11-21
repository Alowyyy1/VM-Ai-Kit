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

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = $PSScriptRoot
$cfgFile = if (Test-Path "$Root\agent.json") { "$Root\agent.json" } elseif (Test-Path "C:\AgentKit\agent.json") { "C:\AgentKit\agent.json" } else { "$Root\config\agent.json" }
if (-not (Test-Path $cfgFile)) {
    Write-Warning "agent.json not found in $Root or C:\AgentKit. Run install-vm.ps1 first."
    return
}

$cfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
$port = if ($cfg.port) { [int]$cfg.port } else { 37075 }
$py = if (Test-Path "$Root\venv\Scripts\python.exe") { "$Root\venv\Scripts\python.exe" } elseif (Test-Path "C:\AgentKit\venv\Scripts\python.exe") { "C:\AgentKit\venv\Scripts\python.exe" } else { "python.exe" }

# Check if already running and healthy
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) {
        Write-Host "[+] AgentKit is already running and healthy on port $port." -ForegroundColor Green
        return
    }
} catch {}

# Clean any stuck vm_agent.server instances before starting a fresh one
$stuck = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*vm_agent.server*" }
foreach ($p in $stuck) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

$workDir = if ($cfg.work_dir) { $cfg.work_dir } else { Join-Path $Root "work" }
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$logFile = Join-Path $workDir "agent_stdout.log"
$errFile = Join-Path $workDir "agent_err.log"

$env:PYTHONPATH = $Root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[*] Launching AgentKit MCP server on port $port..." -ForegroundColor Cyan

if ($Foreground) {
    Write-Host "[*] Running in foreground. Press Ctrl+C to stop."
    & $py -m vm_agent.server --config $cfgFile
} else {
    $startArgs = "-m vm_agent.server --config `"$cfgFile`""
    Start-Process -FilePath $py -ArgumentList $startArgs -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError $errFile
    Start-Sleep -Seconds 2

    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Host "[+] AgentKit successfully started in background on port $port!" -ForegroundColor Green
            Write-Host "[+] Log output: $workDir\agent.log"
        }
    } catch {
        Write-Warning "Agent started, but health check failed. Check logs at: $workDir\agent.log and $errFile"
    }
}
