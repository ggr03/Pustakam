<#
  Pustakam (पुस्तकम्) uninstaller for Windows.
  Removes the program, background tasks, Start-menu shortcut and firewall rule.
  Your notes in %USERPROFILE%\.pustakam are kept unless you choose to delete them.

      powershell -ExecutionPolicy Bypass -File .\PustakamUninstall.ps1
#>
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$InstallDir = Join-Path $env:LOCALAPPDATA 'Pustakam'
$AppDir     = Join-Path $InstallDir 'app'
$DataDir    = Join-Path $HOME '.pustakam'
$StartMenu  = Join-Path ([Environment]::GetFolderPath('Programs')) 'Pustakam.url'

Write-Host '=================================================='
Write-Host '   Pustakam (पुस्तकम्) uninstaller'
Write-Host '=================================================='

foreach ($t in 'Pustakam', 'Pustakam Backup') {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Host 'Background tasks removed'

Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$AppDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Get-NetFirewallRule -DisplayName 'Pustakam' -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName 'Pustakam' -ErrorAction SilentlyContinue
    if ($?) { Write-Host 'Firewall rule removed' } else { Write-Host 'Run as Administrator to remove the "Pustakam" firewall rule.' -ForegroundColor Yellow }
}

Remove-Item $StartMenu -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
# This script may live inside $InstallDir; remove everything except itself, then itself last.
Get-ChildItem $InstallDir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $MyInvocation.MyCommand.Path } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'Program files removed'

Write-Host ''
Write-Host "Your notes, settings and backups are in: $DataDir" -ForegroundColor Yellow
$r = Read-Host 'Delete them too? This cannot be undone. Type DELETE to confirm, or press Enter to keep'
if ($r -ceq 'DELETE') {
    Remove-Item $DataDir -Recurse -Force
    Write-Host "Removed $DataDir"
} else {
    Write-Host "Kept $DataDir" -ForegroundColor Green
}
Write-Host ''
Write-Host 'Pustakam has been uninstalled.' -ForegroundColor Green
if ($MyInvocation.MyCommand.Path -like "$InstallDir*") {
    Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$InstallDir`"" -WindowStyle Hidden
}
