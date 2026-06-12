# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma cleanup module.

Provides a robust mechanism to terminate zombie and rogue processes without killing
the system tray or IDE processes. Supports both Linux and Windows platforms.
"""
import os
import subprocess
import sys
import time

# Ensure psutil is available
try:
    import psutil
except ImportError:
    # We are inside the main codebase, we assume psutil is either in current env or venv
    pass


def restart_daemon_services() -> None:
    """Restart daemon via systemctl without stopping the tray.

    systemd handles the cascade via BindsTo/Wants in the unit files.
    Fallback for non-systemd: _cmd_off() + _cmd_on() (blocks caller thread up to ~60s).
    """
    import shutil
    if sys.platform != "win32" and shutil.which("systemctl"):
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "mnemostroma-daemon"],
                capture_output=True,
            )
        except Exception as e:
            print(f"systemctl restart failed: {e}")
        return
    # Non-systemd fallback
    from mnemostroma.cli.commands import _cmd_off, _cmd_on
    _cmd_off()
    time.sleep(1)
    _cmd_on()


def stop_services() -> None:
    """Stop all Mnemostroma services based on the operating system."""
    if sys.platform == "win32":
        # Windows: Stop SCM service and tasks
        print("Stopping Windows services and scheduled tasks...")
        try:
            # Stop Windows Service
            subprocess.run(
                ["powershell", "-Command", "Stop-Service -Name mnemostroma-service -Force"],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            print(f"Failed to stop Windows Service: {e}")

        try:
            # End scheduled tasks
            subprocess.run(
                ["schtasks", "/End", "/TN", "Mnemostroma Daemon Watchdog"],
                capture_output=True,
                timeout=5
            )
            subprocess.run(
                ["schtasks", "/End", "/TN", "Mnemostroma Proxy Server"],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            print(f"Failed to end Windows scheduled tasks: {e}")
    else:
        # Linux: Stop systemd user units
        services: list[str] = [
            "mnemostroma.service",
            "mnemostroma-daemon.service",
            "mnemostroma-proxy.service",
            "mnemostroma-watchdog.service",
            "mnemostroma-ui.service",
            "mnemostroma-tunnel.service",
            "mnemostroma-serveo.service"
        ]
        print("Stopping systemd user services...")
        for svc in services:
            try:
                subprocess.run(
                    ["systemctl", "--user", "stop", svc],
                    capture_output=True,
                    timeout=5
                )
            except Exception as e:
                print(f"Failed to stop service {svc}: {e}")


def start_services() -> None:
    """Start all Mnemostroma services back up based on the operating system."""
    if sys.platform == "win32":
        print("Starting Windows services...")
        try:
            # Try SCM service first
            res = subprocess.run(
                ["powershell", "-Command", "Start-Service -Name mnemostroma-service"],
                capture_output=True,
                timeout=10
            )
            if res.returncode == 0:
                print("Windows Service started successfully.")
                return
        except Exception as e:
            print(f"Failed to start Windows Service: {e}")

        try:
            # Fallback to scheduled tasks
            subprocess.run(
                ["schtasks", "/Run", "/TN", "Mnemostroma Daemon Watchdog"],
                capture_output=True,
                timeout=5
            )
            print("Scheduled tasks started.")
        except Exception as e:
            print(f"Failed to run Windows scheduled tasks: {e}")
    else:
        print("Starting systemd user services...")
        # Start daemon, proxy, watchdog
        for svc in ["mnemostroma-daemon.service", "mnemostroma-proxy.service", "mnemostroma-watchdog.service", "mnemostroma-tunnel.service"]:
            try:
                subprocess.run(
                    ["systemctl", "--user", "start", svc],
                    capture_output=True,
                    timeout=10
                )
                print(f"Started {svc}")
            except Exception as e:
                print(f"Failed to start service {svc}: {e}")


def emergency_cleanup(restart_services: bool = True) -> None:
    """Aggressively terminate rogue Mnemostroma and MCP processes while preserving tray/IDE.

    Args:
        restart_services: Whether to restart the core services after killing zombie processes.
    """
    # 1. Stop existing services
    stop_services()

    # Give them a moment to stop
    time.sleep(1.0)

    # 2. Identify target processes and kill them
    targets: list[str] = [
        "-m mnemostroma",
        "bin/mnemostroma",
        "mnemostroma.exe",
        "context-manager/mcp/server.js",
        "perplexity-mcp",
        "mcp_stdio_adapter"
    ]

    # Explicitly avoid killing these (suicide prevention)
    avoid_keywords: list[str] = [
        "tray_pyqt",
        "tray.py",
        "tray_old_pystray",
        "clean-zombies.py",
        "cleanup.py",
        "language_server",
        "Code",
        "antigravity",
        "python-lsp"
    ]

    my_pid = os.getpid()
    killed = 0
    errors = 0

    try:
        import psutil
    except ImportError:
        print("Error: 'psutil' is required for cleanup logic.")
        return

    for p in psutil.process_iter(['pid', 'cmdline', 'name']):
        try:
            pid = p.info['pid']
            if pid == my_pid:
                continue

            cmdline = p.info['cmdline'] or []
            cmd_str = " ".join(cmdline)

            # Avoid suicide / IDE processes
            if any(k in cmd_str for k in avoid_keywords):
                continue

            # If any target string is in the process command
            if any(t in cmd_str for t in targets):
                print(f"🗡️  Killing PID {pid}: {cmd_str[:80]}...")
                p.terminate()
                try:
                    p.wait(timeout=2)
                except psutil.TimeoutExpired:
                    print(f"   ↳ Force killing PID {pid}...")
                    p.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            errors += 1
        except Exception as e:
            print(f"Error handling PID {p.info.get('pid', '?')}: {e}")
            errors += 1

    print("\n--- Cleanup Summary ---")
    print(f"Terminated/Killed: {killed} processes.")
    if errors > 0:
        print(f"Access Denied/Errors: {errors}")

    # 3. Restart services if requested
    if restart_services:
        time.sleep(1.0)
        start_services()
        print("Services restarted successfully.")
