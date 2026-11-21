<#
.SYNOPSIS
    Stops any running instances of AgentKit MCP server and its supervisor task.
#>
[CmdletBinding()]
param()

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "[*] Stopping scheduled supervisor task (if running)..."
foreach ($taskName in @("VM_Ai_Kit_Agent", "AgentKit_MCP", "VM_Ai_Kit_Logon")) {
    $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($t -and $t.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
}

Write-Host "[*] Terminating supervisor cmd and vm_agent.server processes..."
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*vm_agent.server*" -or $_.CommandLine -like "*run_agent.bat*"
}

if ($procs) {
    foreach ($p in $procs) {
        Write-Host "[*] Terminating PID $($p.ProcessId) ($($p.Name))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[+] AgentKit stopped." -ForegroundColor Green
} else {
    Write-Host "[*] No active AgentKit processes found."
}
