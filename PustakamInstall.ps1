<#
=====================================================================
  Pustakam (पुस्तकम्) installer for Windows 10 / 11

  Installs for the CURRENT Windows user and starts Pustakam as a hidden
  background task, so you sign in with this Windows account.

  Run from the Pustakam folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File .\PustakamInstall.ps1
  Options:
      -RunAtStartup   start at boot even before you log in (asks for your
                      Windows password once, stored by Task Scheduler)
      -OpenFirewall   allow other devices on your network (needs admin)
      -Yes            accept defaults without questions
=====================================================================
#>
[CmdletBinding()]
param(
    [switch]$RunAtStartup,
    [switch]$OpenFirewall,
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Version    = '1.0'
$Port       = 5150
$TaskName   = 'Pustakam'
$BackupTask = 'Pustakam Backup'
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA 'Pustakam'
$AppDir     = Join-Path $InstallDir 'app'
$VenvDir    = Join-Path $InstallDir 'venv'
$DataDir    = Join-Path $HOME '.pustakam'
$StartMenu  = Join-Path ([Environment]::GetFolderPath('Programs')) 'Pustakam.url'

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Ask($q, $default = 'n') {
    if ($Yes) { return $default -eq 'y' }
    $hint = if ($default -eq 'y') { '[Y/n]' } else { '[y/N]' }
    $r = Read-Host "$q $hint"
    if ([string]::IsNullOrWhiteSpace($r)) { $r = $default }
    return $r -match '^[Yy]'
}

Write-Host '=================================================='
Write-Host "   Pustakam (पुस्तकम्) installer  v$Version"
Write-Host '=================================================='

# ------------------------------------------------------------- Python 3.11+
function Find-Python {
    $candidates = @(@('py', '-3'), @('python'), @('python3'))
    foreach ($c in $candidates) {
        $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $path = & $exe @pre -c "import sys; print(sys.executable if sys.version_info >= (3,11) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path $path) -and ($path -notmatch 'WindowsApps')) { return $path.Trim() }
        } catch { }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Warn 'Python 3.11 or newer was not found.'
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask 'Install Python 3.12 with winget now?' 'y')) {
        winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $Python = Find-Python
    }
    if (-not $Python) { throw 'Please install Python 3.11 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run this again.' }
}
Ok "Using Python: $Python"

# ------------------------------------------------------------- stop old copy
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$AppDir*PustakamApp.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ------------------------------------------------------------- copy files
Info "Installing to $AppDir"
New-Item -ItemType Directory -Force -Path $AppDir, "$DataDir\notes", "$DataDir\backups", "$DataDir\Logs" | Out-Null
Remove-Item -Recurse -Force (Join-Path $AppDir 'templates'), (Join-Path $AppDir 'static') -ErrorAction SilentlyContinue
Copy-Item (Join-Path $ScriptDir 'Pustakam*.py'), (Join-Path $ScriptDir 'PustakamRequirements.txt') $AppDir -Force
Copy-Item (Join-Path $ScriptDir 'templates'), (Join-Path $ScriptDir 'static') $AppDir -Recurse -Force
Copy-Item (Join-Path $ScriptDir 'PustakamUninstall.ps1') $InstallDir -Force

Info 'Creating Python environment'
& $Python -m venv $VenvDir
$VPy  = Join-Path $VenvDir 'Scripts\python.exe'
$VPyw = Join-Path $VenvDir 'Scripts\pythonw.exe'
& $VPy -m pip install --upgrade pip -q
& $VPy -m pip install -r (Join-Path $AppDir 'PustakamRequirements.txt') -q
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
Ok 'Python packages installed'

# ------------------------------------------------------------- rclone (OneDrive sign-in & sync)
$RcloneExe = Join-Path $InstallDir 'bin\rclone.exe'
if (Test-Path $RcloneExe) {
    Ok "rclone: $((& $RcloneExe version | Select-Object -First 1)) (Pustakam's copy)"
} elseif (Get-Command rclone -ErrorAction SilentlyContinue) {
    Ok "rclone: $((& rclone version | Select-Object -First 1)) (system)"
} else {
    Info 'OneDrive sign-in uses rclone (no Microsoft app registration needed).'
    if (Ask "Download the official rclone build (~25 MB, checksum-verified) into $InstallDir\bin?" 'y') {
        & $VPy (Join-Path $AppDir 'PustakamGetRclone.py') (Join-Path $InstallDir 'bin')
        if ($LASTEXITCODE -ne 0) { Warn 'rclone download failed; OneDrive will not work until rclone is installed.' }
    } else {
        Warn 'Skipped. Install rclone later for OneDrive: winget install Rclone.Rclone'
    }
}

Push-Location $AppDir
& $VPy -c "import PustakamDatabase as d; d.init_db(); print('Database ready')"
Pop-Location

# ------------------------------------------------------------- background task
Info 'Registering background task'
$action   = New-ScheduledTaskAction -Execute $VPyw -Argument "`"$AppDir\PustakamApp.py`"" -WorkingDirectory $AppDir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -StartWhenAvailable -MultipleInstances IgnoreNew
$user = "$env:USERDOMAIN\$env:USERNAME"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

if ($RunAtStartup) {
    Warn 'Task Scheduler needs your Windows password once to start Pustakam before you log in.'
    $cred = Get-Credential -UserName $user -Message 'Your Windows password (stored by Task Scheduler, not by Pustakam)'
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited `
        -Description 'Pustakam (पुस्तकम्) notes server' | Out-Null
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description 'Pustakam (पुस्तकम्) notes server' | Out-Null
}

$bAction  = New-ScheduledTaskAction -Execute $VPyw -Argument "`"$AppDir\PustakamBackup.py`"" -WorkingDirectory $AppDir
$bTrigger = New-ScheduledTaskTrigger -Daily -At '21:00'
$bPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Unregister-ScheduledTask -TaskName $BackupTask -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $BackupTask -Action $bAction -Trigger $bTrigger -Principal $bPrincipal `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries) `
    -Description 'Pustakam daily backup (keeps the last 5)' | Out-Null

Start-ScheduledTask -TaskName $TaskName
Ok 'Pustakam started'

# ------------------------------------------------------------- firewall (optional)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($OpenFirewall -or (-not $Yes -and (Ask "Allow other devices on your network to reach Pustakam (firewall port $Port)?" 'n'))) {
    if ($isAdmin) {
        Remove-NetFirewallRule -DisplayName 'Pustakam' -ErrorAction SilentlyContinue
        New-NetFirewallRule -DisplayName 'Pustakam' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
        Ok "Firewall: port $Port open on private networks"
    } else {
        Warn "Run this once in an *Administrator* PowerShell to open the port:"
        Write-Host "  New-NetFirewallRule -DisplayName Pustakam -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private"
    }
}

# ------------------------------------------------------------- Start menu shortcut
"[InternetShortcut]`r`nURL=http://localhost:$Port/`r`n" | Set-Content -Path $StartMenu -Encoding ASCII

Start-Sleep -Seconds 3
Write-Host ''
Write-Host '=================================================='
Ok   "  Pustakam v$Version is installed"
Write-Host '=================================================='
Write-Host "  Open:        http://localhost:$Port   (Start menu: Pustakam)"
Write-Host "  Sign in as:  $env:USERNAME with your Windows password"
Write-Host "               (Microsoft account: MicrosoftAccount\you@outlook.com; a PIN will not work)"
Write-Host "  Data:        $DataDir"
Write-Host "  Program:     $InstallDir"
Write-Host "  Manage:      Start-ScheduledTask Pustakam / Stop-ScheduledTask Pustakam"
Write-Host "  Logs:        $DataDir\Logs\server.log"
Write-Host "  Uninstall:   powershell -ExecutionPolicy Bypass -File `"$InstallDir\PustakamUninstall.ps1`""
Write-Host ''
if (Ask 'Open Pustakam in your browser now?' 'y') { Start-Process "http://localhost:$Port/" }
