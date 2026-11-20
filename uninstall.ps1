<#
.SYNOPSIS
    Uninstalls AgentKit tasks, firewall rules, and desktop shortcuts.
#>
[CmdletBinding()]
param(
    [switch]$PurgeFiles
)

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Run as Administrator to cleanly remove tasks and firewall rules."
}

Write-Host "[*] Stopping AgentKit..."
& (Join-Path $PSScriptRoot "stop-agent.ps1")

Write-Host "[*] Removing scheduled task..."
Unregister-ScheduledTask -TaskName "AgentKit_MCP" -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[*] Removing firewall rules..."
Remove-NetFirewallRule -DisplayName "AgentKit MCP *" -ErrorAction SilentlyContinue

Write-Host "[*] Removing desktop shortcuts..."
$desktop = [Environment]::GetFolderPath("Desktop")
Remove-Item (Join-Path $desktop "AgentKit - *.lnk") -Force -ErrorAction SilentlyContinue

if ($PurgeFiles) {
    Write-Host "[*] Purging C:\AgentKit directory..."
    Remove-Item "C:\AgentKit" -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[+] AgentKit uninstalled." -ForegroundColor Green
