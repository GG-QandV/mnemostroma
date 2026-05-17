# =============================================================================
# uninstall-windows.ps1 -- Mnemostroma Windows Uninstaller
# Compatible with: PowerShell 5.1+ (Windows 10/11 built-in)
#
# Usage (recommended):
#   1. Download uninstall-windows.bat from GitHub
#   2. Double-click it
#
# Usage (manual):
#   powershell -ExecutionPolicy Bypass -File ".\scripts\uninstall-windows.ps1"
# =============================================================================

$ErrorActionPreference = "SilentlyContinue"

$mnemoDir     = "$env:USERPROFILE\.mnemostroma"
$manifestPath = "$mnemoDir\install-manifest.json"
$uninstallLog = "$mnemoDir\uninstall.log"

New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null
Start-Transcript -Path $uninstallLog -Append -Force

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma -- Uninstaller"
Write-Host "  Date : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  User : $env:USERNAME"
Write-Host "==================================================================="
Write-Host ""

# -- Read manifest ------------------------------------------------------------

$manifest   = $null
$tasks      = @("Mnemostroma Daemon", "Mnemostroma Proxy", "Mnemostroma Watchdog")
$scriptsDir = "$mnemoDir\venv\Scripts"
$pathAdded  = $true

if (Test-Path $manifestPath) {
    try {
        $manifest   = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $tasks      = $manifest.tasks
        $scriptsDir = $manifest.scripts_dir
        $pathAdded  = $manifest.path_added
        Write-Host "  OK Found install manifest"
        Write-Host "     Installed : $($manifest.install_date)"
        Write-Host "     Version   : $($manifest.version)"
    } catch {
        Write-Host "  WARN Could not read manifest -- using defaults."
    }
} else {
    Write-Host "  WARN No install manifest found at $manifestPath"
    Write-Host "       Proceeding with default task names and paths."
}

Write-Host ""


# -- STEP 1: Stop and remove Task Scheduler tasks -----------------------------

Write-Host "[1/4] Removing Task Scheduler tasks..."

foreach ($taskName in $tasks) {
    try {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "  OK Removed: $taskName"
    } catch {
        Write-Host "  WARN Could not remove '$taskName' (may not exist): $_"
    }
}


# -- STEP 2: Remove Scripts from user PATH ------------------------------------

Write-Host ""
Write-Host "[2/4] Removing from user PATH..."

if ($pathAdded) {
    $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -eq $null) { $currentPath = "" }
    $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $scriptsDir }) -join ";"
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "  OK Removed from PATH: $scriptsDir"
} else {
    Write-Host "  OK PATH was not modified by installer -- skipping"
}


# -- STEP 3: Remove venv ------------------------------------------------------

Write-Host ""
Write-Host "[3/4] Removing virtual environment..."

$venvDir = "$mnemoDir\venv"
if (Test-Path $venvDir) {
    try {
        Remove-Item $venvDir -Recurse -Force
        Write-Host "  OK Removed: $venvDir"
    } catch {
        Write-Host "  ERROR Could not remove venv: $_"
        Write-Host "        Remove manually: rmdir /s /q `"$venvDir`""
    }
} else {
    Write-Host "  OK Venv not found -- already removed"
}


# -- STEP 4: Remove data directory --------------------------------------------

Write-Host ""
Write-Host "[4/4] Data directory..."
Write-Host ""
Write-Host "  Your memory data is stored in:"
Write-Host "  $mnemoDir"
Write-Host ""

$answer = Read-Host "  Delete all Mnemostroma data and memory? [y/N]"

if ($answer -eq "y" -or $answer -eq "Y") {
    Stop-Transcript
    try {
        Remove-Item $mnemoDir -Recurse -Force
        Write-Host "  OK Removed: $mnemoDir"
    } catch {
        Write-Host "  ERROR Could not fully remove data directory: $_"
        Write-Host "        Remove manually: rmdir /s /q `"$mnemoDir`""
    }
} else {
    Write-Host "  Keeping data directory (logs and memory preserved)."
    Write-Host "  To remove manually later:"
    Write-Host "    rmdir /s /q `"$mnemoDir`""
    Stop-Transcript
}


# -- Done ---------------------------------------------------------------------

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma has been uninstalled."
Write-Host "==================================================================="
Write-Host ""
Write-Host "  To reinstall:"
Write-Host "    https://github.com/GG-QandV/mnemostroma#windows"
Write-Host ""
