$Root = $PSScriptRoot
$cfgFile = Join-Path $Root "agent.json"
$port = 37075
if (Test-Path $cfgFile) {
    try {
        $cfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.port) { $port = [int]$cfg.port }
    } catch {}
}

$healthUrl = "http://127.0.0.1:$port/healthz"
$workDir = Join-Path $Root "work"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$logFile = Join-Path $workDir "watchdog.log"

function Write-Log([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [WATCHDOG] $msg"
    [System.IO.File]::AppendAllText($logFile, $line + "`r`n", [System.Text.UTF8Encoding]::new($false))
}

function Test-AgentHealth([int]$timeoutSec = 8) {
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec $timeoutSec -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (Test-AgentHealth 8) {
    exit 0
}

# If first attempt failed, retry after 5 seconds before concluding it's dead
Start-Sleep -Seconds 5
if (Test-AgentHealth 10) {
    exit 0
}

# Still failing after retry - check if there are running python processes
$pyProcesses = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*vm_agent.server*" }
if (-not $pyProcesses) {
    Write-Log "Agent not running. Starting VM_Ai_Kit_Agent scheduled task..."
    Start-ScheduledTask -TaskName "VM_Ai_Kit_Agent" -ErrorAction SilentlyContinue
    exit 0
}

# Check if any long-running tool child processes are running (capa, pe-sieve, x64dbg, etc.)
$children = Get-CimInstance Win32_Process | Where-Object {
    $parentPid = $_.ParentProcessId
    ($pyProcesses | Where-Object { $_.ProcessId -eq $parentPid }) -and
    ($_.Name -in @("capa.exe", "pe-sieve64.exe", "hollows_hunter64.exe", "x64dbg.exe", "x96dbg.exe", "mitmdump.exe", "mitmweb.exe", "powershell.exe", "cmd.exe"))
}
if ($children) {
    Write-Log "Agent is busy with child process ($($children.Name -join ', ')). Skipping restart."
    exit 0
}

Write-Log "Health check failed twice (agent not responding on port $port). Stopping unresponsive server..."
foreach ($p in $pyProcesses) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "VM_Ai_Kit_Agent" -ErrorAction SilentlyContinue
