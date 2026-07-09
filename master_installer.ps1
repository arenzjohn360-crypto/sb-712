<#
.SYNOPSIS
    SB-712 Master Installer — installs all components on Windows 10+

.DESCRIPTION
    Installs the full SB-712 stack from the SB712_MASTER canonical folder:
      • sb_712   — core package (security, system, recovery, …)
      • sb688    — storage engine (WAL, replicas, Merkle, crypto)
      • stitch_brick — validation framework
      • intelligence / recovery layers
      • Registers SB712SecurityHost as a Windows Service (NSSM or sc.exe)
      • Registers SB712Watchdog as a Task Scheduler task (logon trigger)
      • Copies .env.example → .env if no .env present

.PARAMETER SourceRoot
    Path to the SB712_MASTER folder (default: folder containing this script).

.PARAMETER InstallRoot
    Target installation directory (default: %ProgramFiles%\SB712\system).

.PARAMETER PythonExe
    Python executable (default: py). Change to 'python3' on systems without
    the Python Launcher.

.PARAMETER ServiceName
    Windows Service name for the SB-712 Security Host
    (default: SB712SecurityHost).

.PARAMETER WatchdogTask
    Task Scheduler task name for the watchdog (default: SB712Watchdog).

.PARAMETER SkipService
    If set, skip Windows Service registration (useful for non-admin installs).

.PARAMETER SkipWatchdog
    If set, skip Task Scheduler watchdog registration.

.EXAMPLE
    .\master_installer.ps1
    .\master_installer.ps1 -InstallRoot "D:\SB712" -PythonExe python3
    .\master_installer.ps1 -SkipService -SkipWatchdog
#>

param(
    [string]$SourceRoot   = (Resolve-Path $PSScriptRoot).Path,
    [string]$InstallRoot  = "$env:ProgramFiles\SB712\system",
    [string]$PythonExe    = "py",
    [string]$ServiceName  = "SB712SecurityHost",
    [string]$WatchdogTask = "SB712Watchdog",
    [switch]$SkipService,
    [switch]$SkipWatchdog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── helpers ──────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) {
    Write-Host "`n[SB-712] $msg" -ForegroundColor Cyan
}

function Write-OK([string]$msg) {
    Write-Host "    ✓ $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "    ⚠ $msg" -ForegroundColor Yellow
}

function Require-Admin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object System.Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run as Administrator (right-click → Run as administrator)."
    }
}

# ── pre-flight ────────────────────────────────────────────────────────────────

Write-Step "Pre-flight checks"

if (-not ($SkipService -and $SkipWatchdog)) {
    Require-Admin
    Write-OK "Running as administrator"
}

# Verify Python
try {
    $pyVer = & $PythonExe --version 2>&1
    Write-OK "Python found: $pyVer"
} catch {
    throw "Python executable '$PythonExe' not found. Install Python 3.10+ from https://python.org and retry."
}

# Verify source
$masterSrc = Join-Path $SourceRoot "SB712_MASTER"
if (-not (Test-Path $masterSrc)) {
    # Fallback: SourceRoot IS the master folder
    $masterSrc = $SourceRoot
}
if (-not (Test-Path (Join-Path $masterSrc "sb_712"))) {
    throw "Cannot find sb_712 package under '$masterSrc'. Run this script from the repo root or SB712_MASTER folder."
}
Write-OK "Source root: $masterSrc"

# ── install directory ─────────────────────────────────────────────────────────

Write-Step "Creating install directory: $InstallRoot"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Write-OK "Directory ready"

# ── copy sources ──────────────────────────────────────────────────────────────

Write-Step "Copying production files"
$copyDirs  = @("sb_712","sb688","stitch_brick","intelligence","recovery")
$copyFiles = @("run_validation.py","run_sb712_ironbraid.py","pyproject.toml","requirements.txt")

foreach ($d in $copyDirs) {
    $src = Join-Path $masterSrc $d
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $InstallRoot -Recurse -Force
        Write-OK "Copied $d/"
    } else {
        Write-Warn "$d/ not found in source — skipped"
    }
}

foreach ($file in $copyFiles) {
    $src = Join-Path $masterSrc $file
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $InstallRoot -Force
        Write-OK "Copied $file"
    } else {
        Write-Warn "$file not found in source — skipped"
    }
}

# ── .env ──────────────────────────────────────────────────────────────────────

Write-Step "Environment file"
$envDest    = Join-Path $InstallRoot ".env"
$envExample = Join-Path $SourceRoot  ".env.example"

if (-not (Test-Path $envDest)) {
    if (Test-Path $envExample) {
        Copy-Item -Path $envExample -Destination $envDest -Force
        Write-OK ".env created from .env.example — EDIT before first run"
    } else {
        Set-Content -Path $envDest -Value "# SB-712 environment — add your keys here`n"
        Write-OK ".env stub created — EDIT before first run"
    }
} else {
    Write-OK ".env already present — not overwritten"
}

# ── Python packages ───────────────────────────────────────────────────────────

Write-Step "Installing Python dependencies"
$reqFile = Join-Path $InstallRoot "requirements.txt"
if (Test-Path $reqFile) {
    & $PythonExe -m pip install -r $reqFile --quiet
    Write-OK "requirements.txt installed"
}
& $PythonExe -m pip install $InstallRoot --quiet
Write-OK "Package installed in development mode"

# ── Windows Service ───────────────────────────────────────────────────────────

if (-not $SkipService) {
    Write-Step "Registering Windows Service: $ServiceName"

    $binaryPath = "`"$PythonExe`" -m sb_712.service_host --env-file `"$envDest`""

    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
        sc.exe delete $ServiceName | Out-Null
        Start-Sleep -Seconds 2
        Write-OK "Removed previous service instance"
    }

    New-Service -Name $ServiceName `
        -BinaryPathName $binaryPath `
        -DisplayName    "SB-712 Security Host" `
        -Description    "SB-712 verification, trace logging, and trust ledger host" `
        -StartupType    Automatic | Out-Null

    Start-Service -Name $ServiceName
    Write-OK "Service '$ServiceName' installed and started"
} else {
    Write-Warn "SkipService set — Windows Service not registered"
}

# ── Task Scheduler watchdog ───────────────────────────────────────────────────

if (-not $SkipWatchdog) {
    Write-Step "Registering Task Scheduler watchdog: $WatchdogTask"

    $watchdogScript = Join-Path $SourceRoot "sb712_watchdog.py"
    if (-not (Test-Path $watchdogScript)) {
        $watchdogScript = Join-Path $InstallRoot "sb712_watchdog.py"
    }

    if (Test-Path $watchdogScript) {
        $action  = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$watchdogScript`""
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                                                  -RestartCount 3 `
                                                  -RestartInterval (New-TimeSpan -Minutes 1)
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

        Unregister-ScheduledTask -TaskName $WatchdogTask -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $WatchdogTask `
                               -Action $action `
                               -Trigger $trigger `
                               -Settings $settings `
                               -Principal $principal `
                               -Description "SB-712 triple-strand watchdog (runs at logon)" | Out-Null
        Write-OK "Task '$WatchdogTask' registered (runs at logon, SYSTEM, no time limit)"
    } else {
        Write-Warn "sb712_watchdog.py not found — watchdog task not registered"
    }
} else {
    Write-Warn "SkipWatchdog set — Task Scheduler task not registered"
}

# ── heartbeat check ───────────────────────────────────────────────────────────

Write-Step "Heartbeat verification"
try {
    Push-Location $InstallRoot
    $result = & $PythonExe -m sb_712.service_host --heartbeat-once 2>&1
    Pop-Location
    Write-OK "Heartbeat: $result"
} catch {
    Write-Warn "Heartbeat check failed (service may need a moment to start): $_"
}

# ── done ──────────────────────────────────────────────────────────────────────

Write-Host "`n╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host   "║  SB-712 Master Install COMPLETE              ║" -ForegroundColor Green
Write-Host   "╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host "`nInstall path : $InstallRoot"
Write-Host "Service      : $ServiceName  (sc query $ServiceName)"
Write-Host "Watchdog     : $WatchdogTask  (schtasks /query /tn $WatchdogTask)"
Write-Host "Validate     : cd '$InstallRoot' ; $PythonExe run_validation.py --tests 50`n"
