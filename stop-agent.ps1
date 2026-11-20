<#
.SYNOPSIS
    Stops any running instances of AgentKit MCP server.
#>
[CmdletBinding()]
param()

Write-Host "[*] Searching for running AgentKit instances..."
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*vm_agent.server*" }

if ($procs) {
    foreach ($p in $procs) {
        Write-Host "[*] Terminating PID $($p.ProcessId)..."
        Stop-Process -Id $p.ProcessId -Force
    }
    Write-Host "[+] AgentKit stopped." -ForegroundColor Green
} else {
    Write-Host "[*] No active AgentKit processes found."
}
