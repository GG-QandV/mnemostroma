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
$installLog = "$mnemoDir\install.log"
$manifestPath = "$mnemoDir\install-manifest.json"

# ── Create install dir and start logging ──────────────────────────────────────

New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null
Start-Transcript -Path $installLog -Append -Force

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma Installation Log"
Write-Host "  Date    : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  OS      : $([System.Environment]::OSVersion.VersionString)"
Write-Host "  Build   : $((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion)"
Write-Host "  User    : $env:USERNAME"
Write-Host "  Install : $mnemoDir"
Write-Host "==================================================================="
Write-Host ""
Write-Host "  ███╗   ███╗███╗  ██╗███████╗███╗   ███╗ ██████╗"
Write-Host "  ████╗ ████║████╗ ██║██╔════╝████╗ ████║██╔═══██╗"
Write-Host "  ██╔████╔██║██╔██╗██║█████╗  ██╔████╔██║██║   ██║"
Write-Host "  ██║╚██╔╝██║██║╚████║██╔══╝  ██║╚██╔╝██║██║   ██║"
Write-Host "  ██║ ╚═╝ ██║██║ ╚███║███████╗██║ ╚═╝ ██║╚██████╔╝"
Write-Host "  ╚═╝     ╚═╝╚═╝  ╚══╝╚══════╝╚═╝     ╚═╝ ╚═════╝"
Write-Host "              Mnemostroma — Windows Installer"
Write-Host ""

# Manifest — will be written at the end
$manifest = @{
    install_date  = (Get-Date -Format "o")
    version       = "unknown"
    venv_dir      = $venvDir
    scripts_dir   = $scriptsDir
    path_added    = $false
    python_bin    = ""
    git_version   = ""
    tasks         = @()
    install_log   = $installLog
    status        = "in_progress"
}


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
        Write-Host ""
        Write-Host "  Installation log saved to: $installLog"
        $manifest.status = "failed_no_python"
        $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
        Stop-Transcript
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
        Write-Host ""
        Write-Host "  Installation log saved to: $installLog"
        Write-Host "  Paste the log contents to ChatGPT or Claude for help."
        $manifest.status = "failed_winget_python"
        $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
        Stop-Transcript
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
        Write-Host "  Close this window, open a new one, and re-run the installer."
        Write-Host ""
        Write-Host "  Installation log saved to: $installLog"
        $manifest.status = "failed_python_path"
        $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
        Stop-Transcript
        exit 1
    }
}

$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
$manifest.python_bin = (Get-Command $pythonCmd).Source
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
    Write-Host ""
    Write-Host "  Installation log saved to: $installLog"
    $manifest.status = "failed_no_git"
    $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
    Stop-Transcript
    exit 1
}

$gitVer = (git --version) -replace "git version ", ""
$manifest.git_version = $gitVer
Write-Host "  ✓ Git $gitVer"


# ── STEP 3: Create venv ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/8] Setting up virtual environment..."

if (-not (Test-Path $venvPy)) {
    Write-Host "  Creating venv at $venvDir..."
    try {
        & $pythonCmd -m venv $venvDir
    } catch {
        Write-Host ""
        Write-Host "  ❌ Failed to create virtual environment."
        Write-Host "  Error: $_"
        Write-Host ""
        Write-Host "  Installation log saved to: $installLog"
        $manifest.status = "failed_venv"
        $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
        Stop-Transcript
        exit 1
    }
}

Write-Host "  ✓ Venv ready"


# ── STEP 4: Install Mnemostroma ───────────────────────────────────────────────

Write-Host ""
Write-Host "[4/8] Installing Mnemostroma..."

if ($Local) {
    $repoRoot = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $PWD.Path }
    Write-Host "  Local mode: $repoRoot"
    try {
        & $venvPy -m pip install --quiet -e "$repoRoot[all]"
    } catch {
        Write-Host "  ❌ Local install failed: $_"
        Write-Host "  Installation log saved to: $installLog"
        $manifest.status = "failed_pip_local"
        $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
        Stop-Transcript
        exit 1
    }
} else {
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
            Write-Host ""
            Write-Host "  Installation log saved to: $installLog"
            Write-Host "  Paste the log contents to ChatGPT or Claude for help."
            $manifest.status = "failed_pip_github"
            $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
            Stop-Transcript
            exit 1
        }
    }
}

if (-not (Test-Path $venvMnemo)) {
    Write-Host ""
    Write-Host "  ❌ mnemostroma CLI not found after install. Something went wrong."
    Write-Host "  Installation log saved to: $installLog"
    $manifest.status = "failed_cli_missing"
    $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
    Stop-Transcript
    exit 1
}

# Capture installed version
try {
    $mnemoVersion = (& $venvPy -c "import mnemostroma; print(mnemostroma.__version__)") 2>$null
    $manifest.version = $mnemoVersion
} catch { $manifest.version = "unknown" }

Write-Host "  ✓ Mnemostroma $($manifest.version) installed"


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
    $manifest.path_added = $true
    Write-Host "  ✓ Added to user PATH: $scriptsDir"
} else {
    Write-Host "  ✓ Already in PATH"
}

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
    Write-Host "  Installation log saved to: $installLog"
    $manifest.status = "failed_setup"
    $manifest | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8
    Stop-Transcript
    exit 1
}

Write-Host "  ✓ Setup complete"


# ── STEP 7: Register Task Scheduler tasks ────────────────────────────────────

Write-Host ""
Write-Host "[7/8] Registering autostart tasks (Task Scheduler)..."

$registeredTasks = @()

function Register-MnemoTask {
    param($TaskName, $Argument, $DelaySeconds, $LogFile)

    $logPath = "$mnemoDir\$LogFile"

    if ($Argument -eq "-m mnemostroma run") {
        $action = New-ScheduledTaskAction `
            -Execute $venvPy `
            -Argument $Argument `
            -WorkingDirectory $mnemoDir
    } else {
        $action = New-ScheduledTaskAction `
            -Execute "cmd.exe" `
            -Argument "/c `"$venvPy`" $Argument >> `"$logPath`" 2>&1" `
            -WorkingDirectory $mnemoDir
    }

    $trigger = New-ScheduledTaskTrigger -AtLogOn
    if ($DelaySeconds -gt 0) { $trigger.Delay = "PT${DelaySeconds}S" }

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
        return $true
    } catch {
        Write-Host "  ⚠ Could not register '$TaskName': $_"
        Write-Host "    Run PowerShell as Administrator and re-run this script to fix."
        return $false
    }
}

if (Register-MnemoTask "Mnemostroma Daemon"   "-m mnemostroma run"                    0  "daemon.log")   { $registeredTasks += "Mnemostroma Daemon" }
if (Register-MnemoTask "Mnemostroma Proxy"    "-m mnemostroma.integration.http_proxy" 20 "proxy.log")    { $registeredTasks += "Mnemostroma Proxy" }
if (Register-MnemoTask "Mnemostroma Watchdog" "-m mnemostroma.watchdog"               25 "watchdog.log") { $registeredTasks += "Mnemostroma Watchdog" }

$manifest.tasks = $registeredTasks

foreach ($taskName in $registeredTasks) {
    try { Start-ScheduledTask -TaskName $taskName }
    catch { Write-Host "  ⚠ Could not start '$taskName' now (will start on next login): $_" }
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


# ── Write manifest ────────────────────────────────────────────────────────────

$manifest.status = "success"
$manifest | ConvertTo-Json -Depth 3 | Set-Content $manifestPath -Encoding UTF8
Write-Host ""
Write-Host "  ✓ Install manifest saved: $manifestPath"


# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "==================================================================="
Write-Host "  🎉 Mnemostroma installed successfully!"
Write-Host "==================================================================="
Write-Host ""
Write-Host "  Management:"
Write-Host "    mnemostroma on      — start daemon"
Write-Host "    mnemostroma off     — stop daemon"
Write-Host "    mnemostroma status  — check status"
Write-Host ""
Write-Host "  Uninstall:"
Write-Host "    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/uninstall-windows.ps1' -OutFile `"`$env:TEMP\mnemo-uninstall.ps1`""
Write-Host "    powershell -ExecutionPolicy Bypass -File `"`$env:TEMP\mnemo-uninstall.ps1`""
Write-Host ""
Write-Host "  Logs:"
Write-Host "    Installation log : $installLog"
Write-Host "    Daemon log       : $mnemoDir\daemon.log"
Write-Host ""
Write-Host "  If something went wrong, paste contents of install.log"
Write-Host "  to ChatGPT, Claude or Gemini for step-by-step help."
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

Stop-Transcript
