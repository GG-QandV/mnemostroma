#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────
# install-daemon.ps1 — установка Mnemostroma как Task Scheduler задача
# Использование (в PowerShell с правами администратора):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\scripts\windows\install-daemon.ps1
# ─────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$userProfile = $env:USERPROFILE
$mnemoDir = "${userProfile}\.mnemostroma"
$venvScript = "${mnemoDir}\venv\Scripts\python.exe"

Write-Host "Installing Mnemostroma daemon on Windows..."
Write-Host "  Profile: $userProfile"
Write-Host "  Mnemostroma dir: $mnemoDir"

# Проверить venv
if (-Not (Test-Path $venvScript)) {
    Write-Error "Virtual env not found at $venvScript"
    Write-Host "Run: python -m venv ${mnemoDir}\venv"
    exit 1
}

Write-Host "  ✓ Python found: $venvScript"

# Создать action
$action = New-ScheduledTaskAction `
    -Execute $venvScript `
    -Argument "-m mnemostroma run" `
    -WorkingDirectory $mnemoDir

# Создать trigger (при логине пользователя)
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Создать settings (автоперезагрузка при падении)
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# Зарегистрировать задачу
Register-ScheduledTask `
    -TaskName "Mnemostroma Daemon" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "  ✓ Task registered: 'Mnemostroma Daemon'"

# Запустить сразу
Start-ScheduledTask -TaskName "Mnemostroma Daemon"
Write-Host "  ✓ Daemon started"

Write-Host ""
Write-Host "Management (Task Scheduler):"
Write-Host "  Start:   Start-ScheduledTask -TaskName 'Mnemostroma Daemon'"
Write-Host "  Stop:    Stop-ScheduledTask -TaskName 'Mnemostroma Daemon'"
Write-Host "  Uninstall: Unregister-ScheduledTask -TaskName 'Mnemostroma Daemon' -Confirm:`$false"
Write-Host ""
Write-Host "View in GUI:"
Write-Host "  taskschd.msc"
