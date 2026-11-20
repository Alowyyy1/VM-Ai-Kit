<#
.SYNOPSIS
    Adds Microsoft Defender exclusions for analysis directories in the VM.
.DESCRIPTION
    Reversing tools (x64dbg, Scylla, ProcDump, Mimikatz, injectors) and malware samples
    are regularly flagged by Windows Defender. Run this script inside the VM to prevent Defender
    from locking or deleting binaries during analysis.
#>
[CmdletBinding()]
param(
    [string[]]$Paths = @("C:\AgentKit", "C:\Analysis", "C:\d2p191126", "C:\temp")
)

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Must be run as Administrator to configure Defender exclusions."
    return
}

foreach ($p in $Paths) {
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Force -Path $p | Out-Null
    }
    Write-Host "[+] Adding Defender Exclusion: $p"
    Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue
}

Write-Host "[+] Windows Defender exclusions configured successfully."
