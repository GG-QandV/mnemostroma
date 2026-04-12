# Mnemostroma Daemon Installation — Windows (Task Scheduler)

Self-hosted Task Scheduler task for Mnemostroma daemon.

## Files

- **install-daemon.ps1** — Installation script (PowerShell)

## Installation

**Requirements:**
- PowerShell 5.0+ (or PowerShell Core 7+)
- Administrator privileges

**Steps:**

1. Open PowerShell **as Administrator**

2. Allow script execution:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

3. Run the installer:
```powershell
cd C:\path\to\mnemostroma
.\scripts\windows\install-daemon.ps1
```

This will:
1. Check that Python venv exists at `%USERPROFILE%\.mnemostroma\venv\Scripts\python.exe`
2. Register "Mnemostroma Daemon" task in Task Scheduler
3. Start the daemon immediately

## Management

**Command line (PowerShell):**
```powershell
# Start
Start-ScheduledTask -TaskName "Mnemostroma Daemon"

# Stop
Stop-ScheduledTask -TaskName "Mnemostroma Daemon"

# View status
Get-ScheduledTaskInfo -TaskName "Mnemostroma Daemon"

# Uninstall
Unregister-ScheduledTask -TaskName "Mnemostroma Daemon" -Confirm:$false
```

**GUI:**
```powershell
taskschd.msc
```

Then navigate to: Task Scheduler Library → Mnemostroma Daemon

## Details

- User-level task (visible only to current user)
- Trigger: At logon (on user login)
- Restart: 999 times, every 5 seconds if crashed
- Socket location: `%USERPROFILE%\.mnemostroma\daemon.sock`
- Logs: check Windows Event Viewer or run `python -m mnemostroma status` after restart
