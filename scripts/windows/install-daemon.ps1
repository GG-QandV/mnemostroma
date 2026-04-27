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
$venvDir  = "${mnemoDir}\venv"
$venvScript = "${venvDir}\Scripts\python.exe"

Write-Host "Installing Mnemostroma on Windows..."
Write-Host "  Profile: $userProfile"
Write-Host "  Mnemostroma dir: $mnemoDir"

# 1. Ensure ~/.mnemostroma exists
New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null

# 2. Verify Python 3.12+
$pythonBin = $null
foreach ($candidate in @("python3.12", "python3.13", "python3", "python")) {
    $p = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($p) {
        $ver = & $p.Source -c "import sys; print(sys.version_info >= (3,12))" 2>$null
        if ($ver -eq "True") { $pythonBin = $p.Source; break }
    }
}
if (-not $pythonBin) {
    Write-Error "Python 3.12+ is required. Download from https://python.org"
    exit 1
}
Write-Host "  ✓ Python found: $pythonBin"

# 3. Create venv if missing
if (-Not (Test-Path $venvScript)) {
    Write-Host "  Creating virtual environment..."
    & $pythonBin -m venv $venvDir
    Write-Host "  ✓ Venv created: $venvDir"
}

# 4. Install / upgrade mnemostroma
Write-Host "  Installing mnemostroma[all]..."
& "${venvDir}\Scripts\pip.exe" install --quiet --upgrade "mnemostroma[all]"
Write-Host "  ✓ Package installed"

# Verify venv is ready
if (-Not (Test-Path $venvScript)) {
    Write-Error "Virtual env not found at $venvScript after install — aborting."
    exit 1
}

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
