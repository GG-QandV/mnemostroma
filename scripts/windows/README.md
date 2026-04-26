# Mnemostroma Daemon Installation — Windows (Task Scheduler)

Self-hosted Task Scheduler task for Mnemostroma daemon.

## Files

- **install-daemon.ps1** — Installation script (PowerShell)

## Installation

**Requirements:**
- PowerShell 5.0+ (or PowerShell Core 7+)
- No administrator privileges required for current-user installation.

**Steps:**

1. Open PowerShell.

2. Allow script execution (if not already enabled):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

3. Run the installer:
```powershell
.\scripts\windows\install-daemon.ps1
```

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

## Details

- User-level task (visible only to current user).
- Trigger: At logon (on user login).
- Restart: Automatic restart if the process crashes.
- Socket location: `%USERPROFILE%\.mnemostroma\daemon.sock`
