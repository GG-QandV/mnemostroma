# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import signal
import logging
import sys
import json
from pathlib import Path

logger = logging.getLogger("mnemostroma")


# ---------------------------------------------------------------------------
# Daemon command
# ---------------------------------------------------------------------------

_MNEMO_DIR = Path.home() / ".mnemostroma"
_PID_FILE  = _MNEMO_DIR / "daemon.pid"


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
        return int(_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


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

    conductor = Conductor()
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform != "win32":
        # Unix: add_signal_handler works on SelectorEventLoop (Linux/macOS)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: stop_event.set())
    else:
        # Windows: ProactorEventLoop does not support add_signal_handler.
        # SIGINT (Ctrl+C) is raised as KeyboardInterrupt and caught below.
        # Process termination via _cmd_off uses taskkill → no graceful hook needed.
        signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    try:
        logger.info("Initializing Mnemostroma Daemon...")
        await conductor.start(
            config_path=config_path,
            db_path=db_path,
            model_dir=model_dir,
        )

        _write_pid()

        # SIGUSR1 → flush write queue immediately (Unix only)
        if sys.platform != "win32" and hasattr(signal, "SIGUSR1"):
            def _on_flush():
                ctx = conductor.ctx
                if ctx and ctx.persistence:
                    asyncio.ensure_future(ctx.persistence.flush())
                    logger.info("SIGUSR1: flush triggered")
            loop.add_signal_handler(signal.SIGUSR1, _on_flush)

        # SIGUSR2 → dump Hot/Warm layer to ~/.mnemostroma/dumps/ (Unix only)
        if sys.platform != "win32" and hasattr(signal, "SIGUSR2"):
            def _on_dump():
                ctx = conductor.ctx
                if ctx:
                    from mnemostroma.tools.admin import ctx_dump
                    asyncio.ensure_future(ctx_dump(ctx))
                    logger.info("SIGUSR2: dump triggered")
            loop.add_signal_handler(signal.SIGUSR2, _on_dump)

        from mnemostroma.ipc_server import IPCServer
        ipc = IPCServer(conductor)
        ipc_task = asyncio.create_task(ipc.serve())

        logger.info("Daemon is running. Press Ctrl+C to stop.")
        await stop_event.wait()
        ipc_task.cancel()
    except Exception as e:
        logger.error(f"Daemon failed: {e}", exc_info=True)
    finally:
        _remove_pid()
        logger.info("Shutting down daemon...")
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
            # Bundles in manifest have 'local_dir' relative to 'models/' but we check relative to 'models_dir'
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
        print("       IMPORTANT: Check Add Python to PATH during installation.")
        sys.exit(1)

    if not shutil.which("mnemostroma"):
        print("WARNING: mnemostroma not found in PATH.")
        print(r"         If using venv: venv\Scripts\activate  (cmd)")
        print(r"                    or: venv\Scripts\Activate.ps1  (PowerShell)")

    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        try:
            result = subprocess.run(
                [ps, "-NoProfile", "-Command", "Get-ExecutionPolicy"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip().lower() == "restricted":
                print("WARNING: PowerShell ExecutionPolicy is Restricted — venv .ps1 scripts blocked.")
                print("         Fix: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser")
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


# ---------------------------------------------------------------------------
# install-models command
# ---------------------------------------------------------------------------

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
        print(
            "NOTE: No HuggingFace token detected. Public models will still download.\n"
            "      If you hit access errors, run: huggingface-cli login\n"
        )

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
            print(f"    ✓ already installed, skipping  (use --force to re-download)\n")
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
                # AVX2 fallback: if primary file fails and fallback exists, try it
                if fallback_files and filename == files[0] and ("404" in err_msg or "not found" in err_msg.lower()):
                    fallback_name = fallback_files[0]
                    print(f"FAILED — trying non-AVX2 fallback...", end=" ", flush=True)
                    try:
                        fb_parts = Path(fallback_name)
                        hf_hub_download(
                            repo_id=hf_repo,
                            subfolder=str(fb_parts.parent) if str(fb_parts.parent) != "." else None,
                            filename=fb_parts.name,
                            local_dir=str(local_dir),
                            local_dir_use_symlinks=False,
                        )
                        # Rename fallback to expected name so ModelRegistry finds it
                        (local_dir / fallback_name).rename(local_dir / filename)
                        print("done (non-AVX2)")
                        continue
                    except Exception:
                        pass
                print("FAILED")
                if "401" in err_msg or "403" in err_msg or "gated" in err_msg.lower():
                    print(f"    ! Access denied for {hf_repo}")
                    print(f"      This model may require license acceptance.")
                    print(f"      Visit: https://huggingface.co/{hf_repo}")
                    print(f"      Then run: huggingface-cli login")
                elif "404" in err_msg or "not found" in err_msg.lower():
                    print(f"    ! File not found: {hf_repo}/{filename}")
                    print(f"      Check repo structure at:")
                    print(f"      https://huggingface.co/{hf_repo}/tree/main")
                else:
                    print(f"    ! {err_msg}")
                bundle_ok = False
                errors.append((name, filename, err_msg))

        if bundle_ok:
            print(f"    ✓ {name} ready\n")
        else:
            print(f"    ✗ {name} incomplete — see errors above\n")

    print("-" * 50)
    if not errors:
        print("✓ All models installed successfully.")
        print("\nTo start the daemon:")
        print("  mnemostroma run")
    else:
        print(f"✗ {len(errors)} file(s) failed to download:")
        for name, filename, _ in errors:
            print(f"  - {name}: {filename}")
        print("\nRe-run after resolving access issues:")
        print("  mnemostroma install-models")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Wrapper script helper
# ---------------------------------------------------------------------------

def _write_claude_wrapper(wrapper_path: Path, ca_cert: Path) -> None:
    """Write ~/.local/bin/mnemo — safe launcher with proxy liveness check.

    Checks port 8767 before setting ANTHROPIC_BASE_URL. If the proxy is not
    listening, falls through to plain 'claude' with no env changes — so Claude
    Code works normally instead of failing with connection refused.
    """
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        "#!/bin/bash\n"
        "# mnemo — Mnemostroma proxy launcher\n"
        "# Generated by: mnemostroma setup\n"
        "#\n"
        "# Routes claude traffic through the Mnemostroma passthrough proxy\n"
        "# so conversations are captured in memory automatically.\n"
        "# If the proxy is not running, falls back to direct API (no capture).\n"
        "# Start proxy with: mnemostroma sse\n"
        "\n"
        "CLAUDE_BIN=$(command -v claude 2>/dev/null)\n"
        "if [ -z \"$CLAUDE_BIN\" ]; then\n"
        "  echo 'mnemo: error: claude not found in PATH' >&2\n"
        "  exit 1\n"
        "fi\n"
        "\n"
        "# Check if proxy port is open (TCP connect, no data sent)\n"
        "if (echo > /dev/tcp/127.0.0.1/8767) 2>/dev/null; then\n"
        f"  export ANTHROPIC_BASE_URL=\"https://localhost:8767\"\n"
        f"  export NODE_EXTRA_CA_CERTS=\"{ca_cert}\"\n"
        "else\n"
        "  echo 'mnemo: proxy not running — starting claude directly (no memory capture)' >&2\n"
        "  echo '  run: mnemostroma sse   to enable capture' >&2\n"
        "fi\n"
        "\n"
        "exec \"$CLAUDE_BIN\" \"$@\"\n",
        encoding="utf-8",
    )
    wrapper_path.chmod(0o755)


# ---------------------------------------------------------------------------
# setup / on / off / status commands
# ---------------------------------------------------------------------------

def _cmd_setup() -> None:
    import shutil

    config_dest = _MNEMO_DIR / "config.json"
    pkg_default = Path(__file__).parent / "config_default.json"

    print("\nMnemostroma setup\n")

    # 1. Create ~/.mnemostroma/
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Directory: {_MNEMO_DIR}")

    # 2. Copy config_default.json → ~/.mnemostroma/config.json
    if not config_dest.exists():
        if pkg_default.exists():
            shutil.copy(pkg_default, config_dest)
            print(f"  ✓ Config:    {config_dest}")
        else:
            print(f"\nERROR: package data missing (config_default.json not found).")
            print(f"       Reinstall: pip install --force-reinstall mnemostroma")
            sys.exit(1)
    else:
        print(f"  ~ Config:    {config_dest}  (already exists, not overwritten)")

    # 3. Copy models_manifest.json → ~/.mnemostroma/models_manifest.json
    manifest_dest = _MNEMO_DIR / "models_manifest.json"
    pkg_manifest = Path(__file__).parent / "models_manifest.json"
    if not manifest_dest.exists():
        if pkg_manifest.exists():
            shutil.copy(pkg_manifest, manifest_dest)
            print(f"  ✓ Manifest:  {manifest_dest}")
        else:
            # fall back to CWD manifest
            cwd_manifest = Path("models_manifest.json")
            if cwd_manifest.exists():
                shutil.copy(cwd_manifest, manifest_dest)
                print(f"  ✓ Manifest:  {manifest_dest}  (from CWD)")
    else:
        print(f"  ~ Manifest:  {manifest_dest}  (already exists)")

    # 4. Copy models_manifest.json to package dir if missing (for dev/build sync)
    if pkg_manifest.parent.exists() and not pkg_manifest.exists():
        if manifest_dest.exists():
            shutil.copy(manifest_dest, pkg_manifest)

    # 5. OS-specific pre-flights (before model download — warn early)
    if sys.platform == "darwin":
        _macos_preflight()
    elif sys.platform == "win32":
        _windows_preflight()

    # 6. Check/Install models
    manifest_dest = _MNEMO_DIR / "models_manifest.json"
    models_dir = _MNEMO_DIR / "models"
    ok, missing = _models_complete(manifest_dest, models_dir)
    if not ok:
        if missing and missing != ["models_manifest.json missing"]:
            print(f"  ↓ Models incomplete ({len(missing)} file(s) missing) — downloading...")
        else:
            print(f"  ↓ Installing models to {models_dir}...")
        _install_models(manifest_dest, force=False)
    else:
        print(f"  ✓ Models:    {models_dir}")

    # 7. DB note (created by daemon on first start)
    db_dest = _MNEMO_DIR / "mnemostroma.db"
    if db_dest.exists():
        print(f"  ✓ Database:  {db_dest}")
    else:
        print(f"  ~ Database:  {db_dest}  (created on first run)")

    # 8. TLS cert for proxy_passthrough (requires mnemostroma[sse])
    try:
        from mnemostroma.setup.tls import generate_passthrough_tls
        ca_cert, _, _ = generate_passthrough_tls(_MNEMO_DIR)
        print(f"  ✓ TLS cert:  {_MNEMO_DIR / 'certs'}  (passthrough-ca/cert/key.pem)")
        _wrapper = Path.home() / ".local" / "bin" / "mnemo"
        print(f"  ✓ Wrapper:   {_wrapper}  (run 'mnemo' instead of 'claude')")
        _write_claude_wrapper(_wrapper, ca_cert)
    except ImportError:
        print(f"  ~ TLS cert:  skipped  (pip install mnemostroma[sse] to enable passthrough proxy)")

    # 9. Print Claude Desktop Config block
    print("\n" + "="*60)
    print("CLAUDE DESKTOP CONFIGURATION (MCP)")
    print("="*60)
    print("Add this to your claude_desktop_config.json to use Mnemostroma:")
    
    # Block 7.1: Safe path detection
    import shutil
    exe_path = shutil.which("mnemostroma") or sys.argv[0]
    
    if not Path(exe_path).is_absolute():
        # Try to find absolute path
        found = shutil.which(exe_path)
        if found:
            exe_path = found
    
    # If in venv, warn the user
    is_venv = sys.prefix != sys.base_prefix
    
    print("\n{")
    print('  "mcpServers": {')
    print('    "mnemostroma": {')
    print(f'      "command": "{exe_path}",')
    print('      "args": ["mcp"]')
    print("    }")
    print("  }")
    print("}")
    
    if is_venv:
        # Check if it's in system PATH (outside of this venv)
        # We can't easily check 'outside' venv but we can check if it's 'found' generally
        # but shutil.which will return the venv one first.
        # Simple heuristic: if the path contains the venv prefix, it's not global.
        if str(sys.prefix) in str(exe_path):
            print("\nWARNING: mnemostroma is not in system PATH.")
            print("         Use the full path in Claude Desktop config, or install globally.")
        else:
            print("\nNOTE: You are running in a virtual environment.")
            print("      If you move or delete this venv, the MCP path will break.")
    
    if sys.platform == "darwin":
        print("\nNOTE: If 'pip install' failed with 'externally managed environment':")
        print("      pipx install mnemostroma  OR  python3 -m venv ~/.mnemo-env && ...")

    print("="*60)

    print(f"\nSetup complete. Run: mnemostroma on\n")


_BANNER = """\

  ███╗   ███╗███╗  ██╗███████╗███╗   ███╗ ██████╗
  ████╗ ████║████╗ ██║██╔════╝████╗ ████║██╔═══██╗
  ██╔████╔██║██╔██╗██║█████╗  ██╔████╔██║██║   ██║
  ██║╚██╔╝██║██║╚████║██╔══╝  ██║╚██╔╝██║██║   ██║
  ██║ ╚═╝ ██║██║ ╚███║███████╗██║ ╚═╝ ██║╚██████╔╝
  ╚═╝     ╚═╝╚═╝  ╚══╝╚══════╝╚═╝     ╚═╝ ╚═════╝
                    MNEMOSTROMA v1.7.x
"""


def _cmd_on() -> None:
    import subprocess, os, time as _time

    # Check already running
    pid = _read_pid()
    if pid is not None:
        try:
            os.kill(pid, 0)
            print(f"Daemon already running (PID {pid})")
            print(f"  Use 'mnemostroma off' to stop, 'mnemostroma status' to check.")
            return
        except (ProcessLookupError, OSError):
            _remove_pid()

    # Robust environment check
    config_path = _MNEMO_DIR / "config.json"
    manifest_path = _MNEMO_DIR / "models_manifest.json"
    models_dir = _MNEMO_DIR / "models"
    
    _check_environment_ready(config_path, manifest_path, models_dir)

    log_path = _MNEMO_DIR / "daemon.log"
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w") as log_f:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "mnemostroma", "run",
                "--config", str(_MNEMO_DIR / "config.json"),
                "--db",     str(_MNEMO_DIR / "mnemostroma.db"),
                "--model-dir", str(_MNEMO_DIR / "models"),
            ],
            start_new_session=True,
            stdout=log_f,
            stderr=log_f,
            cwd=str(_MNEMO_DIR),
        )

    print(_BANNER)
    print(f"  Starting...  PID {proc.pid}")
    _time.sleep(1.0)

    # Verify still alive
    if proc.poll() is None:
        print(f"  ⚡ Daemon running   PID {proc.pid}")
    else:
        print(f"  ✗ Daemon exited early — check: {log_path}")
        sys.exit(1)

    print(f"  Logs:              {log_path}")
    print(f"  Stop:              mnemostroma off")
    print(f"  Status:            mnemostroma status")
    print()


def _cmd_off() -> None:
    import os, time as _time

    pid = _read_pid()
    if pid is None:
        print("Daemon not running (no daemon.pid found)")
        return

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        print(f"Daemon not running (stale PID {pid} — cleaned up)")
        _remove_pid()
        return

    print(f"Stopping daemon (PID {pid})...", end=" ", flush=True)
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        print("already stopped")
        _remove_pid()
        return

    # Wait up to 5s for graceful shutdown
    for _ in range(10):
        _time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, OSError):
            print("stopped")
            _remove_pid()
            return

    # Force kill
    print("forcing...", end=" ", flush=True)
    try:
        if sys.platform == "win32":
            import subprocess
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
        _time.sleep(0.3)
    except (ProcessLookupError, OSError):
        pass
    print("killed")
    _remove_pid()


def _print_status() -> None:
    import os, time as _time

    print("\nMnemostroma status\n")

    # --- Daemon state ---
    pid = _read_pid()
    running = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            running = True
        except (ProcessLookupError, OSError):
            _remove_pid()

    if running:
        print(f"  Daemon:   running  (PID {pid})")
    else:
        print(f"  Daemon:   stopped")

    # --- status.json metrics ---
    status_path = _MNEMO_DIR / "status.json"
    pulse_path  = _MNEMO_DIR / "pulse.json"

    if running and status_path.exists():
        try:
            s = json.loads(status_path.read_text(encoding="utf-8"))
            age = int(_time.time()) - s.get("ts", 0)
            print(f"  RAM:      {s.get('ram_mb', '?')} MB")
            print(f"  Sessions: {s.get('ram_index_count', '?')} (RAM)  "
                  f"{s.get('session_index_count', '?')} (index)")
            print(f"  Writes:   {s.get('pending_writes', '?')} pending")
            metrics = s.get("metrics", {})
            if metrics:
                dropped = metrics.get("dropped_sessions", 0)
                if dropped:
                    print(f"  Dropped:  {dropped} sessions (queue overflow)")
            print(f"  Updated:  {age}s ago")
        except Exception:
            pass

    if running and pulse_path.exists():
        try:
            p = json.loads(pulse_path.read_text(encoding="utf-8"))
            age = int(_time.time()) - p.get("ts", 0)
            urgency = p.get("urgency_active", 0)
            if urgency:
                print(f"  Urgency:  {urgency} active")
            print(f"  Pulse:    {age}s ago")
        except Exception:
            pass

    # --- Config ---
    config_path = _MNEMO_DIR / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            cal = cfg.get("calibration", {})
            if cal.get("calibration_complete"):
                print(f"  Calibration: complete")
            elif cal.get("enabled"):
                print(f"  Calibration: in progress")
            log_cfg = cfg.get("logging", {})
            print(f"  Logging:  enabled={log_cfg.get('enabled', True)}, "
                  f"mode={log_cfg.get('mode', 'safe')!r}")
        except Exception:
            pass

    # --- Models ---
    manifest_path = _MNEMO_DIR / "models_manifest.json"
    if not manifest_path.exists():
        manifest_path = Path("models_manifest.json")
    if manifest_path.exists():
        try:
            manifest = _load_manifest(manifest_path)
            bundles = manifest.get("download_bundles", {})
            base_dir = _MNEMO_DIR / "models"
            print(f"\n  Models:")
            for name, bundle in bundles.items():
                rel = bundle["local_dir"].replace("models/", "", 1)
                local_dir = base_dir / rel
                key_file = local_dir / bundle["files"][0]
                mark = "✓" if key_file.exists() else "✗"
                print(f"    {mark} {name}  ({bundle.get('size_mb', '?')} MB)")
        except Exception:
            pass

    print()


# ---------------------------------------------------------------------------
# config tuner
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path("config.json")

# Human-readable descriptions for every tunable parameter (section.key)
_PARAM_DOCS: dict = {
    "resources.session_window_size":       "Max sessions kept in RAM hot layer",
    "resources.content_max_blocks":        "Max content blocks in RAM",
    "resources.ram_soft_limit_mb":         "RAM soft eviction trigger (MB)",
    "resources.ram_hard_limit_mb":         "RAM hard eviction limit (MB)",
    "resources.ram_eviction_threshold":    "Eviction fraction when hard limit hit (0-1)",
    "resources.window_min":                "Minimum sessions to keep in RAM regardless of score",
    "resources.sqlite_cache_mb":           "SQLite page cache size (MB)",
    "resources.sqlite_mmap_mb":            "SQLite mmap size (MB)",
    "resources.db_growth_budget_mb_per_day": "Max allowed DB growth per day (MB)",
    "resources.onnx_inter_threads":        "ONNX inter-op parallelism threads",
    "resources.onnx_intra_threads":        "ONNX intra-op parallelism threads",
    "score.weight_relevance":              "Score weight: semantic relevance (write profile)",
    "score.weight_temporal":               "Score weight: temporal recency (write profile)",
    "score.weight_importance":             "Score weight: importance level (write profile)",
    "score.temporal_decay_lambda":         "Temporal decay rate λ (higher = faster decay)",
    "score.weight_relevance_search":       "Score weight: relevance (search profile)",
    "score.weight_temporal_search":        "Score weight: temporal (search profile)",
    "score.weight_importance_search":      "Score weight: importance (search profile)",
    "importance.weight_critical":          "Importance score multiplier for 'critical'",
    "importance.weight_important":         "Importance score multiplier for 'important'",
    "importance.weight_background":        "Importance score multiplier for 'background'",
    "importance.weight_principle":         "Importance score multiplier for 'principle'",
    "importance.ner_score_threshold":      "Minimum NER confidence to accept entity",
    "importance.tag_verification_threshold": "Min score to keep a tag after verification",
    "search.top_k_candidates":             "Candidates fetched per search before reranking",
    "search.top_n_results":                "Final results returned after reranking",
    "search.embedding_dim":                "Embedding dimension (must match loaded model)",
    "search.matrix_dtype":                 "Matrix storage dtype (float32 recommended)",
    "search.pipeline_width":               "Parallel search pipelines: 2=default, 4=power user",
    "observer.min_text_length":            "Minimum text length to process (chars)",
    "observer.ner_call_rate_target":       "Fraction of sessions that trigger NER (0-1)",
    "observer.brief_max_chars":            "Max characters in session brief",
    "observer.active_variables_max":       "Max active variables tracked per session",
    "observer.tags_max_per_session":       "Max tags stored per session",
    "observer.tags_min_for_search":        "Min tags needed to trigger tag-based search",
    "observer.session_type_classify_after_n": "Classify session type after N chars",
    "observer.gliner_mode":                "GLiNER mode: 'fast' | 'precise' | 'auto'",
    "dissolver.lambda_critical":           "Decay λ for 'critical' sessions",
    "dissolver.lambda_important":          "Decay λ for 'important' sessions",
    "dissolver.lambda_background":         "Decay λ for 'background' sessions",
    "dissolver.lambda_principle":          "Decay λ for 'principle' sessions",
    "dissolver.use_factor_coefficient":    "Use-count boost coefficient for decay resistance",
    "dissolver.consolidation_interval_sec": "ConsolidationWorker run interval (seconds)",
    "dissolver.content_max_blocks":        "Max content blocks before eviction",
    "dissolver.content_evict_batch":       "How many content blocks to evict per cycle",
    "dissolver.content_hot_protect_hours": "Hours to protect recently-used content from eviction",
    "tuner.conflict_signal_threshold":     "Cosine distance threshold for conflict detection",
    "tuner.semantic_drift_threshold":      "Drift threshold to trigger recalibration",
    "tuner.anchor_ttl_days_default":       "Default anchor TTL (days)",
    "tuner.anchor_ttl_days_decision":      "Anchor TTL for decision-type sessions (days)",
    "tuner.anchor_ttl_days_principle":     "Anchor TTL for principle sessions (days)",
    "tuner.check_interval_sec":            "Tuner background check interval (seconds)",
    "tuner.conflict_hold_max_days":        "Max days to hold a conflict before auto-resolving",
    "urgency.check_interval_sec":          "Urgency checker run interval (seconds)",
    "urgency.default_hours_ahead":         "Default deadline horizon when none specified (hours)",
    "urgency.bare_entity_compress_delay_sec": "Delay before compressing bare-entity sessions",
    "storage.sqlite_synchronous":          "SQLite PRAGMA synchronous (NORMAL|FULL|OFF)",
    "storage.async_flush_interval_sec":    "Max seconds between async SQLite flushes",
    "storage.batch_flush_size":            "Sessions per SQLite write batch",
    "experience.layer_enabled":            "Enable/disable Experience Layer",
    "experience.intuition_fire_threshold": "Min avg_score to emit DO_THIS signal",
    "experience.maturity_apprentice":      "Sessions needed to reach Apprentice maturity",
    "experience.maturity_practitioner":    "Sessions needed to reach Practitioner maturity",
    "experience.maturity_expert":          "Sessions needed to reach Expert maturity",
    "experience.maturity_master":          "Sessions needed to reach Master maturity",
    "experience.exp_decay_days_threshold": "Days of inactivity before decay starts",
    "experience.exp_decay_rate":           "Daily decay rate applied to score_sum",
    "calibration.enabled":                 "Enable onboarding calibration collector",
    "calibration.max_sessions":            "Max sessions to collect for calibration",
    "calibration.min_onboarding_sessions": "Min sessions before finalizing threshold",
    "calibration.continuation_threshold":  "Cosine similarity threshold for continuation detection",
    "calibration.calibration_complete":    "Flag: calibration already done (set by system)",
    "logging.enabled":                     "Enable/disable event logging to logs.db",
    "logging.mode":                        "Logging verbosity: 'safe' | 'debug'",
    "logging.db_path":                     "Path to logs SQLite database",
}


def _load_config_raw(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config_raw(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _resolve_key(data: dict, dotkey: str):
    """Return (section_dict, field_name, current_value) for a dot-notation key."""
    parts = dotkey.split(".", 1)
    if len(parts) != 2:
        return None, None, None
    section, field = parts
    section_data = data.get(section)
    if not isinstance(section_data, dict):
        return None, None, None
    if field not in section_data:
        return None, None, None
    return section_data, field, section_data[field]


def _coerce_value(raw: str, current):
    """Cast raw string to the same type as current value."""
    if isinstance(current, bool):
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Expected bool (true/false), got {raw!r}")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    # str / None
    return raw


def _config_get(key: str, config_path: Path = _CONFIG_PATH) -> None:
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)
    data = _load_config_raw(config_path)
    _, field, value = _resolve_key(data, key)
    if field is None:
        print(f"ERROR: key {key!r} not found in config")
        sys.exit(1)
    doc = _PARAM_DOCS.get(key, "")
    print(f"{key} = {json.dumps(value)}")
    if doc:
        print(f"  # {doc}")


def _config_set(key: str, raw_value: str, config_path: Path = _CONFIG_PATH) -> None:
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)
    data = _load_config_raw(config_path)
    section_data, field, current = _resolve_key(data, key)
    if field is None:
        print(f"ERROR: key {key!r} not found in config")
        sys.exit(1)
    try:
        new_value = _coerce_value(raw_value, current)
    except (ValueError, TypeError) as e:
        print(f"ERROR: invalid value for {key}: {e}")
        sys.exit(1)
    section_data[field] = new_value
    _save_config_raw(config_path, data)
    print(f"{key}: {json.dumps(current)} -> {json.dumps(new_value)}")


def _config_list(section_filter: str | None = None, config_path: Path = _CONFIG_PATH) -> None:
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)
    data = _load_config_raw(config_path)

    sections = [section_filter] if section_filter else list(data.keys())
    found_any = False

    for section in sections:
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            continue
        found_any = True
        print(f"\n[{section}]")
        for field, value in section_data.items():
            dotkey = f"{section}.{field}"
            doc = _PARAM_DOCS.get(dotkey, "")
            val_str = json.dumps(value)
            if doc:
                print(f"  {field:<42} = {val_str:<12}  # {doc}")
            else:
                print(f"  {field:<42} = {val_str}")

    if not found_any:
        print(f"ERROR: section {section_filter!r} not found")
        sys.exit(1)
    print()


def _config_help() -> None:
    print(
        "Usage:\n"
        "  mnemostroma config list [section]   List parameters (optionally filter by section)\n"
        "  mnemostroma config get  <key>        Print current value of key\n"
        "  mnemostroma config set  <key> <val>  Set a parameter value\n"
        "\n"
        "Keys use dot notation: section.field\n"
        "Examples:\n"
        "  mnemostroma config list\n"
        "  mnemostroma config list search\n"
        "  mnemostroma config get  search.embedding_dim\n"
        "  mnemostroma config set  resources.onnx_inter_threads 4\n"
        "  mnemostroma config set  logging.enabled false\n"
        "  mnemostroma config set  experience.exp_decay_days_threshold 60\n"
    )


def _handle_config(args: list) -> None:
    subcmd = args[0] if args else "list"

    if subcmd in ("-h", "--help"):
        _config_help()
        return

    config_path = _CONFIG_PATH
    # Allow --config <path> override anywhere in args
    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 < len(args):
            config_path = Path(args[idx + 1])
            args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if subcmd == "list":
        section = args[1] if len(args) > 1 else None
        _config_list(section, config_path)

    elif subcmd == "get":
        if len(args) < 2:
            print("ERROR: mnemostroma config get <key>")
            sys.exit(1)
        _config_get(args[1], config_path)

    elif subcmd == "set":
        if len(args) < 3:
            print("ERROR: mnemostroma config set <key> <value>")
            sys.exit(1)
        _config_set(args[1], args[2], config_path)

    else:
        print(f"Unknown config subcommand: {subcmd!r}\n")
        _config_help()
        sys.exit(1)


# ---------------------------------------------------------------------------
# system service (systemd / launchd)
# ---------------------------------------------------------------------------

def _cmd_service(args: list) -> None:
    """Entry point for 'mnemostroma service' command."""
    subcmd = args[0] if args else "help"
    
    if subcmd == "install":
        _install_service()
    elif subcmd == "uninstall":
        _uninstall_service()
    elif subcmd == "status":
        import platform
        if platform.system() == "Linux":
            print("Systemd status (user mode):")
            os.system("systemctl --user status mnemostroma")
        elif platform.system() == "Darwin":
            print("Launchd status:")
            os.system("launchctl list com.mnemostroma.daemon")
        elif platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["schtasks", "/query", "/tn", "Mnemostroma", "/fo", "LIST"],
                capture_output=True, text=True
            )
            print(result.stdout if result.returncode == 0 else "Task not found.")
        else:
            print(f"Status check not supported for {platform.system()}.")
    else:
        print("Usage: mnemostroma service [install|uninstall|status]")


def _install_service() -> None:
    import platform
    import shutil
    import os
    
    system = platform.system()
    # Find the executable
    exe = "mnemostroma"
    if not shutil.which(exe):
        exe = str(Path(sys.executable).parent / "mnemostroma")
        if not Path(exe).exists():
            exe = f"{sys.executable} -m mnemostroma"

    if system == "Linux":
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path = unit_dir / "mnemostroma.service"
        
        exec_start = exe if " " not in exe else f'"{sys.executable}" -m mnemostroma'
        
        content = f"""[Unit]
Description=Mnemostroma Memory Daemon (MCP)
After=network.target

[Service]
ExecStart={exec_start} mcp
Restart=always
RestartSec=10
StandardOutput=append:{_MNEMO_DIR / "daemon.log"}
StandardError=append:{_MNEMO_DIR / "daemon.log"}

[Install]
WantedBy=default.target
"""
        unit_path.write_text(content, encoding="utf-8")
        print(f"Created {unit_path}")
        
        # Block 6.2: XDG_RUNTIME_DIR check
        if not os.environ.get("XDG_RUNTIME_DIR"):
            print("\nWARNING: XDG_RUNTIME_DIR not set — systemd user mode may fail.")
            print("         On headless servers use: mnemostroma on (manual start)")
            
        os.system("systemctl --user daemon-reload")
        os.system("systemctl --user enable mnemostroma")
        # Block 6.1: enable-linger
        ret = os.system("loginctl enable-linger $(whoami)")
        if ret != 0:
            print("NOTE: enable-linger failed — service will stop at logout.")
            print("      Fix: sudo loginctl enable-linger $USER")
            
        os.system("systemctl --user start mnemostroma")
        print("Service installed and started.")
        
    elif system == "Darwin":
        agent_dir = Path.home() / "Library" / "LaunchAgents"
        agent_dir.mkdir(parents=True, exist_ok=True)
        plist_path = agent_dir / "com.mnemostroma.daemon.plist"
        
        # ProgramArguments array
        if " " in exe:
            args_xml = f"        <string>{sys.executable}</string>\n        <string>-m</string>\n        <string>mnemostroma</string>"
        else:
            args_xml = f"        <string>{exe}</string>"
        args_xml += "\n        <string>mcp</string>"

        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mnemostroma.daemon</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_MNEMO_DIR / "daemon.log"}</string>
    <key>StandardErrorPath</key>
    <string>{_MNEMO_DIR / "daemon.log"}</string>
</dict>
</plist>
"""
        plist_path.write_text(content, encoding="utf-8")
        print(f"Created {plist_path}")
        # macOS 12+ (Monterey+): launchctl load is deprecated → use bootstrap
        uid = os.getuid()
        ret = os.system(f"launchctl bootstrap gui/{uid} {plist_path}")
        if ret != 0:
            # fallback for older macOS
            os.system(f"launchctl load {plist_path}")
        print("Service installed and started.")

    elif system == "Windows":
        _install_service_windows(exe)
    else:
        print(f"Unsupported OS: {system}")


def _install_service_windows(exe: str) -> None:
    """Install Mnemostroma as a Windows Task Scheduler task (auto-start on logon)."""
    import subprocess
    task_name = "Mnemostroma"
    # Build the command: python -m mnemostroma mcp
    cmd = f'"{sys.executable}" -m mnemostroma mcp'
    result = subprocess.run(
        [
            "schtasks", "/create",
            "/tn", task_name,
            "/tr", cmd,
            "/sc", "onlogon",
            "/rl", "limited",
            "/f",
        ],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Task '{task_name}' created (runs at logon).")
        # Start immediately
        subprocess.run(["schtasks", "/run", "/tn", task_name], capture_output=True)
        print("Service started.")
    else:
        print(f"Failed to create task: {result.stderr.strip()}")
        print("You may need to run as Administrator, or start manually:")
        print(f"  mnemostroma on")


def _uninstall_service() -> None:
    import platform, os
    system = platform.system()
    if system == "Linux":
        unit_path = Path.home() / ".config" / "systemd" / "user" / "mnemostroma.service"
        if unit_path.exists():
            os.system("systemctl --user stop mnemostroma")
            os.system("systemctl --user disable mnemostroma")
            unit_path.unlink()
            os.system("systemctl --user daemon-reload")
            print("Service uninstalled.")
    elif system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.mnemostroma.daemon.plist"
        if plist_path.exists():
            uid = os.getuid()
            ret = os.system(f"launchctl bootout gui/{uid} {plist_path}")
            if ret != 0:
                os.system(f"launchctl unload {plist_path}")
            plist_path.unlink()
            print("Service uninstalled.")
    elif system == "Windows":
        import subprocess
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", "Mnemostroma", "/f"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("Service uninstalled.")
        else:
            print(f"Failed: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cmd_dump() -> None:
    """Send SIGUSR2 to the running daemon → triggers ctx_dump in the daemon process."""
    pid = _read_pid()
    if pid is None:
        print("ERROR: daemon not running (no daemon.pid found)")
        sys.exit(1)
    try:
        import os
        os.kill(pid, signal.SIGUSR2)
        dump_dir = _MNEMO_DIR / "dumps"
        print(f"Dump triggered (PID {pid}). Output will appear in {dump_dir}/")
    except ProcessLookupError:
        print(f"ERROR: no process with PID {pid} — daemon may have crashed")
        _remove_pid()
        sys.exit(1)
    except AttributeError:
        print("ERROR: SIGUSR2 not available on this platform")
        sys.exit(1)


async def _cmd_growth_async(db_path: str) -> None:
    """Standalone growth report — opens SQLite directly, no daemon needed."""
    import aiosqlite, os, time as _time
    db_path_obj = Path(db_path)
    if not db_path_obj.exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    now = int(_time.time())
    async with aiosqlite.connect(str(db_path_obj)) as db:
        counts = {}
        for label, cutoff in [
            ("total",  0),
            ("today",  now - 86400),
            ("week",   now - 7 * 86400),
            ("month",  now - 30 * 86400),
        ]:
            if label == "total":
                async with db.execute("SELECT COUNT(*) FROM sessions") as cur:
                    row = await cur.fetchone()
            else:
                async with db.execute(
                    "SELECT COUNT(*) FROM sessions WHERE created_at >= ?", (cutoff,)
                ) as cur:
                    row = await cur.fetchone()
            counts[label] = row[0] if row else 0

        size_mb = round(db_path_obj.stat().st_size / (1024 * 1024), 2)
        # --- TASK 1: добавляем logs.db ---
        logs_path_obj = Path.home() / ".mnemostroma" / "logs.db"
        logs_size_mb = round(logs_path_obj.stat().st_size / (1024 * 1024), 2) if logs_path_obj.exists() else 0.0
        total_size_mb = round(size_mb + logs_size_mb, 2)
        # ---------------------------------
        avg_mb = size_mb / counts["total"] if counts["total"] > 0 else 0.0
        daily_mb = round(counts["today"] * avg_mb, 4)
        days_to_1gb  = int((1024  - total_size_mb) / daily_mb) if daily_mb > 0 else None
        days_to_10gb = int((10240 - total_size_mb) / daily_mb) if daily_mb > 0 else None

    print(f"Sessions — total: {counts['total']}  today: {counts['today']}"
          f"  week: {counts['week']}  month: {counts['month']}")
    # --- TASK 1: три строки хранилища вместо одной ---
    print(f"Storage:")
    print(f"  mnemostroma.db  {size_mb} MB")
    print(f"  logs.db         {logs_size_mb} MB")
    print(f"  ─────────────────────────")
    print(f"  total           {total_size_mb} MB")
    # -------------------------------------------------
    print(f"Growth:   {daily_mb} MB/day" if daily_mb > 0 else "Growth:   insufficient data")
    if days_to_1gb is not None:
        print(f"Forecast: {days_to_1gb} days to 1 GB  |  {days_to_10gb} days to 10 GB")
    # --- TASK 4: baseline validation ---
    if daily_mb > 0 and counts["today"] > 0:
        SPEC_BASELINE_KB_PER_SESSION = 3.0  # 9 MB/month / 3000 sessions = 3 KB/session
        actual_kb = (daily_mb * 1024) / counts["today"]
        deviation_pct = (actual_kb - SPEC_BASELINE_KB_PER_SESSION) / SPEC_BASELINE_KB_PER_SESSION * 100
        if abs(deviation_pct) > 50:
            status = "⚠️  ANOMALY"
        elif abs(deviation_pct) > 20:
            status = "△  ELEVATED"
        else:
            status = "✓  NORMAL"
        print(f"Per-session: {round(actual_kb, 2)} KB/session  {status}  (spec: 3.0 KB)")
    # -----------------------------------
    fc = result.get("forecast", {})
    fc_lin = result.get("forecast_linear", {})
    fc_exp = result.get("forecast_exp", {})
    pts    = result.get("history_points", 0)

    if fc.get("model") == "insufficient_data":
        print(f"\nForecast         insufficient data ({pts} snapshots, need ≥3)")
        print(f"                 Snapshots are written hourly — check back tomorrow")
    else:
        print(f"\nForecast model   {fc['best_model']}  (R²={fc['r_squared']})")
        print(f"  Daily rate:    {fc['daily_rate_mb']} MB/day")
        d1 = fc['days_to_1gb']
        d10 = fc['days_to_10gb']
        print(f"  Days to 1 GB:  {d1 if d1 > 0 else '—'}")
        print(f"  Days to 10 GB: {d10 if d10 > 0 else '—'}")
        print(f"\n  Linear:  rate={fc_lin['daily_rate_mb']} MB/day  R²={fc_lin['r_squared']}")
        print(f"  Exp:     rate={fc_exp['daily_rate_mb']} MB/day  R²={fc_exp['r_squared']}")
        print(f"  History: {pts} snapshots (last 30 days)")

def _print_help():
    print(
        "Mnemostroma — local cognitive memory layer for AI agents\n"
        "\n"
        "Usage:\n"
        "  mnemostroma <command> [options]\n"
        "\n"
        "Commands:\n"
        "  setup                 First-time setup: create ~/.mnemostroma/, copy config\n"
        "  on                    Start daemon in background (user mode)\n"
        "  off                   Stop running daemon\n"
        "  status                Show daemon state and metrics\n"
        "  service [sub]         Manage system service (systemd/launchd)\n"
        "                          install    — register and start service\n"
        "                          uninstall  — remove service\n"
        "                          status     — show raw service status\n"
        "  install-models        Download ONNX models from HuggingFace\n"
        "                          --force   re-download even if already present\n"
        "  mcp                   Start MCP server (alias for run)\n"
        "  run                   Start daemon in foreground (dev/debug mode)\n"
        "                          --config <path>     config.json path  (default: config.json)\n"
        "                          --db <path>         database path     (default: mnemostroma.db)\n"
        "                          --model-dir <path>  models directory  (default: models)\n"
        "  dump                  Trigger RAM dump in running daemon (writes to ~/.mnemostroma/dumps/)\n"
        "  growth                Show session growth stats and DB size forecast\n"
        "                          --db <path>      path to mnemostroma.db\n"
        "  logs                  Analyze logs.db — anomalies and calibration recommendations\n"
        "                          --db <path>      path to logs.db (default: logs.db)\n"
        "                          --days <N>       analysis window in days (default: 7)\n"
        "                          --json           output as JSON\n"
        "  tray                  System tray status indicator (requires pip install mnemostroma[tray])\n"
        "                          --db <path>      path to logs.db (default: logs.db)\n"
        "                          --interval <N>   poll every N seconds (default: 3)\n"
        "  watch                 Live terminal dashboard (reads logs.db)\n"
        "                          --db <path>      path to logs.db (default: logs.db)\n"
        "                          --interval <N>   refresh every N seconds (default: 2)\n"
        "                          --window <N>     show last N seconds of activity (default: 30)\n"
        "  config <sub> [args]   View and edit config parameters\n"
        "                          list [section]   — show all / section params\n"
        "                          get  <key>       — print value\n"
        "                          set  <key> <val> — update value\n"
        "\n"
        "Quick start:\n"
        "  pip install mnemostroma\n"
        "  mnemostroma setup\n"
        "  mnemostroma on\n"
        "  # Models will auto-install during 'setup'\n"
    )


def cli():
    """Main CLI entry point for the `mnemostroma` command."""
    logging.basicConfig(level=logging.WARNING)
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return

    command = args[0]

    if command == "setup":
        setup_args = args[1:]
        if "--inject" in setup_args:
            idx = setup_args.index("--inject")
            if idx + 1 >= len(setup_args):
                print("ERROR: --inject requires a file path argument")
                print("       Example: mnemostroma setup --inject ~/.claude/CLAUDE.md")
                sys.exit(1)
            from mnemostroma.setup.inject import inject as _inject
            result = _inject(Path(setup_args[idx + 1]))
            print(result)
        elif "--undo" in setup_args:
            idx = setup_args.index("--undo")
            if idx + 1 >= len(setup_args):
                print("ERROR: --undo requires a file path argument")
                sys.exit(1)
            from mnemostroma.setup.inject import undo as _undo
            result = _undo(Path(setup_args[idx + 1]))
            print(result)
        elif "--status" in setup_args:
            idx = setup_args.index("--status")
            if idx + 1 >= len(setup_args):
                print("ERROR: --status requires a file path argument")
                sys.exit(1)
            from mnemostroma.setup.inject import status as _status
            path = Path(setup_args[idx + 1]).expanduser().resolve()
            present = _status(path)
            icon = "✓" if present else "✗"
            state = "present" if present else "not found"
            print(f"  {icon} Memory protocol {state} — {path}")
        elif "--print-protocol" in setup_args:
            from mnemostroma.setup.protocol import get_block
            print(get_block())
        else:
            _cmd_setup()

    elif command == "on":
        _cmd_on()

    elif command == "off":
        _cmd_off()

    elif command in ("run", "mcp"):
        import argparse as _ap
        prog = f"mnemostroma {command}"
        p = _ap.ArgumentParser(prog=prog, add_help=False)
        
        # In 'mcp' mode, we default to user dir paths
        if command == "mcp":
            def_cfg = str(_MNEMO_DIR / "config.json")
            def_db  = str(_MNEMO_DIR / "mnemostroma.db")
            def_mod = str(_MNEMO_DIR / "models")
        else:
            def_cfg = "config.json"
            def_db  = "mnemostroma.db"
            def_mod = "models"

        p.add_argument("--config",    default=def_cfg, help="Path to config.json")
        p.add_argument("--db",        default=def_db,  help="Path to database")
        p.add_argument("--model-dir", default=def_mod, help="Models directory")
        ra, _ = p.parse_known_args(args[1:])
        
        # Guard: check environment before starting MCP
        manifest_path = _MNEMO_DIR / "models_manifest.json"
        if not manifest_path.exists():
            manifest_path = Path("models_manifest.json")
            
        _check_environment_ready(Path(ra.config), manifest_path, Path(ra.model_dir))
        
        try:
            asyncio.run(_run_daemon(ra.config, ra.db, ra.model_dir))
        except KeyboardInterrupt:
            pass

    elif command == "install-models":
        force = "--force" in args
        # User-mode: prefer ~/.mnemostroma/models_manifest.json
        manifest_path = _MNEMO_DIR / "models_manifest.json"
        if not manifest_path.exists():
            # Dev-mode fallback: CWD
            manifest_path = Path("models_manifest.json")
        if not manifest_path.exists():
            print(f"ERROR: models_manifest.json not found.")
            print(f"       Run 'mnemostroma setup' first, or run from the project root.")
            sys.exit(1)
        _install_models(manifest_path, force=force)

    elif command == "status":
        _print_status()

    elif command == "dump":
        _cmd_dump()

    elif command == "growth":
        import argparse as _ap
        p = _ap.ArgumentParser(prog="mnemostroma growth", add_help=False)
        p.add_argument("--db", default="mnemostroma.db", help="Path to mnemostroma.db")
        ga, _ = p.parse_known_args(args[1:])
        try:
            asyncio.run(_cmd_growth_async(ga.db))
        except KeyboardInterrupt:
            pass

    elif command == "logs":
        from mnemostroma.tools.logs import run_logs
        import argparse as _ap
        p = _ap.ArgumentParser(prog="mnemostroma logs", add_help=False)
        p.add_argument("--db",   default="logs.db", help="Path to logs.db")
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--json", action="store_true")
        la, _ = p.parse_known_args(args[1:])
        run_logs(la.db, la.days, la.json)

    elif command == "tray":
        from mnemostroma.tools.tray import run_tray
        import argparse as _ap
        p = _ap.ArgumentParser(prog="mnemostroma tray", add_help=False)
        p.add_argument("--db",       default="logs.db", help="Path to logs.db")
        p.add_argument("--interval", type=int, default=3, help="Poll interval (seconds)")
        ta, _ = p.parse_known_args(args[1:])
        run_tray(Path(ta.db), interval=ta.interval)

    elif command == "watch":
        from mnemostroma.tools.watch import run_watch
        import argparse as _ap
        p = _ap.ArgumentParser(prog="mnemostroma watch", add_help=False)
        p.add_argument("--db",       default="logs.db",  help="Path to logs.db")
        p.add_argument("--interval", type=int, default=2,  help="Refresh interval (seconds)")
        p.add_argument("--window",   type=int, default=30, help="Activity window (seconds)")
        wa, _ = p.parse_known_args(args[1:])
        run_watch(Path(wa.db), interval=wa.interval, window_sec=wa.window)

    elif command == "sse":
        try:
            from mnemostroma.integration.mcp_sse_adapter import run as _run_sse
            asyncio.run(_run_sse())
        except ImportError:
            print("ERROR: SSE adapter requires starlette and uvicorn.")
            print("       Install with: pip install mnemostroma[sse]")
            sys.exit(1)
        except KeyboardInterrupt:
            pass

    elif command == "service":
        _cmd_service(args[1:])

    elif command == "config":
        _handle_config(args[1:])

    else:
        print(f"Unknown command: {command!r}\n")
        _print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
