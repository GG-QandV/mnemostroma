# =============================================================================
# install-windows.ps1 -- Mnemostroma Windows Installer
# Compatible with: PowerShell 5.1+ (Windows 10/11 built-in)
#
# Usage (recommended):
#   1. Download install-windows.bat from GitHub
#   2. Double-click it
#
# Usage (manual):
#   powershell -ExecutionPolicy Bypass -File ".\scripts\install-windows.ps1"
#   powershell -ExecutionPolicy Bypass -File ".\scripts\install-windows.ps1" -Local
# =============================================================================

param (
    [switch]$Local
)

$ErrorActionPreference = "Stop"

$mnemoDir     = "$env:USERPROFILE\.mnemostroma"
$venvDir      = "$mnemoDir\venv"
$venvPy       = "$venvDir\Scripts\python.exe"
$venvMnemo    = "$venvDir\Scripts\mnemostroma.exe"
$scriptsDir   = "$venvDir\Scripts"
$installLog   = "$mnemoDir\install.log"
$manifestPath = "$mnemoDir\install-manifest.json"

# -- Create install dir and start logging -------------------------------------

New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null
Start-Transcript -Path $installLog -Append -Force

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma -- Windows Installer"
Write-Host "  Date    : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  OS      : $([System.Environment]::OSVersion.VersionString)"
Write-Host "  User    : $env:USERNAME"
Write-Host "  Install : $mnemoDir"
Write-Host "==================================================================="
Write-Host ""

$manifest = @{
    install_date = (Get-Date -Format "o")
    version      = "unknown"
    venv_dir     = $venvDir
    scripts_dir  = $scriptsDir
    path_added   = $false
    python_bin   = ""
    git_version  = ""
    tasks        = @()
    install_log  = $installLog
    status       = "in_progress"
}

function Save-Manifest($status) {
    $manifest.status = $status
    $json = $manifest | ConvertTo-Json -Depth 3
    [System.IO.File]::WriteAllText($manifestPath, $json, [System.Text.Encoding]::UTF8)
}

function Exit-WithError($status, $message) {
    Write-Host ""
    Write-Host "  ERROR: $message"
    Write-Host ""
    Write-Host "  Installation log saved to:"
    Write-Host "  $installLog"
    Write-Host ""
    Write-Host "  Paste the log contents into ChatGPT, Claude or Gemini"
    Write-Host "  and ask: 'What went wrong in this Mnemostroma installation log?'"
    Write-Host ""
    Save-Manifest $status
    Stop-Transcript
    exit 1
}


# -- STEP 1: Ensure Python 3.12+ ----------------------------------------------

function Test-PythonVersion($cmd) {
    $local:ErrorActionPreference = "SilentlyContinue"
    try {
        $result = & $cmd -c "import sys; print(sys.version_info >= (3,12))" 2>$null
        return ($result -eq "True")
    } catch {
        return $false
    }
}

function Find-Python {
    $local:ErrorActionPreference = "SilentlyContinue"
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
        Exit-WithError "failed_no_python" @"
Python 3.12+ is required and winget is not available.

  Install Python manually: https://python.org/downloads
  Check 'Add Python to PATH' during installation.
  Then re-run this installer.
"@
    }

    Write-Host "  Installing Python 3.12 via winget (no admin needed)..."
    $wingetResult = winget install Python.Python.3.12 `
        --silent --scope user `
        --accept-package-agreements `
        --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Exit-WithError "failed_winget_python" @"
winget failed to install Python (exit code $LASTEXITCODE).

  Install manually: https://python.org/downloads
  Check 'Add Python to PATH', then re-run this installer.
"@
    }

    # Refresh PATH in current process
    $userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    if ($userPath -eq $null) { $userPath = "" }
    if ($machinePath -eq $null) { $machinePath = "" }
    $env:PATH = "$userPath;$machinePath"

    $pythonCmd = Find-Python
    if (-not $pythonCmd) {
        Exit-WithError "failed_python_path" @"
Python was installed but is not yet in PATH for this session.

  Close this window, open a new one, and re-run the installer.
"@
    }
}

$pyVer = & $pythonCmd -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'.'+str(sys.version_info.micro))"
$manifest.python_bin = (Get-Command $pythonCmd -ErrorAction SilentlyContinue).Source
Write-Host "  OK Python $pyVer ($pythonCmd)"


# -- STEP 2: Ensure Git -------------------------------------------------------

Write-Host ""
Write-Host "[2/8] Checking Git..."

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Exit-WithError "failed_no_git" @"
Git is required (pip uses git to download Mnemostroma).

  Install Git: https://git-scm.com/download/win
  Use default settings. Then re-run this installer.
"@
}

$gitVer = (git --version) -replace "git version ", ""
$manifest.git_version = $gitVer
Write-Host "  OK Git $gitVer"


# -- STEP 3: Create venv ------------------------------------------------------

Write-Host ""
Write-Host "[3/8] Setting up virtual environment..."

if (-not (Test-Path $venvPy)) {
    Write-Host "  Creating venv at $venvDir ..."
    try {
        & $pythonCmd -m venv $venvDir
    } catch {
        Exit-WithError "failed_venv" "Failed to create virtual environment: $_"
    }
}

Write-Host "  OK Venv ready"


# -- STEP 4: Install Mnemostroma ----------------------------------------------

Write-Host ""
Write-Host "[4/8] Installing Mnemostroma..."

if ($Local) {
    $repoRoot = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $PWD.Path }
    Write-Host "  Local mode: $repoRoot"
    try {
        & $venvPy -m pip install --quiet -e "$repoRoot[all]"
    } catch {
        Exit-WithError "failed_pip_local" "Local install failed: $_"
    }
} else {
    $isEditable = ""
    try {
        $isEditable = & $venvPy -m pip show mnemostroma 2>$null
    } catch {}

    if ($isEditable -match "Editable project location") {
        Write-Host "  Editable install detected -- preserving local source link."
    } else {
        Write-Host "  Downloading from GitHub (may take 1-3 minutes)..."
        $pipSpec = "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
        try {
            & $venvPy -m pip install --quiet --upgrade $pipSpec
        } catch {
            Exit-WithError "failed_pip_github" @"
Installation from GitHub failed: $_

  Common causes:
    - No internet connection
    - Git not in PATH (close and reopen PowerShell after installing Git)
    - pip too old -- try: & '$venvPy' -m pip install --upgrade pip
"@
        }
    }
}

if (-not (Test-Path $venvMnemo)) {
    Exit-WithError "failed_cli_missing" "mnemostroma.exe not found after install. Check the log above."
}

$mnemoVersion = ""
try {
    $mnemoVersion = & $venvPy -c "import mnemostroma; print(mnemostroma.__version__)" 2>$null
} catch {}
if (-not $mnemoVersion) { $mnemoVersion = "unknown" }
$manifest.version = $mnemoVersion

Write-Host "  OK Mnemostroma $mnemoVersion installed"


# -- STEP 5: Add Scripts to PATH (User scope) ---------------------------------

Write-Host ""
Write-Host "[5/8] Updating PATH..."

$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -eq $null) { $userPath = "" }

if ($userPath -notlike "*$scriptsDir*") {
    [System.Environment]::SetEnvironmentVariable("PATH", "$userPath;$scriptsDir", "User")
    $manifest.path_added = $true
    Write-Host "  OK Added to user PATH: $scriptsDir"
} else {
    Write-Host "  OK Already in PATH"
}

$env:PATH = "$env:PATH;$scriptsDir"


# -- STEP 6: Run mnemostroma setup --------------------------------------------

Write-Host ""
Write-Host "[6/8] Running setup (~300 MB AI models download)..."
Write-Host "  Note: Windows Defender may scan ONNX files -- first run can take 30-60s extra."
Write-Host ""

try {
    & $venvMnemo setup
} catch {
    Exit-WithError "failed_setup" "mnemostroma setup failed: $_"
}

Write-Host "  OK Setup complete"


# -- STEP 7: Register Task Scheduler tasks ------------------------------------

Write-Host ""
Write-Host "[7/8] Registering autostart tasks..."

$registeredTasks = @()

function Register-MnemoTask($TaskName, $Argument, $DelaySeconds, $LogFile) {
    $logPath = "$mnemoDir\$LogFile"

    if ($Argument -eq "-m mnemostroma run") {
        $action = New-ScheduledTaskAction `
            -Execute $venvPy `
            -Argument $Argument `
            -WorkingDirectory $mnemoDir
    } else {
        $cmdArgs = "/c `"$venvPy`" $Argument >> `"$logPath`" 2>&1"
        $action = New-ScheduledTaskAction `
            -Execute "cmd.exe" `
            -Argument $cmdArgs `
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
        Write-Host "  OK Registered: $TaskName"
        return $true
    } catch {
        Write-Host "  WARN Could not register '$TaskName': $_"
        Write-Host "       Run PowerShell as Administrator and re-run installer to fix."
        return $false
    }
}

if (Register-MnemoTask "Mnemostroma Daemon"   "-m mnemostroma run"                    0  "daemon.log")   { $registeredTasks += "Mnemostroma Daemon" }
if (Register-MnemoTask "Mnemostroma Proxy"    "-m mnemostroma.integration.http_proxy" 20 "proxy.log")    { $registeredTasks += "Mnemostroma Proxy" }
if (Register-MnemoTask "Mnemostroma Watchdog" "-m mnemostroma.watchdog"               25 "watchdog.log") { $registeredTasks += "Mnemostroma Watchdog" }

$manifest.tasks = $registeredTasks

foreach ($taskName in $registeredTasks) {
    try {
        Start-ScheduledTask -TaskName $taskName
    } catch {
        Write-Host "  WARN Could not start '$taskName' now (will start on next login): $_"
    }
}

Write-Host "  OK Tasks started ($($registeredTasks.Count)/3)"


# -- STEP 8: Final status -----------------------------------------------------

Write-Host ""
Write-Host "[8/8] Checking daemon status..."
Write-Host "  (waiting 5 seconds for daemon to initialize...)"
Start-Sleep -Seconds 5

try {
    & $venvMnemo status
} catch {
    Write-Host "  WARN Status check failed -- daemon may still be starting."
    Write-Host "       Run manually: mnemostroma status"
}


# -- Write manifest -----------------------------------------------------------

Save-Manifest "success"
Write-Host ""
Write-Host "  OK Install manifest saved: $manifestPath"


# -- Done ---------------------------------------------------------------------

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma installed successfully!"
Write-Host "==================================================================="
Write-Host ""
Write-Host "  Manage daemon:"
Write-Host "    mnemostroma on      -- start"
Write-Host "    mnemostroma off     -- stop"
Write-Host "    mnemostroma status  -- check"
Write-Host ""
Write-Host "  Logs:"
Write-Host "    Install log : $installLog"
Write-Host "    Daemon log  : $mnemoDir\daemon.log"
Write-Host ""
Write-Host "  Uninstall:"
Write-Host "    Download uninstall-windows.bat from:"
Write-Host "    https://github.com/GG-QandV/mnemostroma/raw/main/scripts/uninstall-windows.bat"
Write-Host ""
Write-Host "  If something went wrong:"
Write-Host "    Open $installLog"
Write-Host "    Copy its contents into ChatGPT, Claude or Gemini"
Write-Host "    Ask: What went wrong in this installation log?"
Write-Host ""
Write-Host "  Note: SIGUSR1/SIGUSR2 are not available on Windows."
Write-Host "    Use 'mnemostroma off' and 'mnemostroma on' instead."
Write-Host ""
Write-Host "  Next step:"
Write-Host "    Install the browser extension to start capturing AI sessions."
Write-Host "    https://github.com/GG-QandV/mnemostroma#browser-extension"
Write-Host ""
Write-Host "  If 'mnemostroma' is not found in new terminals:"
Write-Host "    Close and reopen PowerShell (PATH update takes effect on new sessions)."
Write-Host ""

Stop-Transcript
