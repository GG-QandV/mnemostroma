#!/usr/bin/env python3
"""
Mnemostroma Absolute Cleanup Utility
Kills all rogue, duplicate, or zombie processes left over in RAM after crashes 
or incorrect updates, without touching the local databases.
"""
import os
import sys
import subprocess
import signal

try:
    import psutil
except ImportError:
    # Auto-relaunch inside Mnemostroma's venv where psutil is guaranteed to exist
    venv_python = os.path.expanduser("~/.mnemostroma/venv/bin/python3")
    if os.name == 'nt':
        venv_python = os.path.expanduser("~\\.mnemostroma\\venv\\Scripts\\python.exe")
    if os.path.exists(venv_python) and sys.executable != venv_python:
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("Error: 'psutil' module not found and Mnemostroma venv is missing.")
        print("Please run inside the venv or install psutil: pip install psutil")
        sys.exit(1)

def stop_systemd_services():
    """Attempt to gracefully stop systemd user services first"""
    services = [
        "mnemostroma.service",
        "mnemostroma-daemon.service",
        "mnemostroma-proxy.service",
        "mnemostroma-watchdog.service",
        "mnemostroma-ui.service",
        "mnemostroma-sse.service",
        "mnemostroma-tunnel.service",
        "mnemostroma-serveo.service"
    ]
    print("Stopping system services...")
    for svc in services:
        subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True)

def find_and_kill():
    targets = [
        "-m mnemostroma",
        "bin/mnemostroma",
        "mnemostroma.exe",
        "context-manager/mcp/server.js",
        "perplexity-mcp",
        "mcp_stdio_adapter"
    ]
    
    killed = 0
    errors = 0
    
    for p in psutil.process_iter(['pid', 'cmdline', 'name']):
        try:
            cmdline = p.info['cmdline'] or []
            cmd_str = " ".join(cmdline)
            
            # Prevent suicide and do not kill the IDE layer
            if "clean-zombies.py" in cmd_str:
                continue
            if "language_server" in cmd_str or "Code" in cmd_str or "antigravity" in cmd_str:
                continue
                
            # If any target string is in the process command
            if any(t in cmd_str for t in targets):
                print(f"🗡️  Killing PID {p.info['pid']}: {cmd_str[:80]}...")
                
                # First try SIGTERM
                p.terminate()
                
                try:
                    p.wait(timeout=2)
                except psutil.TimeoutExpired:
                    # Escalation
                    print(f"   ↳ Force killing PID {p.info['pid']}...")
                    p.kill()
                    
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            errors += 1
        except Exception as e:
            print(f"Error handling PID {p.info.get('pid', '?')}: {e}")
            errors += 1
            
    print("\n--- Summary ---")
    print(f"Terminated/Killed: {killed} processes.")
    if errors > 0:
        print(f"Access Denied/Errors: {errors}")
        
    if killed > 0:
        print("\nClean complete. To restart safely, run:\n  mnemostroma service install && mnemostroma on")
    else:
        print("\nNo zombie instances found. RAM is clean.")

if __name__ == "__main__":
    stop_systemd_services()
    find_and_kill()
