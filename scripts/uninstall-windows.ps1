# ─────────────────────────────────────────────────────────────────────────────
# uninstall-windows.ps1 — Mnemostroma Windows Uninstaller
#
# Usage:
#   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/uninstall-windows.ps1" -OutFile "$env:TEMP\mnemo-uninstall.ps1"
#   powershell -ExecutionPolicy Bypass -File "$env:TEMP\mnemo-uninstall.ps1"
#
# Or double-click uninstall-windows.bat (if available)
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "SilentlyContinue"

$mnemoDir     = "$env:USERPROFILE\.mnemostroma"
$manifestPath = "$mnemoDir\install-manifest.json"
$uninstallLog = "$mnemoDir\uninstall.log"

New-Item -ItemType Directory -Force -Path $mnemoDir | Out-Null
Start-Transcript -Path $uninstallLog -Append -Force

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma Uninstaller"
Write-Host "  Date : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  User : $env:USERNAME"
Write-Host "==================================================================="
Write-Host ""

# ── Read manifest ─────────────────────────────────────────────────────────────

$manifest = $null
$tasks     = @("Mnemostroma Daemon", "Mnemostroma Proxy", "Mnemostroma Watchdog")
$scriptsDir = "$mnemoDir\venv\Scripts"

if (Test-Path $manifestPath) {
    try {
        $manifest   = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $tasks      = $manifest.tasks
        $scriptsDir = $manifest.scripts_dir
        Write-Host "  ✓ Found install manifest (installed: $($manifest.install_date), version: $($manifest.version))"
    } catch {
        Write-Host "  ⚠ Could not read manifest — using defaults."
    }
} else {
    Write-Host "  ⚠ No install manifest found at $manifestPath"
    Write-Host "    Proceeding with default task names and paths."
}

Write-Host ""


# ── STEP 1: Stop and remove Task Scheduler tasks ─────────────────────────────

Write-Host "[1/4] Removing Task Scheduler tasks..."

foreach ($taskName in $tasks) {
    try {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "  ✓ Removed: '$taskName'"
    } catch {
        Write-Host "  ⚠ Could not remove '$taskName' (may not exist): $_"
    }
}


# ── STEP 2: Remove Scripts from user PATH ────────────────────────────────────

Write-Host ""
Write-Host "[2/4] Removing from user PATH..."

$pathAdded = if ($manifest) { $manifest.path_added } else { $true }

if ($pathAdded) {
    $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "User") ?? ""
    $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $scriptsDir }) -join ";"
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "  ✓ Removed from PATH: $scriptsDir"
} else {
    Write-Host "  ✓ PATH was not modified by installer — skipping"
}


# ── STEP 3: Remove venv ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/4] Removing virtual environment..."

$venvDir = "$mnemoDir\venv"
if (Test-Path $venvDir) {
    try {
        Remove-Item $venvDir -Recurse -Force
        Write-Host "  ✓ Removed: $venvDir"
    } catch {
        Write-Host "  ❌ Could not remove venv: $_"
        Write-Host "    Remove manually: rmdir /s /q `"$venvDir`""
    }
} else {
    Write-Host "  ✓ Venv not found — already removed"
}


# ── STEP 4: Remove data directory ────────────────────────────────────────────

Write-Host ""
Write-Host "[4/4] Data directory..."
Write-Host ""
Write-Host "  Your data and memory are stored in:"
Write-Host "  $mnemoDir"
Write-Host ""

$answer = Read-Host "  Delete all Mnemostroma data and memory? [y/N]"

if ($answer -eq "y" -or $answer -eq "Y") {
    Stop-Transcript
    try {
        Remove-Item $mnemoDir -Recurse -Force
        Write-Host "  ✓ Removed: $mnemoDir"
    } catch {
        Write-Host "  ❌ Could not fully remove data directory: $_"
        Write-Host "    Remove manually: rmdir /s /q `"$mnemoDir`""
    }
} else {
    Write-Host "  Keeping data directory (logs and memory preserved)."
    Write-Host "  To remove manually later:"
    Write-Host "    rmdir /s /q `"$mnemoDir`""
    Stop-Transcript
}


# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "==================================================================="
Write-Host "  Mnemostroma has been uninstalled."
Write-Host "==================================================================="
Write-Host ""
Write-Host "  To reinstall:"
Write-Host "    https://github.com/GG-QandV/mnemostroma#windows"
Write-Host ""
