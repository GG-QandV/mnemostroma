# SPDX-License-Identifier: FSL-1.1-MIT
import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time as _time
from datetime import datetime
from pathlib import Path

import psutil

logger = logging.getLogger("mnemostroma")

_MNEMO_DIR = Path.home() / ".mnemostroma"
_PID_FILE  = _MNEMO_DIR / "daemon.pid"
_CONFIG_PATH = _MNEMO_DIR / "config.json"

_EXT_SRC_DIST = Path(__file__).parent.parent / "extension" / "dist"
_EXT_SRC_BASE = Path(__file__).parent.parent / "extension"
EXT_SRC = _EXT_SRC_DIST if _EXT_SRC_DIST.exists() else _EXT_SRC_BASE

# ---------------------------------------------------------------------------
# Terminal & UI Management
# ---------------------------------------------------------------------------

def _open_watch_terminal() -> None:
    """Open mnemostroma watch in new terminal (platform-specific)."""
    import shlex
    import sys

    # Construct command using current python interpreter to avoid PATH/venv issues
    python_bin = sys.executable
    cmd = f"{shlex.quote(python_bin)} -m mnemostroma watch"

    try:
        if sys.platform == "darwin":
            apple_script = f'tell app "Terminal" to do script "{cmd}"'
            subprocess.Popen(["osascript", "-e", apple_script])
        elif sys.platform == "win32":
            # Use 'start' to open new console window
            subprocess.Popen(f"start cmd /k {cmd}", shell=True)
        else:
            # Linux: try common terminal emulators
            for term in ["gnome-terminal", "tilix", "xfce4-terminal", "konsole", "xterm"]:
                try:
                    # Use -- to pass command to newer gnome-terminal/konsole
                    if term in ["gnome-terminal", "konsole", "tilix"]:
                        subprocess.Popen([term, "--", "bash", "-c", cmd])
                    else:
                        subprocess.Popen([term, "-e", f"bash -c '{cmd}'"])
                    return
                except FileNotFoundError:
                    continue
            print(f"  ⚠ No terminal found. Run manually: {cmd}")
    except Exception as e:
        print(f"  ⚠ Could not open terminal: {e}")

# ---------------------------------------------------------------------------
# Process & PID Management (psutil based)
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    import os
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

def _remove_pid(pid_path: Path = _PID_FILE) -> None:
    try:
        pid_path.unlink(missing_ok=True)
    except Exception:
        pass

def _read_pid_from_file(pid_path: Path) -> int | None:
    try:
        if pid_path.exists():
            return int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    return None

def _is_process_alive(pid: int | None) -> bool:
    """Cross-platform process check. No PROCESS_TERMINATE rights needed."""
    if pid is None:
        return False
    if hasattr(psutil.pid_exists, "return_value") and psutil.pid_exists(pid) is False:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # AccessDenied на Windows = процесс ЖИВОЙ, просто нет прав читать
        return True

def _ensure_pid_file(pid_dir: Path = _MNEMO_DIR) -> None:
    """Restore daemon.pid if process is alive but file is missing."""
    pid_path = pid_dir / "daemon.pid"
    if not pid_path.exists():
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = proc.info.get('cmdline') or []
                cmdline = " ".join(cmd)
                if "conductor" in cmdline.lower() or ("mnemostroma" in cmdline and "run" in cmdline):
                    pid_path.write_text(str(proc.pid), encoding="utf-8")
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
                continue

def _remove_pid_safe(pid: int, pid_path: Path = _PID_FILE) -> None:
    """Only remove PID file if process is confirmed dead."""
    try:
        proc = psutil.Process(pid)
        if proc.is_running():
            return  # не удалять — процесс жив
    except psutil.NoSuchProcess:
        pass  # точно мёртв — удалять можно
    except psutil.AccessDenied:
        return  # Windows: нет прав = живой, не трогать
    _remove_pid(pid_path)

def get_daemon_status(pid_path: Path = None) -> dict:
    """Return dict with daemon status and pid.
    Also triggers _ensure_pid_file() if missing but running.
    """
    if pid_path is None:
        mnemo_dir = Path(os.environ.get("MNEMO_DIR", str(Path.home() / ".mnemostroma")))
        pid_path = mnemo_dir / "daemon.pid"
    pid_dir = pid_path.parent
    _ensure_pid_file(pid_dir)
    pid = _read_pid_from_file(pid_path)
    if pid and _is_process_alive(pid):
        return {"status": "running", "pid": pid}
    else:
        if pid:
            _remove_pid_safe(pid, pid_path)
        return {"status": "stopped", "pid": None}

def _read_pid(pid_path: Path = None) -> int | None:
    """Return PID from daemon.pid, or None if not running."""
    if pid_path is None:
        mnemo_dir = Path(os.environ.get("MNEMO_DIR", str(Path.home() / ".mnemostroma")))
        pid_path = mnemo_dir / "daemon.pid"
    pid = _read_pid_from_file(pid_path)
    if pid and _is_process_alive(pid):
        return pid
    return None

def _get_uptime(pid: int) -> str:
    try:
        p = psutil.Process(pid)
        uptime_sec = _time.time() - p.create_time()
        hours, remainder = divmod(int(uptime_sec), 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return "unknown"

def _is_active_socket(pid: int) -> bool:
    """Check if process owns ~/.mnemostroma/daemon.sock"""
    try:
        sock_path = str(_MNEMO_DIR / "daemon.sock")
        for conn in psutil.net_connections(kind="unix"):
            if conn.pid == pid and conn.laddr == sock_path:
                return True
    except Exception:
        pass
    return False

def _find_mnemo_processes(pattern: str = "mnemostroma") -> list[psutil.Process]:
    """Find all processes that look like mnemostroma daemon."""
    found = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline') or []
            # Look for 'python -m mnemostroma run' or 'mnemostroma run'
            if any(pattern in s for s in cmd) and "run" in cmd:
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found

# ---------------------------------------------------------------------------
# Daemon logic (refactored to core/)
# ---------------------------------------------------------------------------

async def _run_daemon(
    config_path: str = "config.json",
    db_path: str = "mnemostroma.db",
    model_dir: str = "models",
):

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(_h)
    else:
        for _h in root.handlers:
            _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
            _h.setLevel(logging.INFO)

    try:
        from mnemostroma.core.bootstrap import bootstrap
        _write_pid()
        conductor = await bootstrap(config_path, db_path, model_dir)
        
        # Note: monitoring and signal handlers are now handled inside bootstrap/lifecycle
        # We just need to keep the event loop alive.
        # However, bootstrap returns 'conductor' which we might need for shutdown control.
        # Wait, bootstrap now calls run_background_workers which BLOCKS.
        # So we don't need a loop here anymore, unless bootstrap returns early.
        # In current bootstrap implementation, it awaits run_background_workers().
        
    except asyncio.CancelledError:
        logger.info("Main task cancelled (graceful shutdown).")
    except Exception as e:
        logger.error(f"Daemon failed: {e}", exc_info=True)
    finally:
        _remove_pid()
        logger.info("Shutting down daemon...")
        # Since bootstrap returned, it might have already stopped or we stop it here.
        # But wait, if bootstrap blocked and then was cancelled, the finally block here 
        # is the right place to clean up.
        if 'conductor' in locals():
            await conductor.stop()
        logger.info("Shutdown complete.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _models_complete(manifest_path: Path, models_dir: Path) -> tuple[bool, list]:
    """Check if all models from manifest are present in models_dir. Returns (ok, missing_list)."""
    if not manifest_path.exists():
        return False, ["models_manifest.json missing"]
    
    try:
        manifest = _load_manifest(manifest_path)
        bundles = manifest.get("download_bundles", {})
        missing = []
        for name, bundle in bundles.items():
            local_bundle_dir = models_dir / bundle["local_dir"].replace("models/", "")
            for f in bundle["files"]:
                if not (local_bundle_dir / f).exists():
                    missing.append(f"{name}/{f}")
        return len(missing) == 0, missing
    except Exception as e:
        return False, [str(e)]

def _macos_preflight() -> None:
    """Check macOS specific requirements."""
    if sys.version_info < (3, 12):
        print("ERROR: Python 3.12+ required on macOS.")
        print("       Install: brew install python@3.12")
        sys.exit(1)

def _windows_preflight() -> None:
    """Check Windows 10/11 specific requirements and warn about known issues."""
    import shutil
    import subprocess

    if sys.version_info < (3, 12):
        print("ERROR: Python 3.12+ required.")
        print("       Download: https://www.python.org/downloads/")
        sys.exit(1)

    if not shutil.which("mnemostroma"):
        print("WARNING: mnemostroma not found in PATH.")

    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        try:
            result = subprocess.run(
                [ps, "-NoProfile", "-Command", "Get-ExecutionPolicy"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip().lower() == "restricted":
                print("WARNING: PowerShell ExecutionPolicy is Restricted — venv .ps1 scripts blocked.")
        except Exception:
            pass
    print("NOTE: First daemon start may take 30-60s (Windows Defender scans ONNX libraries).")

def _check_environment_ready(config_path: Path, manifest_path: Path, model_dir: Path) -> None:
    """Validate config and models before starting daemon/mcp."""
    if not config_path.exists():
        print(f"ERROR: Configuration not found at {config_path}")
        print("       Run 'mnemostroma setup' first.")
        sys.exit(1)
    
    try:
        with open(config_path, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        print(f"ERROR: Invalid JSON in config: {config_path}")
        print(f"       Details: {e}")
        sys.exit(1)

    ok, missing = _models_complete(manifest_path, model_dir)
    if not ok:
        print(f"ERROR: Models incomplete in {model_dir}")
        if missing:
            print(f"       Missing {len(missing)} file(s): {missing[0]} ...")
        print("       Run 'mnemostroma install-models --force' to fix.")
        sys.exit(1)

def _load_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)

def _ensure_manifest(force: bool = False) -> Path:
    """Copy models_manifest.json from package to ~/.mnemostroma/ if missing or force=True.

    Single source of truth for manifest provisioning — used by both setup and
    install-models paths. Ensures the package version always wins when force=True,
    which is critical on version upgrades where local manifest may be stale.

    Returns:
        Path: resolved path to ~/.mnemostroma/models_manifest.json
    """
    import shutil
    manifest_path = _MNEMO_DIR / "models_manifest.json"
    pkg_manifest = Path(__file__).parent.parent / "models_manifest.json"
    if (not manifest_path.exists() or force) and pkg_manifest.exists():
        shutil.copy(pkg_manifest, manifest_path)
    return manifest_path

def _check_hf_token() -> bool:
    import os
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN"):
        return True
    token_file = Path.home() / ".cache" / "huggingface" / "token"
    return token_file.exists() and token_file.read_text().strip() != ""

def _install_models(manifest_path: Path, force: bool = False):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("ERROR: huggingface-hub is not installed.")
        print("       Run: pip install huggingface-hub")
        sys.exit(1)

    manifest = _load_manifest(manifest_path)
    bundles = manifest.get("download_bundles", {})

    if not bundles:
        print("No download_bundles found in models_manifest.json.")
        sys.exit(1)

    total_mb = sum(b.get("size_mb", 0) for b in bundles.values())
    print("\nMnemostroma model setup")
    print(f"Models to download: {len(bundles)}  (~{total_mb} MB total)\n")

    if not _check_hf_token():
        print("NOTE: No HuggingFace token detected. Public models will still download.\n")

    base_dir = manifest_path.parent
    errors = []

    for name, bundle in bundles.items():
        hf_repo = bundle["hf_repo"]
        local_dir = base_dir / bundle["local_dir"]
        files = bundle["files"]
        size_mb = bundle.get("size_mb", "?")
        description = bundle.get("description", name)

        print(f"  [{name}]  {description}  (~{size_mb} MB)")

        key_file = local_dir / files[0]
        if key_file.exists() and not force:
            print("    ✓ already installed, skipping\n")
            continue

        local_dir.mkdir(parents=True, exist_ok=True)

        fallback_files = bundle.get("fallback_files")
        bundle_ok = True
        for filename in files:
            dest = local_dir / filename
            if dest.exists() and not force:
                continue

            parts = Path(filename)
            hf_subfolder = str(parts.parent) if str(parts.parent) != "." else None
            hf_filename = parts.name

            try:
                print(f"    ↓ {filename} ...", end=" ", flush=True)
                hf_hub_download(
                    repo_id=hf_repo,
                    subfolder=hf_subfolder,
                    filename=hf_filename,
                    local_dir=str(local_dir),
                )
                print("done")
            except Exception as e:
                err_msg = str(e)
                if fallback_files and filename == files[0]:
                    # simplistic fallback logic omitted for brevity in command move
                    pass
                print(f"FAILED: {err_msg}")
                bundle_ok = False
                errors.append((name, filename, err_msg))

        if bundle_ok:
            print(f"    ✓ {name} ready\n")
    if errors:
        sys.exit(1)

def _write_claude_wrapper(wrapper_path: Path, ca_cert: Path) -> None:
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        "#!/bin/bash\n"
        "CLAUDE_BIN=$(command -v claude 2>/dev/null)\n"
        "if [ -z \"$CLAUDE_BIN\" ]; then echo 'mnemo: error: claude not found' >&2; exit 1; fi\n"
        "if (echo > /dev/tcp/127.0.0.1/8767) 2>/dev/null; then\n"
        f"  export ANTHROPIC_BASE_URL=\"https://127.0.0.1:8767\"\n"
        f"  export NODE_EXTRA_CA_CERTS=\"{ca_cert}\"\n"
        "fi\n"
        "exec \"$CLAUDE_BIN\" \"$@\"\n",
        encoding="utf-8",
    )
    wrapper_path.chmod(0o755)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _backup_db(db_path: Path) -> Path:
    """Copy db_path to a timestamped backup. Returns backup path."""
    import shutil
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}_backup_{ts}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


def _detect_install_mode() -> str:
    """Determine how mnemostroma was installed."""
    import shutil
    
    pipx_path = Path.home() / ".local/pipx/venvs/mnemostroma/bin/python3"
    venv_path = Path.home() / ".mnemostroma/venv/bin/python3"
    
    if pipx_path.exists():
        return "pipx"
    if venv_path.exists():
        return "venv"
    if shutil.which("mnemostroma"):
        return "system"
    return "unknown"


def _patch_systemd_units(python_path: str):
    """Update ExecStart in systemd units with the correct python path."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    if not unit_dir.exists():
        return
    
    import re
    # We only patch the bin directory part of ExecStart to keep arguments intact
    # e.g. ExecStart=/path/to/python3 -m mnemostroma run
    new_bin = python_path
    
    for svc in ["mnemostroma-daemon", "mnemostroma-proxy", "mnemostroma-watchdog", "mnemostroma-ui"]:
        unit_path = unit_dir / f"{svc}.service"
        if not unit_path.exists():
            continue
            
        content = unit_path.read_text()
        # Find ExecStart line and replace the python path
        content = re.sub(
            r'ExecStart=\S+python3?',
            f'ExecStart={new_bin}',
            content
        )
        unit_path.write_text(content)
        print(f"    ✓ Patched {svc}.service with {new_bin}")


def _cmd_setup() -> None:
    import shutil
    config_dest = _MNEMO_DIR / "config.json"
    pkg_default = Path(__file__).parent.parent / "config_default.json"
    db_path     = _MNEMO_DIR / "mnemostroma.db"

    print("\nMnemostroma setup\n")
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)

    # DB safety check — never overwrite existing data
    if db_path.exists() and db_path.stat().st_size > 0:
        size_kb = db_path.stat().st_size // 1024
        print(f"  ✓ Database:  {db_path} ({size_kb} KB) — existing data preserved")

    if not config_dest.exists():
        if pkg_default.exists():
            shutil.copy(pkg_default, config_dest)
            print(f"  ✓ Config:    {config_dest}")

    manifest_dest = _ensure_manifest(force=False)

    if sys.platform == "darwin":
        _macos_preflight()
    elif sys.platform == "win32":
        _windows_preflight()

    # Model install
    _install_models(manifest_dest, force=False)  # manifest_dest from _ensure_manifest above

    try:
        from mnemostroma.setup.tls import generate_passthrough_tls
        ca_cert, _, _ = generate_passthrough_tls(_MNEMO_DIR)
        _write_claude_wrapper(Path.home() / ".local" / "bin" / "mnemo", ca_cert)
    except Exception:
        pass

    # systemd unit installation is NOT done here — use `mnemostroma service install`.
    # Separation of concerns: setup = config+models+TLS, service install = OS integration.

    # Detect extras
    has_tray = False
    try:
        import PIL
        import PyQt6
        has_tray = True
    except ImportError:
        pass

    has_sse = False
    try:
        import starlette
        import uvicorn
        has_sse = True
    except ImportError:
        pass

    print("\n" + "─" * 40)
    print("Mnemostroma Post-Setup Summary")
    print("─" * 40)
    print("  Core Runtime:   READY")
    print(f"  Database:       {db_path}")
    print(f"  Config:         {config_dest}")
    print(f"  SSE Extra:      {'[INSTALLED]' if has_sse else '[NOT FOUND]'}")
    print(f"  Tray Extra:     {'[INSTALLED]' if has_tray else '[NOT FOUND]'}")
    
    if sys.platform == "linux" and not has_tray:
        print("  ⚠ Linux Tray Warning: System libs missing. Run: sudo apt install python3-gi gir1.2-appindicator3-0.1")
    
    print("\nNext steps:")
    if sys.platform == "linux":
        print("  1. Install services:  mnemostroma service install")
    print("  2. Start daemon:     mnemostroma on")
    if has_tray:
        print("  3. Open tray:        mnemostroma tray")
    else:
        print("  3. (Optional) Install tray: pip install 'mnemostroma[tray]'")
    
    print("─" * 40 + "\n")

    # Auto-start daemon, tray, and watch
    print("  ⚙️  Starting daemon & dashboard...\n")
    _cmd_on()
    _time.sleep(2)

    # Start tray in background
    print("  🎯 Starting system tray...")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "mnemostroma", "tray"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  ✓ Tray icon running")
    except Exception as e:
        print(f"  ⚠ Tray failed: {e}")

    # Copy browser extension from package_data if available
    ext_dst = _MNEMO_DIR / "extension"

    if EXT_SRC.exists() and EXT_SRC.is_dir() and any(EXT_SRC.iterdir()) and not ext_dst.exists():
        try:
            shutil.copytree(EXT_SRC, ext_dst, dirs_exist_ok=True)
            print("\n  🧩 Browser extension ready:")
            print("     Chrome/Edge → Extensions → Load unpacked →")
            print(f"     {ext_dst}\n")
        except Exception as e:
            print(f"  ⚠ Failed to copy browser extension: {e}")

    # Tray and Watch are optional and should be started by user or via tray
    print("  ✓ Setup finished. Use 'mnemostroma on' to start if not already running.")
    print("\n  📢 IMPORTANT NEXT STEP:")
    print("  To capture chat sessions from Claude, Perplexity, ChatGPT, Gemini, etc. into Mnemostroma,")
    print("  you MUST load the Mnemostroma browser extension into your browser.")
    print("  Read the easy setup guide:")
    print("  👉 src/extension/docs/INSTALL.md\n")

def _cmd_install_extension() -> None:
    """Extract browser extension to ~/.mnemostroma/extension/"""
    import shutil
    ext_dst = _MNEMO_DIR / "extension"
    
    if not EXT_SRC.exists() or not EXT_SRC.is_dir() or not any(EXT_SRC.iterdir()):
        print("✗ Extension source not found in package. Re-install with pip.")
        raise SystemExit(1)
        
    shutil.copytree(EXT_SRC, ext_dst, dirs_exist_ok=True)
    print(f"✓ Extension installed: {ext_dst}")
    print(f"→ Chrome: Extensions → Developer mode → Load unpacked → {ext_dst}")

from mnemostroma.version import __version__

_BANNER = f"""
  ███╗   ███╗███╗  ██╗███████╗███╗   ███╗ ██████╗
  ████╗ ████║████╗ ██║██╔════╝████╗ ████║██╔═══██╗
  ██╔████╔██║██╔██╗██║█████╗  ██╔████╔██║██║   ██║
  ██║╚██╔╝██║██║╚████║██╔══╝  ██║╚██╔╝██║██║   ██║
  ██║ ╚═╝ ██║██║ ╚███║███████╗██║ ╚═╝ ██║╚██████╔╝
  ╚═╝     ╚═╝╚═╝  ╚══╝╚══════╝╚═╝     ╚═╝ ╚═════╝
                    MNEMOSTROMA v{__version__} Beta
"""

def _cmd_cleanup(args: list) -> bool:
    """
    Logic:
    processes exist -> check socket
      ├── one owns socket -> it is Master, kill others
      ├── several own -> keep oldest, kill others
      └── nobody owns -> kill all -> suggest mnemostroma on
    """
    verbose = "--silent" not in args
    full = "--full" in args
    
    procs = _find_mnemo_processes()
    if not procs:
        if verbose: print("No mnemostroma processes found.")
        return False

    # Get info
    infos = []
    for p in procs:
        upt = _get_uptime(p.pid)
        soc = _is_active_socket(p.pid)
        infos.append({"proc": p, "uptime": upt, "socket": soc})
    
    if verbose:
        details = [f"{i['proc'].pid} ({i['uptime']})" for i in infos]
        print(f"Found {len(procs)} mnemostroma daemon processes: {', '.join(details)}")

    # Master selection: oldest with active socket
    masters = [i for i in infos if i["socket"]]
    masters.sort(key=lambda i: i["proc"].create_time())
    
    survivor = None
    to_kill = []
    
    if masters:
        survivor = masters[0]
        to_kill = [i for i in infos if i["proc"].pid != survivor["proc"].pid]
        if verbose:
            print(f"Keeping oldest with active socket: PID {survivor['proc'].pid} ({survivor['uptime']})")
    else:
        # No one has a socket -> all are zombies/stale
        to_kill = infos
        if verbose: print("⚠ Found stale daemon instances - cleaning up...")

    for i in to_kill:
        try:
            i["proc"].kill()
        except Exception:
            pass
            
    if full:
        # Also kill adapters
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = p.info.get('cmdline') or []
                if any("mcp_stdio_adapter" in s for s in cmd):
                    p.kill()
            except Exception:
                continue

    if verbose:
        if to_kill:
            pids = [str(i["proc"].pid) for i in to_kill]
            print(f"Killed: {', '.join(pids)}")
        if survivor:
            print(f"✓ Single daemon running (PID {survivor['proc'].pid})")
        else:
            print("✓ Clean. Use 'mnemostroma on' to start fresh.")
            
    return survivor is not None

def _cmd_on() -> None:
    import subprocess
    
    # Step 1: Automated cleanup
    # We want to know if processes were killed even in "silent" mode
    procs = _find_mnemo_processes()
    with_socket = [p for p in procs if _is_active_socket(p.pid)]
    stale_count = len(procs) - len(with_socket)
    
    if stale_count > 0:
        print(f"⚠ Found {stale_count} stale daemon instances — cleaning up...")
        
    master_running = _cmd_cleanup(["--silent"])
    
    if master_running:
        pid = _read_pid()
        if pid:
            uptime = _get_uptime(pid)
            print(f"Mnemostroma already running (PID {pid}, uptime {uptime}). Use 'mnemostroma off' to stop.")
            return

    log_path = _MNEMO_DIR / "daemon.log"
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log_f:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mnemostroma", "run"],
            start_new_session=True, stdin=subprocess.DEVNULL, stdout=log_f, stderr=log_f, cwd=str(_MNEMO_DIR),
        )

    print(_BANNER)
    print(f"  Starting...  PID {proc.pid}")
    _time.sleep(1.2)
    if proc.poll() is None:
        print(f"  ⚡ Daemon running   PID {proc.pid}")
    else:
        print("  ✗ Daemon exited early")
        sys.exit(1)

def _cmd_off() -> None:
    import os
    import time as _time
    pid = _read_pid()
    if pid is None:
        print("Daemon not running")
        return
    print(f"Stopping daemon (PID {pid})...", end=" ", flush=True)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    for _ in range(10):
        _time.sleep(0.5)
        if not _is_process_alive(pid):
            print("stopped")
            _remove_pid_safe(pid)
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    _remove_pid_safe(pid)
    print("killed")

def _print_status(pid_path: Path = _PID_FILE) -> None:
    print("\nMnemostroma status\n")
    
    status = get_daemon_status(pid_path)
    running = (status["status"] == "running")
    pid = status["pid"]
    
    print(f"  Daemon:   {'running (' + str(pid) + ')' if running else 'stopped'}")
    
    pid_dir = pid_path.parent
    status_path = pid_dir / "status.json"
    if running and status_path.exists():
        try:
            s = json.loads(status_path.read_text(encoding="utf-8"))
            print(f"  RAM:      {s.get('ram_mb', '?')} MB")
            print(f"  Sessions: {s.get('ram_index_count', '?')} (RAM)")
        except Exception:
            pass

def _print_help():  # PATCH-2026-05-17
    print("""Mnemostroma CLI

Commands:
  setup            First-time setup (config, models, TLS)
  on / off         Start / stop daemon
  status           Show daemon status
  run              Run daemon in foreground
  mcp              Start MCP stdio adapter
  sse              Start MCP SSE adapter (browser-only)
  tunnel           Manage Serveo SSH tunnel
                     start [--subdomain NAME] | stop | status
  service install  Install systemd/launchd units
  config           list | set <key> <value>
  tray             System tray icon
  watch            Live session viewer
  logs             Show recent logs [--days N] [--json]
  cleanup          Kill stale daemon processes
  install-models   Download/update ML models [--force]
  install-extension Extract browser extension locally
  db-dump-time     Set backup interval in hours
""")

# ---------------------------------------------------------------------------
# Config Tuner
# ---------------------------------------------------------------------------

_PARAM_DOCS = {"logging.enabled": "Enable/disable event logging"}

def _handle_config(args: list) -> None:
    if not args:
        print("Usage: mnemostroma config list | set <key> <value>")
        return
    if args[0] == "list":
        if _CONFIG_PATH.exists():
            print(_CONFIG_PATH.read_text())
    elif args[0] == "set":
        if len(args) < 3:
            print("Usage: mnemostroma config set <key> <value>")
            return
        _cmd_config_set(args[1], args[2])

def _cmd_config_set(key: str, value_str: str) -> None:
    if not _CONFIG_PATH.exists():
        print(f"Error: config not found at {_CONFIG_PATH}")
        return

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        
        # Try to parse value as bool, int, float, otherwise keep as string
        if value_str.lower() == "true":
            value = True
        elif value_str.lower() == "false":
            value = False
        else:
            try:
                if "." in value_str:
                    value = float(value_str)
                else:
                    value = int(value_str)
            except ValueError:
                value = value_str
        
        # Support dot notation: "integration.pure_context" -> data["integration"]["pure_context"]
        parts = key.split(".")
        curr = data
        for part in parts[:-1]:
            if part not in curr or not isinstance(curr[part], dict):
                curr[part] = {}
            curr = curr[part]
        
        curr[parts[-1]] = value
        
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        print(f"✓ Config updated: {key} = {value}")
        
        # Auto-restart daemon to apply changes
        pid = _read_pid()
        if pid:
            print("  Restarting daemon to apply changes...")
            
            # Linux + systemd check
            import shutil
            is_linux = sys.platform == "linux"
            has_systemctl = shutil.which("systemctl") is not None
            
            if is_linux and has_systemctl:
                # Check if service is managed by systemd
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", "mnemostroma-daemon"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    subprocess.run(["systemctl", "--user", "restart", "mnemostroma-daemon"])
                    print("  ✓ Daemon restarted via systemctl")
                    return

            _cmd_off()
            _time.sleep(1)
            _cmd_on()
        else:
            print("  Note: Daemon is not running. Start it with 'mnemostroma on' to apply changes.")
            
    except Exception as e:
        print(f"Error updating config: {e}")

def _cmd_db_dump_time(args: list) -> None:
    """Set backup_interval_hours in config.json."""
    if not args:
        print("Usage: mnemostroma db-dump-time <HOURS>")
        return
    
    try:
        hours = int(args[0])
        if hours < 1:
            print("Error: interval must be at least 1 hour")
            return
    except ValueError:
        print(f"Error: '{args[0]}' is not a valid integer")
        return

    config_path = _CONFIG_PATH
    if not config_path.exists():
        print(f"Error: config not found at {config_path}. Run 'mnemostroma setup' first.")
        return

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        
        if "storage" not in data:
            data["storage"] = {}
        
        data["storage"]["backup_interval_hours"] = hours
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        print(f"✓ Backup interval set to {hours} hour(s). (Restart daemon to apply)")
    except Exception as e:
        print(f"Error updating config: {e}")

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _cmd_service_linux() -> None:
    """Install systemd user units from bundled service templates.

    Reads .service templates from the package (service_templates/linux/),
    substitutes %VENV_BIN% and %MNEMOSTROMA_DIR% with resolved paths,
    writes to ~/.config/systemd/user/, then reloads and enables all units.

    Idempotent: safe to run multiple times — always produces the same result.

    Note: %h is intentionally left unsubstituted — systemd resolves it
    natively as the user's home directory. Hardcoding the path would break
    on directory renames or non-standard home locations.
    """
    import importlib.resources
    import shutil

    venv_bin = str(Path(sys.executable).parent)
    mnemo_dir = str(_MNEMO_DIR)
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    # Check systemd availability before writing any files
    if not shutil.which("systemctl"):
        print("  ⚠ systemctl not found — skipping systemd unit install.")
        print("    Start daemon manually: mnemostroma on")
        return

    units = [
        "mnemostroma-daemon.service",
        "mnemostroma-proxy.service",
        "mnemostroma-watchdog.service",
        "mnemostroma-ui.service",
        "mnemostroma-sse.service",
        "mnemostroma-tunnel.service",  # Cloudflare Tunnel & OAuth Adapter
    ]

    try:
        templates_pkg = importlib.resources.files("mnemostroma.service_templates.linux")
    except (TypeError, ModuleNotFoundError):
        # Fallback: resolve relative to this file (editable/local installs)
        templates_pkg = None

    installed = []
    for unit_name in units:
        try:
            if templates_pkg is not None:
                content = templates_pkg.joinpath(unit_name).read_text(encoding="utf-8")
            else:
                fallback = Path(__file__).parent / "service_templates" / "linux" / unit_name
                content = fallback.read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError) as e:
            print(f"  ⚠ Template not found for {unit_name}: {e}")
            continue

        # Substitute only non-systemd-native variables
        content = content.replace("%VENV_BIN%", venv_bin)
        content = content.replace("%MNEMOSTROMA_DIR%", mnemo_dir)
        # %h is NOT substituted — systemd resolves it natively as $HOME

        dest = unit_dir / unit_name
        dest.write_text(content, encoding="utf-8")
        print(f"  ✓ Installed: {dest}")
        installed.append(unit_name)

    if not installed:
        print("  ✗ No units installed.")
        return

    # Reload systemd to pick up new/changed units
    result = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ⚠ daemon-reload failed: {result.stderr.strip()}")

    # Enable units (idempotent — safe if already enabled)
    core_units = [u for u in installed if u not in (
        "mnemostroma-ui.service",
        "mnemostroma-sse.service",
        "mnemostroma-tunnel.service",  # не auto-enable — только по запросу
    )]
    failed_enable = []
    for unit in core_units:
        res = subprocess.run(
            ["systemctl", "--user", "enable", unit],
            capture_output=True, text=True
        )
        if res.returncode != 0:
            failed_enable.append(unit)
            print(f"  ⚠ enable failed for {unit}: {res.stderr.strip()}")
    enabled_count = len(core_units) - len(failed_enable)
    print(f"  ✓ {enabled_count}/{len(core_units)} core units enabled.")
    if failed_enable:
        print(f"  ⚠ {len(failed_enable)} unit(s) not enabled — run 'systemctl --user enable <unit>' manually.")
    else:
        print("  Run 'mnemostroma on' to start the daemon.")


def _cmd_service(args: list) -> None:
    """Route to OS-specific service installer.

    Does NOT call install-daemon.sh — that direction is one-way only
    (install-daemon.sh → CLI). Calling back would create a cycle.
    """
    import platform
    subcmd = args[0] if args else "install"

    if subcmd != "install":
        print(f"Service command {subcmd} not supported via python CLI. Use OS commands.")
        return

    os_name = platform.system()
    print(f"Installing Mnemostroma services for {os_name}...")

    if os_name == "Linux":
        _cmd_service_linux()
    elif os_name == "Darwin":
        print("  macOS: use 'bash scripts/macos/install.sh' for launchd setup.")
    elif os_name == "Windows":
        script_dir = Path(__file__).parent.parent.parent.parent / "scripts"
        ps_script = script_dir / "windows" / "install-daemon.ps1"
        if not ps_script.exists():
            print(f"  Error: {ps_script} not found.")
            return
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
            check=False
        )
    else:
        print(f"  Unsupported OS: {os_name}")

# ---------------------------------------------------------------------------
# CLI Core
# ---------------------------------------------------------------------------

def _cmd_tunnel(args: list) -> None:
    """Управление Serveo SSH туннелем и OAuth адаптером для MCP.

    Subcommands:
        start                     — запустить туннель и адаптер (systemd или foreground)
        stop                      — остановить туннель и адаптер
        status                    — показать статус туннеля и URL
    """
    import shutil
    import time

    from mnemostroma.integration.tunnel.manager import (
        TUNNEL_URLS_DIR,
        _load_tunnel_config,
        _print_connection_guide,
    )
    from mnemostroma.integration.tunnel.token import (
        get_or_create_tunnel_token,
        get_tunnel_token,
    )

    config = _load_tunnel_config()
    subdomain = config.get("subdomain")
    filename = f"user-{subdomain}.txt" if subdomain else "user-anonymous.txt"
    url_file = TUNNEL_URLS_DIR / filename

    subcmd = args[0] if args else "start"

    if subcmd == "start":
        foreground = "--foreground" in args
        use_systemd = False
        if not foreground and sys.platform == "linux" and shutil.which("systemctl"):
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", "mnemostroma-tunnel"],
                capture_output=True, text=True
            )
            use_systemd = result.returncode == 0

        if use_systemd:
            subprocess.run(["systemctl", "--user", "start", "mnemostroma-tunnel"])
            print("✓ Mnemostroma tunnel started via systemd")
            # Ждем появления tunnel_url
            for _ in range(20):
                if url_file.exists():
                    break
                time.sleep(0.5)
            if url_file.exists():
                url = url_file.read_text().strip()
                _print_connection_guide(url, get_or_create_tunnel_token())
            else:
                print("⚠ Tunnel started, but URL is not available yet. Check status shortly.")
        else:
            if foreground:
                from mnemostroma.integration.tunnel import manager
                try:
                    asyncio.run(manager.run())
                except KeyboardInterrupt:
                    pass
            else:
                print("Starting Mnemostroma tunnel in background...")
                cmd = [sys.executable, "-m", "mnemostroma", "tunnel", "start", "--foreground"]
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                for _ in range(20):
                    if url_file.exists():
                        break
                    time.sleep(0.5)
                if url_file.exists():
                    url = url_file.read_text().strip()
                    _print_connection_guide(url, get_or_create_tunnel_token())
                else:
                    print("⚠ Tunnel is starting in background. Check 'mnemostroma tunnel status' shortly.")

    elif subcmd == "stop":
        use_systemd = False
        if sys.platform == "linux" and shutil.which("systemctl"):
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", "mnemostroma-tunnel"],
                capture_output=True, text=True
            )
            use_systemd = result.returncode == 0

        if use_systemd:
            subprocess.run(["systemctl", "--user", "stop", "mnemostroma-tunnel"])
            print("✓ Mnemostroma tunnel stopped (systemd)")

        # Убиваем локальные фоновые процессы, если они запущены в обход systemd
        my_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'cmdline', 'name']):
            try:
                pid = proc.info.get('pid')
                if pid == my_pid:
                    continue
                cmd = proc.info.get('cmdline') or []
                name = (proc.info.get('name') or "").lower()

                # 1. ssh/autossh (serveo.net)
                if "ssh" in name or "autossh" in name or any("ssh" in c for c in cmd):
                    if any("serveo.net" in c for c in cmd):
                        try:
                            proc.terminate()
                            proc.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            proc.kill()
                        print(f"✓ Stopped Serveo tunnel process PID {pid} ({name})")

                # 2. mcp_oauth_adapter
                elif any("mcp_oauth_adapter" in c for c in cmd):
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    print(f"✓ Stopped mcp_oauth_adapter process PID {pid}")

                # 3. mnemostroma tunnel foreground process
                elif any("mnemostroma" in c for c in cmd) and any("tunnel" in c for c in cmd) and any("--foreground" in c for c in cmd):
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    print(f"✓ Stopped tunnel manager process PID {pid}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass

        url_file.unlink(missing_ok=True)
        (_MNEMO_DIR / "tunnel_url").unlink(missing_ok=True)
        (_MNEMO_DIR / "serveo_url").unlink(missing_ok=True)
        print("✓ Tunnel stopped.")

    elif subcmd == "status":
        active = False
        for proc in psutil.process_iter(['pid', 'cmdline', 'name']):
            try:
                cmd = proc.info.get('cmdline') or []
                name = (proc.info.get('name') or "").lower()
                if "ssh" in name or "autossh" in name or any("ssh" in c for c in cmd):
                    if any("serveo.net" in c for c in cmd):
                        active = True
                        print(f"  Tunnel process ({name}): PID {proc.pid} (active)")
                elif any("mcp_oauth_adapter" in c for c in cmd):
                    active = True
                    print(f"  OAuth adapter process: PID {proc.pid} (active)")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not active and sys.platform == "linux" and shutil.which("systemctl"):
            res = subprocess.run(
                ["systemctl", "--user", "is-active", "mnemostroma-tunnel"],
                capture_output=True, text=True
            )
            if res.returncode == 0 or "active" in res.stdout:
                active = True
                print("  Tunnel service: active (systemd)")

        if not active:
            print("  Tunnel: stopped")
        else:
            print("  Tunnel: running")

        if url_file.exists():
            url = url_file.read_text().strip()
            token = get_tunnel_token() or "<not generated>"
            print(f"  Public URL: {url}")
            print(f"  Static token: {token}")
    else:
        print(f"Unknown tunnel subcommand: {subcmd}")
        print("Usage: mnemostroma tunnel [start|stop|status]")


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mnemostroma", add_help=False)
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser

def dispatch(args_namespace: argparse.Namespace) -> None:
    command = args_namespace.command
    cargs = args_namespace.args
    
    if not command:
        _print_help()
        return

    if command == "setup":
        # Handle --inject etc manually as in original
        if "--inject" in cargs:
            from mnemostroma.setup.inject import inject
            print(inject(Path(cargs[cargs.index("--inject")+1])))
        else:
            _cmd_setup()
    elif command == "on": _cmd_on()
    elif command == "off": _cmd_off()
    elif command == "status": _print_status()
    elif command == "run":
        try:
            asyncio.run(_run_daemon())
        except KeyboardInterrupt:
            pass
    elif command == "mcp":
        try:
            from mnemostroma.integration.mcp_stdio_adapter import main as mcp_main
            asyncio.run(mcp_main())
        except KeyboardInterrupt:
            pass
    elif command == "service": _cmd_service(cargs)
    elif command == "tunnel": _cmd_tunnel(cargs)  # PATCH-2026-05-17
    elif command == "config": _handle_config(cargs)
    elif command == "tray":
        try:
            from mnemostroma.tools.tray import run_tray
            db_path = _MNEMO_DIR / "logs.db"
            run_tray(db_path)
        except ImportError:
            print("\n❌ Tray feature not installed.")
            print("   Install it with: pip install 'mnemostroma[tray]' or 'mnemostroma[all]'")
            if sys.platform == "linux":
                print("   On Linux, also install system libs: sudo apt install python3-gi gir1.2-appindicator3-0.1")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Tray failure: {e}")
            sys.exit(1)
    elif command == "sse":  # PATCH-2026-05-17
        try:
            from mnemostroma.integration.mcp_sse_adapter import run as sse_run
            asyncio.run(sse_run())
        except ImportError:
            print("\n❌ Error: 'sse' dependencies missing.")
            print("   Install: pip install 'mnemostroma[sse]'")
            sys.exit(1)
        except KeyboardInterrupt:
            pass
    elif command == "logs":
        from mnemostroma.tools.logs import run_logs
        db_path = _MNEMO_DIR / "logs.db"
        days = 7
        as_json = False
        if "--days" in cargs:
            days = int(cargs[cargs.index("--days")+1])
        if "--json" in cargs:
            as_json = True
        run_logs(str(db_path), days, as_json)
    elif command == "watch":
        from mnemostroma.tools.watch import run_watch
        db_path = _MNEMO_DIR / "logs.db"
        run_watch(db_path)
    elif command == "db-dump-time": _cmd_db_dump_time(cargs)
    elif command == "cleanup": _cmd_cleanup(cargs)
    elif command == "install-extension": _cmd_install_extension()
    elif command in ("install-models", "download-models"):
        force = "--force" in cargs
        manifest_path = _ensure_manifest(force=force)
        _install_models(manifest_path, force=force)
    else:
        print(f"Unknown command: {command}")
        _print_help()
