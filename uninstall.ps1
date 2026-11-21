<#
.SYNOPSIS
    Uninstalls AgentKit tasks, firewall rules, and desktop shortcuts.
#>
[CmdletBinding()]
param(
    [switch]$PurgeFiles
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Run as Administrator to cleanly remove tasks and firewall rules."
}

Write-Host "[*] Stopping AgentKit..."
& (Join-Path $PSScriptRoot "stop-agent.ps1")

Write-Host "[*] Removing scheduled tasks..."
foreach ($taskName in @("AgentKit_MCP", "VM_Ai_Kit_Logon", "VM_Ai_Kit_Agent", "VM_Ai_Kit_Watchdog")) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}

Write-Host "[*] Removing firewall rules..."
Remove-NetFirewallRule -DisplayName "AgentKit MCP *" -ErrorAction SilentlyContinue

Write-Host "[*] Removing desktop shortcuts..."
$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop -and (Test-Path -LiteralPath $desktop)) {
    Get-ChildItem -LiteralPath $desktop -Filter "*.lnk" -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "AgentKit - *.lnk" -or $_.Name -like "VM-Ai-Kit - *.lnk" -or $_.Name -like "Start-VM-Ai-Kit*.lnk"
    } | Remove-Item -Force -ErrorAction SilentlyContinue
}

if ($PurgeFiles) {
    Write-Host "[*] Purging C:\AgentKit directory..."
    Remove-Item "C:\AgentKit" -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[+] AgentKit uninstalled." -ForegroundColor Green
