<#
.SYNOPSIS
    Installs AgentKit (VM-Ai-Kit) inside the Windows analysis machine.
.DESCRIPTION
    Deploys files to C:\AgentKit, sets up Python venv & dependencies (including mitmproxy),
    verifies VC++ Redistributable, configures x64dbg plugins without overwriting custom
    scylla_hide.ini, configures firewall, registers reliable logon autostart + watchdog tasks,
    and creates clean desktop shortcuts (safe for Cyrillic/Unicode user profiles).
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\AgentKit",
    [int]$Port = 37075,
    [string]$Token = "",
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
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

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
Write-Host "      VM-Ai-Kit Installer (Analysis Machine / VM)         " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

$Root = Split-Path -Parent $PSCommandPath
Write-Host "[*] Source path: $Root"
Write-Host "[*] Target path: $InstallDir"

# 2. Deploy kit to InstallDir (preserve runtime config, venv, tools\bin, work, BCD files)
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$resolvedTarget = $InstallDir.TrimEnd('\')
if (Test-Path -LiteralPath $InstallDir) {
    $resolvedTarget = (Resolve-Path -LiteralPath $InstallDir).Path.TrimEnd('\')
}

if ($resolvedRoot.ToLowerInvariant() -ne $resolvedTarget.ToLowerInvariant()) {
    Write-Host "[*] Deploying files to $InstallDir..."
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    & robocopy.exe $Root $InstallDir /E /XD work cache .git _capa_rules venv /XF agent.log agent.json _out*.txt /NP /R:2 /W:1 | Out-Null
}

# 3. Defender Exclusions
if ($DefenderExclusions) {
    Write-Host "[*] Configuring Defender exclusion for $InstallDir..."
    Add-MpPreference -ExclusionPath $InstallDir -ErrorAction SilentlyContinue
}

# 3.1 Verify VC++ Redistributable 2015-2022 (x64 & x86)
$vcDll64 = "C:\Windows\System32\vcruntime140.dll"
$vcDll86 = "C:\Windows\SysWOW64\vcruntime140.dll"
if (-not (Test-Path $vcDll64) -or -not (Test-Path $vcDll86)) {
    Write-Host "[*] Visual C++ Redistributable missing. Attempting silent install..." -ForegroundColor Yellow
    $dlDir = Join-Path $InstallDir "work\dl"
    New-Item -ItemType Directory -Force -Path $dlDir | Out-Null
    foreach ($arch in @(
        @{ Url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"; File = "vc_redist.x64.exe"; Check = $vcDll64 },
        @{ Url = "https://aka.ms/vs/17/release/vc_redist.x86.exe"; File = "vc_redist.x86.exe"; Check = $vcDll86 }
    )) {
        if (-not (Test-Path $arch.Check)) {
            $dst = Join-Path $dlDir $arch.File
            try {
                Invoke-WebRequest -Uri $arch.Url -OutFile $dst -UseBasicParsing -TimeoutSec 60
                Start-Process -FilePath $dst -ArgumentList "/install /quiet /norestart" -Wait
                Remove-Item $dst -Force -ErrorAction SilentlyContinue
                Write-Host "[+] Installed $($arch.File)" -ForegroundColor Green
            } catch {
                Write-Warning "Could not download/install $($arch.File) automatically: $($_.Exception.Message)"
            }
        }
    }
} else {
    Write-Host "[+] Visual C++ Redistributable x64/x86 present." -ForegroundColor Green
}

# 4. Ensure Python 3.10+
$pythonExe = $null
if (-not $SkipPython) {
    $cands = @(
        "C:\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "python.exe",
        "py.exe"
    )
    foreach ($cand in $cands) {
        try {
            $ver = & $cand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.10") {
                $cmdInfo = Get-Command $cand -ErrorAction SilentlyContinue
                $pythonExe = if ($cmdInfo) { $cmdInfo.Source } else { $cand }
                break
            }
        } catch {}
    }

    if (-not $pythonExe) {
        Write-Host "[*] Python 3.10+ not detected. Installing bundled Python 3.12..." -ForegroundColor Yellow
        $instCands = @(
            (Join-Path $InstallDir "installers\python-3.12.10-amd64.exe"),
            (Join-Path $InstallDir "installers\python-3.12.10-amd64.exe\python-3.12.10-amd64.exe")
        )
        $installer = $instCands | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
        if ($installer) {
            Write-Host "[*] Running Python installer: $installer"
            Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
            $pythonExe = "$env:ProgramFiles\Python312\python.exe"
            if (-not (Test-Path $pythonExe)) {
                $pythonExe = (Get-Command "python.exe" -ErrorAction SilentlyContinue).Source
            }
        } else {
            Write-Warning "Python installer not found. Please install Python 3.10+ manually."
        }
    }
}
if (-not $pythonExe) {
    $pythonExe = if (Test-Path "C:\Python312\python.exe") { "C:\Python312\python.exe" } else { "python.exe" }
}
Write-Host "[+] Using Python: $pythonExe"

# 4.1 Ensure Node.js
$nodeCmd = Get-Command "node.exe" -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    $nodeMsi = Join-Path $InstallDir "installers\node-v20.18.1-x64.msi"
    if (Test-Path $nodeMsi) {
        Write-Host "[*] Installing Node.js LTS from bundled installer..." -ForegroundColor Yellow
        Start-Process msiexec.exe -ArgumentList "/i `"$nodeMsi`" /qn /norestart" -Wait
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
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

# 6. Install Python packages (offline wheels first, then PyPI for any extras like mitmproxy)
$wheelsDir = Join-Path $InstallDir "installers\wheels"
$reqFile = Join-Path $InstallDir "vm_agent\requirements.txt"
$needInstall = $Force
if (-not $needInstall) {
    & $venvPy -c "import mcp, mss, PIL, psutil, pefile, capstone, mitmproxy" 2>$null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
}
if ($needInstall) {
    if (Test-Path $wheelsDir) {
        Write-Host "[*] Installing base dependencies from local wheels..."
        & $venvPy -m pip install --no-index --find-links $wheelsDir mcp mss pillow psutil pefile capstone --quiet
    }
    Write-Host "[*] Installing remaining dependencies from requirements.txt..."
    & $venvPy -m pip install -r $reqFile --quiet
} else {
    Write-Host "[+] All Python dependencies (including mitmproxy) already installed in venv." -ForegroundColor Green
}

# 7. Configure Plugins for x64dbg (preserve existing scylla_hide.ini if customized)
Write-Host "[*] Verifying x64dbg plugins (ScyllaHide & MCP automation)..."
$x64PluginDir = Join-Path $InstallDir "tools\bin\x64dbg\x64\plugins"
$x32PluginDir = Join-Path $InstallDir "tools\bin\x64dbg\x32\plugins"
New-Item -ItemType Directory -Force -Path $x64PluginDir, $x32PluginDir | Out-Null

$scyllaSrc = Join-Path $InstallDir "tools\bin\scyllahide\x64dbg"
foreach ($archPair in @(
    @{ Src = "$scyllaSrc\x64\plugins"; Dst = $x64PluginDir },
    @{ Src = "$scyllaSrc\x32\plugins"; Dst = $x32PluginDir }
)) {
    if (Test-Path $archPair.Src) {
        Get-ChildItem $archPair.Src -File | ForEach-Object {
            $dstFile = Join-Path $archPair.Dst $_.Name
            if ($_.Name -ieq "scylla_hide.ini" -and (Test-Path $dstFile)) {
                return
            }
            Copy-Item $_.FullName $dstFile -Force
        }
    }
}

$mcpSrc = Join-Path $InstallDir "tools\bin\x64dbg_mcp"
if (Test-Path "$mcpSrc\x64dbg_mcp.dp64") {
    Copy-Item "$mcpSrc\x64dbg_mcp.dp64" $x64PluginDir -Force
}
if (Test-Path "$mcpSrc\x64dbg_mcp.dp32") {
    Copy-Item "$mcpSrc\x64dbg_mcp.dp32" $x32PluginDir -Force
}

# 8. Token generation & config (UTF-8 without BOM)
$cfgFile = Join-Path $InstallDir "agent.json"
$existingCfg = $null
if (Test-Path $cfgFile) {
    try { $existingCfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
}

if (-not $Token) {
    if ($existingCfg -and $existingCfg.token) {
        $Token = $existingCfg.token
    } else {
        $rngBytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rngBytes)
        $Token = ([BitConverter]::ToString($rngBytes) -replace '-', '').ToLower()
    }
}

$allowRoots = if ($existingCfg -and $existingCfg.allow_roots) {
    @($existingCfg.allow_roots)
} else {
    @($InstallDir, "C:\Analysis", "C:\d2p191126", "C:\temp")
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
    allow_roots = $allowRoots
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

Write-Utf8NoBom $cfgFile ($agentConfig | ConvertTo-Json -Depth 5)
Write-Host "[+] Agent configuration written (UTF-8 no BOM) to $cfgFile" -ForegroundColor Green

# 9. Firewall configuration & Power Plan (prevent sleep on physical testbeds)
Write-Host "[*] Configuring Windows Firewall for port $Port (Any profile, scoped to $FirewallRemote)..."
Remove-NetFirewallRule -DisplayName "AgentKit MCP *" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "AgentKit MCP $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -RemoteAddress $FirewallRemote -Profile Any | Out-Null

Write-Host "[*] Disabling AC standby/hibernation sleep..."
try {
    & powercfg.exe /change standby-timeout-ac 0 | Out-Null
    & powercfg.exe /change hibernate-timeout-ac 0 | Out-Null
} catch {}

# 10. Desktop Shortcuts (Unicode/Cyrillic profile safe: save to ASCII temp path then copy via .NET)
$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop -and (Test-Path -LiteralPath $desktop)) {
    Write-Host "[*] Updating desktop shortcuts in: $desktop"
    Get-ChildItem -LiteralPath $desktop -Filter "*.lnk" -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "AgentKit - *.lnk" -or $_.Name -like "VM-Ai-Kit - *.lnk" -or $_.Name -like "Start-VM-Ai-Kit*.lnk"
    } | Remove-Item -Force -ErrorAction SilentlyContinue

    $wsh = New-Object -ComObject WScript.Shell
    $workTmp = Join-Path $InstallDir "work"
    New-Item -ItemType Directory -Force -Path $workTmp | Out-Null

    function Save-DesktopShortcut([string]$Name, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Desc) {
        $tmpLnk = Join-Path $workTmp "_tmp_shortcut.lnk"
        if (Test-Path -LiteralPath $tmpLnk) { Remove-Item -LiteralPath $tmpLnk -Force }
        $sc = $wsh.CreateShortcut($tmpLnk)
        $sc.TargetPath = $Target
        $sc.Arguments = $Arguments
        $sc.WorkingDirectory = $WorkDir
        $sc.Description = $Desc
        $sc.Save()
        $dstLnk = Join-Path $desktop $Name
        [System.IO.File]::Copy($tmpLnk, $dstLnk, $true)
        Remove-Item -LiteralPath $tmpLnk -Force -ErrorAction SilentlyContinue
    }

    Save-DesktopShortcut "VM-Ai-Kit - Start Agent.lnk" "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\start-agent.ps1`" -Foreground" $InstallDir "Start VM-Ai-Kit MCP Agent in foreground console"
    Save-DesktopShortcut "VM-Ai-Kit - Stop Agent.lnk" "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\stop-agent.ps1`"" $InstallDir "Stop VM-Ai-Kit MCP Agent"
    Save-DesktopShortcut "VM-Ai-Kit - Directory.lnk" "explorer.exe" "`"$InstallDir`"" $InstallDir "Open VM-Ai-Kit installation directory"

    Write-Host "[+] Desktop shortcuts created cleanly." -ForegroundColor Green
} else {
    Write-Warning "Desktop folder could not be resolved; skipping shortcuts."
}

# 11. Clean legacy tasks & Register Reliable Autostart + Watchdog Scheduled Tasks
if ($Autostart) {
    Write-Host "[*] Registering VM_Ai_Kit_Agent + VM_Ai_Kit_Watchdog..."
    foreach ($oldTask in @("AgentKit_MCP", "VM_Ai_Kit_Logon")) {
        Unregister-ScheduledTask -TaskName $oldTask -Confirm:$false -ErrorAction SilentlyContinue
    }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $runBat = Join-Path $InstallDir "run_agent.bat"
    $watchdogPs = Join-Path $InstallDir "watchdog.ps1"

    $agentAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$runBat`"`"" -WorkingDirectory $InstallDir
    $agentTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $agentPrincipal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
    $agentSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "VM_Ai_Kit_Agent" -Action $agentAction -Trigger $agentTrigger -Principal $agentPrincipal -Settings $agentSettings -Force | Out-Null

    $wdAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogPs`"" -WorkingDirectory $InstallDir
    $wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $wdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "VM_Ai_Kit_Watchdog" -Action $wdAction -Trigger $wdTrigger -Principal $agentPrincipal -Settings $wdSettings -Force | Out-Null

    Write-Host "[+] Scheduled tasks 'VM_Ai_Kit_Agent' (AtLogOn) and 'VM_Ai_Kit_Watchdog' (every 5m) registered for $currentUser." -ForegroundColor Green
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "                Installation Complete!                   " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Agent Port:  $Port"
Write-Host "Agent Token: $Token" -ForegroundColor Yellow
