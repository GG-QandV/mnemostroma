@echo off
:: Mnemostroma - Windows Uninstaller Launcher
:: Double-click this file to uninstall Mnemostroma.

title Mnemostroma Uninstaller
color 0C
echo.
echo  ==========================================
echo    Mnemostroma - Uninstaller
echo  ==========================================
echo.
echo  Downloading uninstaller, please wait...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/uninstall-windows.ps1' -OutFile '%TEMP%\mnemo-uninstall.ps1'"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ERROR: Download failed. Check your internet connection.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\mnemo-uninstall.ps1"

echo.
echo  ==========================================
echo  Done. You can close this window.
echo  ==========================================
echo.
pause
