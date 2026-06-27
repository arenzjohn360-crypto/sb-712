param(
    [string]$ServiceName = "SB712SecurityHost",
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$InstallRoot = "$env:ProgramFiles\SB712\system",
    [string]$PythonExe = "py",
    [string]$EnvFile = (Join-Path $InstallRoot ".env")
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path (Join-Path $SourceRoot "*") -Destination $InstallRoot -Recurse -Force
& $PythonExe -m pip install $InstallRoot

$BinaryPath = "$PythonExe -m sb_712.service_host --env-file `"$EnvFile`""
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 1
}

New-Service -Name $ServiceName `
    -BinaryPathName $BinaryPath `
    -DisplayName "SB-712 Security Host" `
    -Description "SB-712 verification, trace logging, and trust ledger host" `
    -StartupType Automatic

Start-Service -Name $ServiceName
Write-Host "Installed $ServiceName into $InstallRoot"
