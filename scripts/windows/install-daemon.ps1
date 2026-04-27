#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────────────
# install-daemon.ps1 — установка Mnemostroma как Task Scheduler задача
# Использование (в PowerShell с правами администратора):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\scripts\windows\install-daemon.ps1
# ─────────────────────────────────────────────────────────────────────

param (
    [switch]$Local
)

$ErrorActionPreference = "Stop"

$userProfile = $env:USERPROFILE
$mnemoDir = "${userProfile}\.mnemostroma"
$venvScript = "${mnemoDir}\venv\Scripts\python.exe"

Write-Host "Installing Mnemostroma daemon on Windows..."
Write-Host "  Profile: $userProfile"
Write-Host "  Mnemostroma dir: $mnemoDir"

if (-Not (Test-Path $mnemoDir)) {
    New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null
}

# 1. Check Python and Create VENV
if (-Not (Test-Path $venvScript)) {
    Write-Host "  Creating virtual environment..."
    $pythonCmd = if (Get-Command "python3" -ErrorAction SilentlyContinue) { "python3" } else { "python" }
    & $pythonCmd -m venv "${mnemoDir}\venv"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment. Ensure Python 3.12+ is installed."
        exit 1
    }
}
Write-Host "  ✓ Python found: $venvScript"

# 2. Install Mnemostroma
if ($Local) {
    Write-Host "  Installing from local source..."
    & $venvScript -m pip install -e ".[all]"
} else {
    Write-Host "  Installing from GitHub..."
    & $venvScript -m pip install --quiet --upgrade "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
}

# 3. Download Models
Write-Host "  Downloading models..."
& $venvScript -m mnemostroma download-models


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

# ── Proxy Task ────────────────────────────────────────────────────────
# Uses cmd /c wrapper to redirect stdout/stderr to log file
# cmd /c is required — Task Scheduler does not support shell redirects directly
$proxyLog  = "${mnemoDir}\proxy.log"
$proxyAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"${venvScript}`" -m mnemostroma.integration.http_proxy >> `"${proxyLog}`" 2>&1" `
    -WorkingDirectory $mnemoDir

# Proxy starts 20s after logon — gives Daemon time to create daemon.sock
# (Daemon needs 10-30s to load ONNX models before accepting connections)
$proxyTrigger = New-ScheduledTaskTrigger -AtLogOn
$proxyTrigger.Delay = "PT20S"

$proxySettings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 10) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "Mnemostroma Proxy" `
    -Action $proxyAction `
    -Trigger $proxyTrigger `
    -Settings $proxySettings `
    -RunLevel Limited `
    -Force

Write-Host "  ✓ Task registered: 'Mnemostroma Proxy' (starts 20s after logon)"
Start-ScheduledTask -TaskName "Mnemostroma Proxy"
Write-Host "  ✓ Proxy started"

# ── Watchdog Task ─────────────────────────────────────────────────────
$watchdogLog = "${mnemoDir}\watchdog.log"
$watchdogAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"${venvScript}`" -m mnemostroma.watchdog >> `"${watchdogLog}`" 2>&1" `
    -WorkingDirectory $mnemoDir

# Watchdog starts 25s after logon — after Daemon and Proxy are up
$watchdogTrigger = New-ScheduledTaskTrigger -AtLogOn
$watchdogTrigger.Delay = "PT25S"

$watchdogSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "Mnemostroma Watchdog" `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -RunLevel Limited `
    -Force

Write-Host "  ✓ Task registered: 'Mnemostroma Watchdog' (starts 25s after logon)"
Start-ScheduledTask -TaskName "Mnemostroma Watchdog"
Write-Host "  ✓ Watchdog started"

Write-Host ""
Write-Host "Management (Task Scheduler):"
Write-Host "  Start:    Start-ScheduledTask -TaskName 'Mnemostroma Daemon'"
Write-Host "  Stop:     Stop-ScheduledTask  -TaskName 'Mnemostroma Daemon'"
Write-Host "  Uninstall all:"
Write-Host "    'Mnemostroma Daemon','Mnemostroma Proxy','Mnemostroma Watchdog' | ForEach-Object { Unregister-ScheduledTask -TaskName `$_ -Confirm:`$false }"
Write-Host ""
Write-Host "Logs:"
Write-Host "  Get-Content ${mnemoDir}\daemon.log   -Wait -Tail 30"
Write-Host "  Get-Content ${mnemoDir}\proxy.log    -Wait -Tail 30"
Write-Host "  Get-Content ${mnemoDir}\watchdog.log -Wait -Tail 30"
Write-Host ""
Write-Host "View in GUI: taskschd.msc"
