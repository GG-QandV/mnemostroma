@echo off
:: Mnemostroma — Windows Installer Launcher
:: Double-click this file to install Mnemostroma.
:: No administrator rights required.

title Mnemostroma Installer
color 0A
echo.
echo  ==========================================
echo    Mnemostroma — Windows Installer
echo  ==========================================
echo.
echo  Downloading installer, please wait...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-windows.ps1' -OutFile '%TEMP%\mnemo-install.ps1'"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ERROR: Download failed. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo  Running installer...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\mnemo-install.ps1"

echo.
echo  ==========================================
echo  Done. You can close this window.
echo  ==========================================
echo.
pause
