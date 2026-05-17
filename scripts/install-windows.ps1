# ─────────────────────────────────────────────────────────────────────────────
# install-windows.ps1 — Mnemostroma Windows Installer
#
# Usage (recommended — download then run):
#   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-windows.ps1" -OutFile "$env:TEMP\mnemo-install.ps1"
#   powershell -ExecutionPolicy Bypass -File "$env:TEMP\mnemo-install.ps1"
#
# Usage (from cloned repo):
#   powershell -ExecutionPolicy Bypass -File ".\scripts\install-windows.ps1" [-Local]
#
# Installs for the CURRENT USER only. No administrator rights required.
# On a shared/family PC — run under each user account separately.
# ─────────────────────────────────────────────────────────────────────────────

param (
    [switch]$Local  # Install from local source instead of GitHub
)

$ErrorActionPreference = "Stop"

$mnemoDir   = "$env:USERPROFILE\.mnemostroma"
$venvDir    = "$mnemoDir\venv"
$venvPy     = "$venvDir\Scripts\python.exe"
$venvPip    = "$venvDir\Scripts\pip.exe"
$venvMnemo  = "$venvDir\Scripts\mnemostroma.exe"
$scriptsDir = "$venvDir\Scripts"

Write-Host ""
Write-Host "  ███╗   ███╗███╗  ██╗███████╗███╗   ███╗ ██████╗"
Write-Host "  ████╗ ████║████╗ ██║██╔════╝████╗ ████║██╔═══██╗"
Write-Host "  ██╔████╔██║██╔██╗██║█████╗  ██╔████╔██║██║   ██║"
Write-Host "  ██║╚██╔╝██║██║╚████║██╔══╝  ██║╚██╔╝██║██║   ██║"
Write-Host "  ██║ ╚═╝ ██║██║ ╚███║███████╗██║ ╚═╝ ██║╚██████╔╝"
Write-Host "  ╚═╝     ╚═╝╚═╝  ╚══╝╚══════╝╚═╝     ╚═╝ ╚═════╝"
Write-Host "              Mnemostroma — Windows Installer"
Write-Host ""
Write-Host "  Install dir : $mnemoDir"
Write-Host "  User        : $env:USERNAME"
Write-Host ""


# ── STEP 1: Ensure Python 3.12+ ───────────────────────────────────────────────

function Test-PythonVersion($cmd) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info >= (3,12))" 2>$null
        return $ver -eq "True"
    } catch { return $false }
}

function Find-Python {
    foreach ($cmd in @("py", "python3", "python")) {
        try {
            if (Get-Command $cmd -ErrorAction SilentlyContinue) {
                if (Test-PythonVersion $cmd) { return $cmd }
            }
        } catch {}
    }
    return $null
}

Write-Host "[1/8] Checking Python 3.12+..."

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Host "  Python 3.12+ not found. Attempting install via winget..."

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "  ❌ Python 3.12+ is required and winget is not available."
        Write-Host ""
        Write-Host "  Install Python manually:"
        Write-Host "    https://python.org/downloads"
        Write-Host "  ✔ Check 'Add Python to PATH' during installation."
        Write-Host "  Then re-run this script."
        exit 1
    }

    Write-Host "  Installing Python 3.12 via winget (user scope, no admin needed)..."
    try {
        winget install Python.Python.3.12 `
            --silent --scope user `
            --accept-package-agreements `
            --accept-source-agreements
    } catch {
        Write-Host ""
        Write-Host "  ❌ winget failed to install Python."
        Write-Host "  Error: $_"
        Write-Host ""
        Write-Host "  Install manually: https://python.org/downloads"
        Write-Host "  ✔ Check 'Add Python to PATH', then re-run this script."
        exit 1
    }

    # Refresh PATH in this process after winget install
    $userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $env:PATH = "$userPath;$machinePath"

    $pythonCmd = Find-Python

    if (-not $pythonCmd) {
        Write-Host ""
        Write-Host "  ❌ Python was installed but is not yet in PATH for this session."
        Write-Host "  Close this PowerShell window, open a new one, and re-run the script."
        exit 1
    }
}

$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host "  ✓ Python $pyVer ($pythonCmd)"


# ── STEP 2: Ensure Git ────────────────────────────────────────────────────────

Write-Host ""
Write-Host "[2/8] Checking Git..."

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "  ❌ Git is required for installation (pip uses git to fetch the package)."
    Write-Host ""
    Write-Host "  Install Git from: https://git-scm.com/download/win"
    Write-Host "  Use default settings. Then re-run this script."
    exit 1
}

$gitVer = (git --version) -replace "git version ", ""
Write-Host "  ✓ Git $gitVer"


# ── STEP 3: Create venv ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/8] Setting up virtual environment..."

New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null

if (-not (Test-Path $venvPy)) {
    Write-Host "  Creating venv at $venvDir..."
    try {
        & $pythonCmd -m venv $venvDir
    } catch {
        Write-Host ""
        Write-Host "  ❌ Failed to create virtual environment."
        Write-Host "  Error: $_"
        exit 1
    }
}

Write-Host "  ✓ Venv ready"


# ── STEP 4: Install Mnemostroma ───────────────────────────────────────────────

Write-Host ""
Write-Host "[4/8] Installing Mnemostroma..."

if ($Local) {
    # Detect script location for local install
    $repoRoot = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $PWD.Path }
    Write-Host "  Local mode: $repoRoot"
    try {
        & $venvPy -m pip install --quiet -e "$repoRoot[all]"
    } catch {
        Write-Host "  ❌ Local install failed: $_"
        exit 1
    }
} else {
    # Check for editable install — preserve it
    $isEditable = (& $venvPy -m pip show -f mnemostroma 2>$null) -match "Editable project location"
    if ($isEditable) {
        Write-Host "  ⚡ Editable install detected — preserving local source link."
    } else {
        Write-Host "  Fetching from GitHub (this may take 1-3 minutes)..."
        try {
            & $venvPy -m pip install --quiet --upgrade `
                "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
        } catch {
            Write-Host ""
            Write-Host "  ❌ Installation failed."
            Write-Host "  Error: $_"
            Write-Host ""
            Write-Host "  Common causes:"
            Write-Host "    - No internet connection"
            Write-Host "    - Git not in PATH (restart PowerShell after Git install)"
            Write-Host "    - pip version too old — try: $venvPy -m pip install --upgrade pip"
            exit 1
        }
    }
}

if (-not (Test-Path $venvMnemo)) {
    Write-Host ""
    Write-Host "  ❌ mnemostroma CLI not found after install. Something went wrong."
    Write-Host "  Check the output above for errors."
    exit 1
}

Write-Host "  ✓ Mnemostroma installed"


# ── STEP 5: Add Scripts to PATH (User scope) ─────────────────────────────────

Write-Host ""
Write-Host "[5/8] Updating PATH..."

$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User") ?? ""
if ($userPath -notlike "*$scriptsDir*") {
    [System.Environment]::SetEnvironmentVariable(
        "PATH",
        "$userPath;$scriptsDir",
        "User"
    )
    Write-Host "  ✓ Added to user PATH: $scriptsDir"
} else {
    Write-Host "  ✓ Already in PATH"
}

# Patch current process so mnemostroma works immediately
$env:PATH = "$env:PATH;$scriptsDir"


# ── STEP 6: Run mnemostroma setup (config + models + TLS) ────────────────────

Write-Host ""
Write-Host "[6/8] Running setup (downloads ~300 MB of AI models)..."
Write-Host "  NOTE: Windows Defender may scan ONNX files — first run takes 30-60s extra."
Write-Host ""

try {
    & $venvMnemo setup
} catch {
    Write-Host ""
    Write-Host "  ❌ Setup failed: $_"
    Write-Host "  Try running manually: mnemostroma setup"
    exit 1
}

Write-Host "  ✓ Setup complete"


# ── STEP 7: Register Task Scheduler tasks ────────────────────────────────────

Write-Host ""
Write-Host "[7/8] Registering autostart tasks (Task Scheduler)..."

function Register-MnemoTask {
    param($TaskName, $Argument, $DelaySeconds, $LogFile)

    $logPath = "$mnemoDir\$LogFile"

    if ($Argument -eq "-m mnemostroma run") {
        # Daemon: run directly, no log redirect (uses daemon.log internally)
        $action = New-ScheduledTaskAction `
            -Execute $venvPy `
            -Argument $Argument `
            -WorkingDirectory $mnemoDir
    } else {
        # Proxy / Watchdog: redirect output to log file via cmd wrapper
        $action = New-ScheduledTaskAction `
            -Execute "cmd.exe" `
            -Argument "/c `"$venvPy`" $Argument >> `"$logPath`" 2>&1" `
            -WorkingDirectory $mnemoDir
    }

    $trigger = New-ScheduledTaskTrigger -AtLogOn
    if ($DelaySeconds -gt 0) {
        $trigger.Delay = "PT${DelaySeconds}S"
    }

    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Seconds 5) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries

    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -RunLevel Limited `
            -Force | Out-Null
        Write-Host "  ✓ Registered: '$TaskName'"
    } catch {
        Write-Host "  ⚠ Could not register '$TaskName': $_"
        Write-Host "    Run PowerShell as Administrator and re-run this script to fix."
    }
}

Register-MnemoTask "Mnemostroma Daemon"   "-m mnemostroma run"                          0  "daemon.log"
Register-MnemoTask "Mnemostroma Proxy"    "-m mnemostroma.integration.http_proxy"       20 "proxy.log"
Register-MnemoTask "Mnemostroma Watchdog" "-m mnemostroma.watchdog"                     25 "watchdog.log"

# Start all tasks immediately
foreach ($taskName in @("Mnemostroma Daemon", "Mnemostroma Proxy", "Mnemostroma Watchdog")) {
    try {
        Start-ScheduledTask -TaskName $taskName
    } catch {
        Write-Host "  ⚠ Could not start '$taskName' now (will start on next login): $_"
    }
}

Write-Host "  ✓ Tasks started"


# ── STEP 8: Final status ──────────────────────────────────────────────────────

Write-Host ""
Write-Host "[8/8] Checking status..."
Write-Host "  (waiting 5s for daemon to initialize...)"
Start-Sleep -Seconds 5

try {
    & $venvMnemo status
} catch {
    Write-Host "  ⚠ Status check failed — daemon may still be starting."
    Write-Host "    Run manually: mnemostroma status"
}


# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "─────────────────────────────────────────────────────"
Write-Host "  🎉 Mnemostroma installed successfully!"
Write-Host "─────────────────────────────────────────────────────"
Write-Host ""
Write-Host "  Management:"
Write-Host "    mnemostroma on      — start daemon"
Write-Host "    mnemostroma off     — stop daemon"
Write-Host "    mnemostroma status  — check status"
Write-Host ""
Write-Host "  Logs:"
Write-Host "    Get-Content $mnemoDir\daemon.log -Wait -Tail 30"
Write-Host ""
Write-Host "  Task Scheduler GUI:  taskschd.msc"
Write-Host ""
Write-Host "  ⚠ NOTE: SIGUSR1/SIGUSR2 are not available on Windows."
Write-Host "    Use 'mnemostroma off' and 'mnemostroma on' instead."
Write-Host ""
Write-Host "  📢 NEXT STEP:"
Write-Host "  Load the Mnemostroma browser extension to capture AI sessions."
Write-Host "  Guide: https://github.com/GG-QandV/mnemostroma#browser-extension"
Write-Host ""
Write-Host "  ℹ If 'mnemostroma' is not found in new terminals:"
Write-Host "    Close and reopen PowerShell (PATH update takes effect on new sessions)."
Write-Host ""
