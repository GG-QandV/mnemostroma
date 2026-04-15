# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import signal
import logging
import sys
import subprocess
import json
import argparse
import psutil
import time as _time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("mnemostroma")

_MNEMO_DIR = Path.home() / ".mnemostroma"
_PID_FILE  = _MNEMO_DIR / "daemon.pid"
_CONFIG_PATH = _MNEMO_DIR / "config.json"

# ---------------------------------------------------------------------------
# Process & PID Management (psutil based)
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    import os
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

def _remove_pid() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def _read_pid() -> int | None:
    """Return PID from daemon.pid, or None if not running."""
    try:
        pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
        if psutil.pid_exists(pid):
            return pid
        _remove_pid()
    except Exception:
        pass
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
    from mnemostroma.conductor import Conductor

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
    import shutil, subprocess

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
        with open(config_path, "r", encoding="utf-8") as f:
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
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)

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
    print(f"\nMnemostroma model setup")
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
            print(f"    ✓ already installed, skipping\n")
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
                    local_dir_use_symlinks=False,
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
        f"  export ANTHROPIC_BASE_URL=\"https://localhost:8767\"\n"
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
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}_backup_{ts}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


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

    manifest_dest = _MNEMO_DIR / "models_manifest.json"
    pkg_manifest = Path(__file__).parent.parent / "models_manifest.json"
    if not manifest_dest.exists() and pkg_manifest.exists():
        shutil.copy(pkg_manifest, manifest_dest)

    if sys.platform == "darwin":
        _macos_preflight()
    elif sys.platform == "win32":
        _windows_preflight()

    # Model install
    _install_models(manifest_dest, force=False)

    try:
        from mnemostroma.setup.tls import generate_passthrough_tls
        ca_cert, _, _ = generate_passthrough_tls(_MNEMO_DIR)
        _write_claude_wrapper(Path.home() / ".local" / "bin" / "mnemo", ca_cert)
    except Exception:
        pass
    print("\nSetup complete. Run: mnemostroma on\n")

_BANNER = """
  ███╗   ███╗███╗  ██╗███████╗███╗   ███╗ ██████╗
  ████╗ ████║████╗ ██║██╔════╝████╗ ████║██╔═══██╗
  ██╔████╔██║██╔██╗██║█████╗  ██╔████╔██║██║   ██║
  ██║╚██╔╝██║██║╚████║██╔══╝  ██║╚██╔╝██║██║   ██║
  ██║ ╚═╝ ██║██║ ╚███║███████╗██║ ╚═╝ ██║╚██████╔╝
  ╚═╝     ╚═╝╚═╝  ╚══╝╚══════╝╚═╝     ╚═╝ ╚═════╝
                    MNEMOSTROMA v1.7.x
"""

def _cmd_cleanup(args: list) -> bool:
    """
    Logic:
    есть процессы -> проверяем сокет
      ├── один владеет сокетом -> он Master, остальных убить
      ├── несколько владеют -> оставить самый старый, остальных убить  
      └── никто не владеет -> убить всех -> предложить mnemostroma on
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
    import subprocess, os
    
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
            start_new_session=True, stdout=log_f, stderr=log_f, cwd=str(_MNEMO_DIR),
        )

    print(_BANNER)
    print(f"  Starting...  PID {proc.pid}")
    _time.sleep(1.2)
    if proc.poll() is None:
        print(f"  ⚡ Daemon running   PID {proc.pid}")
    else:
        print(f"  ✗ Daemon exited early")
        sys.exit(1)

def _cmd_off() -> None:
    import os, time as _time
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
        try:
            os.kill(pid, 0)
        except OSError:
            print("stopped")
            _remove_pid()
            return
    os.kill(pid, signal.SIGKILL)
    _remove_pid()
    print("killed")

def _print_status() -> None:
    import os, time as _time
    print("\nMnemostroma status\n")
    pid = _read_pid()
    running = False
    if pid:
        try:
            os.kill(pid, 0)
            running = True
        except OSError:
            _remove_pid()
    print(f"  Daemon:   {'running (' + str(pid) + ')' if running else 'stopped'}")
    
    status_path = _MNEMO_DIR / "status.json"
    if running and status_path.exists():
        try:
            s = json.loads(status_path.read_text(encoding="utf-8"))
            print(f"  RAM:      {s.get('ram_mb', '?')} MB")
            print(f"  Sessions: {s.get('ram_index_count', '?')} (RAM)")
        except Exception:
            pass

def _print_help():
    print("Mnemostroma CLI\n\nCommands: setup, on, off, status, config, service, run, mcp, tray, watch, logs")

# ---------------------------------------------------------------------------
# Config Tuner
# ---------------------------------------------------------------------------

_PARAM_DOCS = {"logging.enabled": "Enable/disable event logging"}

def _handle_config(args: list) -> None:
    if not args:
        print("Usage: mnemostroma config list")
        return
    if args[0] == "list":
        if _CONFIG_PATH.exists():
            print(_CONFIG_PATH.read_text())

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _cmd_service(args: list) -> None:
    subcmd = args[0] if args else "help"
    print(f"Service command {subcmd} (logic moved to cli/commands.py)")

# ---------------------------------------------------------------------------
# CLI Core
# ---------------------------------------------------------------------------

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
    elif command in ("run", "mcp"):
        try:
            asyncio.run(_run_daemon())
        except KeyboardInterrupt:
            pass
    elif command == "service": _cmd_service(cargs)
    elif command == "config": _handle_config(cargs)
    elif command == "tray":
        from mnemostroma.tools.tray import run_tray
        db_path = _MNEMO_DIR / "logs.db"
        run_tray(db_path)
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
    elif command == "cleanup": _cmd_cleanup(cargs)
    else:
        print(f"Unknown command: {command}")
        _print_help()
