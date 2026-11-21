<#
.SYNOPSIS
    Installs AgentKit inside the Windows Virtual Machine for automated analysis.
.DESCRIPTION
    Sets up Python runtime, virtual environment, offline pip packages, reverse-engineering
    toolchain (x64dbg with ScyllaHide and MCP plugin, DIE, PE-bear, capa, Sysinternals),
    configures firewall rules, and creates autostart tasks.
.PARAMETER InstallDir
    Target directory for AgentKit installation (default: C:\AgentKit).
.PARAMETER Port
    TCP port for the MCP Agent server (default: 8765).
.PARAMETER Token
    Authentication token. If omitted, a cryptographically secure 64-hex token is generated.
.PARAMETER Autostart
    Register a scheduled task to start the agent at user logon.
.PARAMETER DefenderExclusions
    Automatically add Windows Defender exclusions for the installation folder.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\AgentKit",
    [int]$Port = 37075,
    [string]$Token = "vm_agent_token_980154022847733770_re",
    [string]$BindAddress = "0.0.0.0",
    [string]$FirewallRemote = "LocalSubnet",
    [switch]$Autostart = $true,
    [switch]$SkipPython,
    [switch]$NoTools,
    [switch]$Force,
    [switch]$DefenderExclusions = $true
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# 1. Elevation check
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Requesting Administrator privileges..." -ForegroundColor Cyan
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"") + $args
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "       AgentKit VM Installer (Reverse Engineering VM)     " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

$Root = Split-Path -Parent $PSCommandPath
Write-Host "[*] Source path: $Root"
Write-Host "[*] Target path: $InstallDir"

# 2. Copy kit to InstallDir
if ((Resolve-Path $Root).Path -ne (Resolve-Path $InstallDir -ErrorAction SilentlyContinue).Path) {
    Write-Host "[*] Deploying files to $InstallDir..."
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    & robocopy.exe $Root $InstallDir /E /XD work cache .git _capa_rules /XF agent.log _out*.txt /NP /R:2 /W:1 | Out-Null
}

# 3. Defender Exclusions
if ($DefenderExclusions) {
    Write-Host "[*] Configuring Defender exclusion for $InstallDir..."
    Add-MpPreference -ExclusionPath $InstallDir -ErrorAction SilentlyContinue
}

# 4. Ensure Python 3.10+
$pythonExe = $null
if (-not $SkipPython) {
    $cands = @("py.exe", "python.exe", "$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
    foreach ($cand in $cands) {
        try {
            $ver = & $cand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -and [float]$ver -ge 3.10) {
                $pythonExe = (Get-Command $cand -ErrorAction SilentlyContinue).Source
                if (-not $pythonExe) { $pythonExe = $cand }
                break
            }
        } catch {}
    }

    if (-not $pythonExe) {
        Write-Host "[*] Python 3.10+ not detected. Installing bundled Python 3.12..." -ForegroundColor Yellow
        $cands = @(
            (Join-Path $InstallDir "installers\python-3.12.10-amd64.exe"),
            (Join-Path $InstallDir "installers\python-3.12.10-amd64.exe\python-3.12.10-amd64.exe")
        )
        $installer = $cands | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1

        if ($installer) {
            Write-Host "[*] Running Python installer: $installer"
            Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
            $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
            $pythonExe = "$env:ProgramFiles\Python312\python.exe"
            if (-not (Test-Path $pythonExe)) {
                $pythonExe = (Get-Command "python.exe" -ErrorAction SilentlyContinue).Source
            }
        } else {
            Write-Warning "Python installer not found. Please install Python manually."
        }
    }
}

if (-not $pythonExe) {
    $pythonExe = "python.exe"
}
Write-Host "[+] Using Python: $pythonExe"

# 4.1 Ensure Node.js
$nodeCmd = Get-Command "node.exe" -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    $nodeMsi = Join-Path $InstallDir "installers\node-v20.18.1-x64.msi"
    if (Test-Path $nodeMsi) {
        Write-Host "[*] Installing Node.js LTS from bundled installer..." -ForegroundColor Yellow
        Start-Process msiexec.exe -ArgumentList "/i `"$nodeMsi`" /qn /norestart" -Wait
        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
        Write-Host "[+] Node.js installed." -ForegroundColor Green
    }
} else {
    Write-Host "[+] Node.js detected: $($nodeCmd.Source)" -ForegroundColor Green
}

# 5. Create Virtual Environment
$venvDir = Join-Path $InstallDir "venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy) -or $Force) {
    Write-Host "[*] Creating Python virtual environment in $venvDir..."
    & $pythonExe -m venv $venvDir
}

# 6. Install offline wheels
$wheelsDir = Join-Path $InstallDir "installers\wheels"
$reqFile = Join-Path $InstallDir "vm_agent\requirements.txt"
if (Test-Path $wheelsDir) {
    Write-Host "[*] Installing Python dependencies from local wheels..."
    & $venvPy -m pip install --no-index --find-links $wheelsDir -r $reqFile --quiet
} else {
    Write-Host "[*] Installing dependencies from PyPI..."
    & $venvPy -m pip install -r $reqFile --quiet
}

# 7. Configure Plugins for x64dbg
Write-Host "[*] Verifying x64dbg plugins (ScyllaHide & MCP automation)..."
$x64PluginDir = Join-Path $InstallDir "tools\bin\x64dbg\x64\plugins"
$x32PluginDir = Join-Path $InstallDir "tools\bin\x64dbg\x32\plugins"
New-Item -ItemType Directory -Force -Path $x64PluginDir, $x32PluginDir | Out-Null

$scyllaSrc = Join-Path $InstallDir "tools\bin\scyllahide\x64dbg"
if (Test-Path "$scyllaSrc\x64\plugins") {
    Copy-Item "$scyllaSrc\x64\plugins\*" $x64PluginDir -Force
}
if (Test-Path "$scyllaSrc\x32\plugins") {
    Copy-Item "$scyllaSrc\x32\plugins\*" $x32PluginDir -Force
}

$mcpSrc = Join-Path $InstallDir "tools\bin\x64dbg_mcp"
if (Test-Path "$mcpSrc\x64dbg_mcp.dp64") {
    Copy-Item "$mcpSrc\x64dbg_mcp.dp64" $x64PluginDir -Force
}
if (Test-Path "$mcpSrc\x64dbg_mcp.dp32") {
    Copy-Item "$mcpSrc\x64dbg_mcp.dp32" $x32PluginDir -Force
}

# 8. Token generation & config
$cfgFile = Join-Path $InstallDir "agent.json"
if (-not $Token) {
    if (Test-Path $cfgFile) {
        $existing = Get-Content $cfgFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($existing -and $existing.token) {
            $Token = $existing.token
        }
    }
    if (-not $Token) {
        $rngBytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rngBytes)
        $Token = ([BitConverter]::ToString($rngBytes) -replace '-','').ToLower()
    }
}

$agentConfig = [ordered]@{
    host = $BindAddress
    port = $Port
    token = $Token
    stateless = $true
    work_dir = (Join-Path $InstallDir "work")
    tools_dir = (Join-Path $InstallDir "tools\bin")
    x64dbg_dir = (Join-Path $InstallDir "tools\bin\x64dbg")
    x64dbg_host = "127.0.0.1"
    x64dbg_port = 27042
    x64dbg_token = ""
    allow_roots = @($InstallDir, "C:\Analysis", "C:\d2p191126", "C:\temp")
    protected_paths = @("C:\Windows", "C:\Program Files", "C:\Program Files (x86)")
    allow_protected_writes = $false
    read_only = $false
    max_chunk_bytes = 3145728
    max_read_bytes = 4194304
    exec_timeout_default = 60
    exec_timeout_max = 1800
    debug_timeout = 600
    log_level = "INFO"
    log_keep_days = 7
}

$agentConfig | ConvertTo-Json -Depth 5 | Set-Content $cfgFile -Encoding UTF8
if ((Resolve-Path $Root).Path -ne (Resolve-Path $InstallDir -ErrorAction SilentlyContinue).Path) {
    $agentConfig | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root "agent.json") -Encoding UTF8 -ErrorAction SilentlyContinue
}
Write-Host "[+] Agent configuration written to $cfgFile" -ForegroundColor Green

# 9. Firewall configuration
Write-Host "[*] Configuring Windows Firewall for port $Port..."
Remove-NetFirewallRule -DisplayName "AgentKit MCP $Port" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "AgentKit MCP $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -RemoteAddress $FirewallRemote -Profile Private,Domain | Out-Null

# 10. Autostart Scheduled Task
if ($Autostart) {
    Write-Host "[*] Registering autostart scheduled task..."
    $taskName = "AgentKit_MCP"
    $startScript = Join-Path $InstallDir "start-agent.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principalTask = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principalTask -Force | Out-Null
    Write-Host "[+] Scheduled task '$taskName' registered."
}

# 11. Desktop Shortcuts
$desktop = [Environment]::GetFolderPath("Desktop")
$wsh = New-Object -ComObject WScript.Shell
$scStart = $wsh.CreateShortcut((Join-Path $desktop "AgentKit - Start MCP.lnk"))
$scStart.TargetPath = "powershell.exe"
$scStart.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\start-agent.ps1`" -Foreground"
$scStart.WorkingDirectory = $InstallDir
$scStart.Save()

$scDir = $wsh.CreateShortcut((Join-Path $desktop "AgentKit - Directory.lnk"))
$scDir.TargetPath = "explorer.exe"
$scDir.Arguments = $InstallDir
$scDir.Save()

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "                Installation Complete!                   " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Agent Port:  $Port"
Write-Host "Agent Token: $Token" -ForegroundColor Yellow
Write-Host ""
Write-Host "To start the agent manually:"
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File `"$InstallDir\start-agent.ps1`""
Write-Host ""
Write-Host "Host MCP Configuration snippet:"
Write-Host @"
{
  "mcpServers": {
    "vm-agent": {
      "command": "python",
      "args": ["-m", "vm_agent.server", "--connect", "http://127.0.0.1:$Port", "--token", "$Token"]
    }
  }
}
"@ -ForegroundColor Cyan
