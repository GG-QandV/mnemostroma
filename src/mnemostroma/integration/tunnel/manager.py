# manager.py — lifecycle туннеля + OAuth адаптера как единый процесс
import asyncio
import json
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .providers.serveo import ServeoTunnelManager
from .token import get_or_create_tunnel_token

logger = logging.getLogger("mnemostroma.tunnel.manager")

MNEMO_DIR: Path = Path.home() / ".mnemostroma"
TUNNEL_CONFIG_PATH: Path = MNEMO_DIR / "tunnel_config.json"
TUNNEL_URLS_DIR: Path = MNEMO_DIR / "tunnel_urls"
TUNNEL_TOKENS_DIR: Path = MNEMO_DIR / "tunnel_tokens"
ADAPTER_PORT: int = 8769   # OAuth адаптер (не конфликтует с 8768 mcphttpadapter)
# Same contract as state.py TunnelState detection (ACTIVE = pid alive + url)
_STATE_PID_FILE: Path = MNEMO_DIR / "serveo_tunnel.pid"


def _mark_state_pid(pid: int | None) -> None:
    if pid is None:
        _STATE_PID_FILE.unlink(missing_ok=True)
    else:
        _STATE_PID_FILE.write_text(str(pid), encoding="utf-8")

# Respawn guard for the OAuth adapter child — caps restarts within a rolling
# window so a persistently broken adapter doesn't crash-loop forever.
ADAPTER_RESPAWN_MAX: int = 5
ADAPTER_RESPAWN_WINDOW_SEC: float = 300.0
ADAPTER_HEALTHCHECK_INTERVAL_SEC: float = 15.0
ADAPTER_HEALTHCHECK_TIMEOUT_SEC: float = 3.0


def _load_tunnel_config() -> dict[str, Any]:
    """Load tunnel config from ~/.mnemostroma/tunnel_config.json."""
    if TUNNEL_CONFIG_PATH.exists():
        return json.loads(TUNNEL_CONFIG_PATH.read_text(encoding="utf-8"))
    return {"provider": "serveo", "subdomain": None, "port": ADAPTER_PORT}


def _save_tunnel_config(config: dict[str, Any]) -> None:
    """Save tunnel config to ~/.mnemostroma/tunnel_config.json."""
    MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    TUNNEL_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _get_or_ask_subdomain() -> str | None:
    """Read subdomain from config, or ask user on first run in interactive mode."""
    from mnemostroma.integration.tunnel.resolve import _is_headless
    config = _load_tunnel_config()
    subdomain = config.get("subdomain")

    if subdomain is None:
        if _is_headless():
            return None  # Headless mode — do not prompt, launch anonymously

        # First run in interactive mode — generate unique random default
        import secrets
        random_suffix = secrets.token_hex(4)
        default_subdomain = f"mnemo-{random_suffix}"

        try:
            raw = input(f"Subdomain for Serveo tunnel [default: {default_subdomain}]: ").strip()
            subdomain = raw if raw else default_subdomain
            config["subdomain"] = subdomain
            _save_tunnel_config(config)
            print(f"  Saved unique subdomain: {subdomain}")
        except EOFError:
            return None

    return subdomain


def _save_tunnel_url(subdomain: str | None, public_url: str) -> None:
    """
    Save PUBLIC_URL:
    1. Каноническое хранилище: tunnel_urls/user-{subdomain}.txt
    2. Flat alias для UI: tunnel_url (атомарная запись через tmp→rename)
    """
    TUNNEL_URLS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"user-{subdomain}.txt" if subdomain else "user-anonymous.txt"
    (TUNNEL_URLS_DIR / filename).write_text(public_url, encoding="utf-8")

    flat = MNEMO_DIR / "tunnel_url"
    tmp  = flat.with_suffix(".tmp")
    tmp.write_text(public_url, encoding="utf-8")
    tmp.replace(flat)


def _save_tunnel_token(subdomain: str | None, token: str) -> None:
    """Save token to ~/.mnemostroma/tunnel_tokens/user-{subdomain}.txt."""
    TUNNEL_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"user-{subdomain}.txt" if subdomain else "user-anonymous.txt"
    token_file = TUNNEL_TOKENS_DIR / filename
    token_file.write_text(token, encoding="utf-8")


def _spawn_adapter_proc(public_url: str, adapter_log_file) -> "asyncio.subprocess.Process":
    import os as _os
    adapter_env = {**_os.environ, "MNEMOSTROMA_DEBUG": "1"}
    return asyncio.create_subprocess_exec(
        sys.executable, "-m", "mnemostroma.integration.mcp_oauth_adapter",
        "--port", str(ADAPTER_PORT),
        "--public-url", public_url,
        env=adapter_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=adapter_log_file,
        stderr=adapter_log_file,
    )


async def _adapter_port_healthy(timeout: float) -> bool:
    """TCP connect check — does the OAuth adapter actually accept connections."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", ADAPTER_PORT), timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _supervise_adapter(
    public_url: str, adapter_log_file, stop_event: asyncio.Event,
    adapter_proc: "asyncio.subprocess.Process",
) -> "asyncio.subprocess.Process":
    """Returns the currently-live adapter Process (may differ from the one
    passed in, if it was respawned) so the caller can shut down the right PID."""
    """Owns the OAuth adapter child for the life of the tunnel.

    Restarts it on unexpected exit (crash) or on a sustained TCP hang —
    systemd only watches THIS process (tunnel start --foreground), so if
    nobody here respawns the grandchild, a dead/hung adapter stays dead
    forever even though the service shows "active".
    """
    proc = adapter_proc
    respawn_times: list[float] = []

    async def _respawn(reason: str) -> bool:
        now = time.monotonic()
        respawn_times[:] = [t for t in respawn_times if now - t < ADAPTER_RESPAWN_WINDOW_SEC]
        if len(respawn_times) >= ADAPTER_RESPAWN_MAX:
            logger.error(
                f"OAuth adapter: {reason}, but already restarted "
                f"{len(respawn_times)}x in {ADAPTER_RESPAWN_WINDOW_SEC:.0f}s — giving up, "
                f"not respawning again (manual intervention needed)"
            )
            return False
        logger.warning(f"OAuth adapter: {reason} → respawning")
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass
        respawn_times.append(now)
        return True

    while not stop_event.is_set():
        wait_exit = asyncio.ensure_future(proc.wait())
        wait_stop = asyncio.ensure_future(stop_event.wait())
        done, pending = await asyncio.wait(
            {wait_exit, wait_stop},
            timeout=ADAPTER_HEALTHCHECK_INTERVAL_SEC,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for fut in pending:
            fut.cancel()

        if stop_event.is_set():
            return proc

        if wait_exit in done:
            ok = await _respawn(f"exited unexpectedly (code={proc.returncode})")
            if not ok:
                return proc
            proc = await _spawn_adapter_proc(public_url, adapter_log_file)
            continue

        # Timed out waiting (interval elapsed) — process still alive, check it actually responds.
        if not await _adapter_port_healthy(ADAPTER_HEALTHCHECK_TIMEOUT_SEC):
            ok = await _respawn(f"hung (port {ADAPTER_PORT} not responding)")
            if not ok:
                return proc
            proc = await _spawn_adapter_proc(public_url, adapter_log_file)

    return proc


def _external_cloudflared_active() -> bool:
    """True если туннель уже поднят внешним cloudflared (systemd-сервис или чужой процесс)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "cloudflared"],
            capture_output=True,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    import psutil
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if any("cloudflared" in (c or "") for c in proc.info.get("cmdline") or []):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


async def _run_cloudflare(config: dict[str, Any]) -> None:
    """Cloudflare provider: named tunnel (external/systemd) или ephemeral fallback."""
    token: str = get_or_create_tunnel_token()
    public_url: str | None = config.get("public_url")

    if public_url and _external_cloudflared_active():
        # Attach mode: туннель управляется снаружи (systemd), мы только OAuth-адаптер
        print(f"  Cloudflare tunnel already active (external): {public_url}")
        _save_tunnel_url(None, public_url)
    else:
        from .providers.cloudflare import start_tunnel
        print("  Starting Cloudflare tunnel...", end=" ", flush=True)
        try:
            tunnel_proc, url = await start_tunnel(port=ADAPTER_PORT)
        except Exception as e:
            print(f"\n✗ Failed to start Cloudflare tunnel: {e}")
            return
        public_url = url
        print("✓")
        _save_tunnel_url(None, url)

    _save_tunnel_token(None, token)

    from mnemostroma.integration.tunnel.state import _kill_port_occupants
    _kill_port_occupants(ADAPTER_PORT)
    await asyncio.sleep(0.3)
    adapter_log_file = open(MNEMO_DIR / "adapter.log", "a", encoding="utf-8")  # noqa: WPS515
    adapter_proc = await _spawn_adapter_proc(public_url, adapter_log_file)
    _mark_state_pid(adapter_proc.pid)
    _print_connection_guide(public_url, token)

    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    stop_event: asyncio.Event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    adapter_proc = await _supervise_adapter(public_url, adapter_log_file, stop_event, adapter_proc)
    adapter_log_file.close()

    print("\n  Stopping OAuth adapter...")
    _mark_state_pid(None)
    try:
        adapter_proc.terminate()
        await asyncio.wait_for(adapter_proc.wait(), timeout=5)
    except Exception:
        try:
            adapter_proc.kill()
        except Exception:
            pass
    print("  ✓ Stopped. (External Cloudflare tunnel left untouched)")


async def run(provider: str | None = None) -> None:
    config = _load_tunnel_config()
    provider = provider or config.get("provider", "serveo")

    if provider == "cloudflare":
        await _run_cloudflare(config)
        return

    token: str = get_or_create_tunnel_token()
    subdomain: str | None = _get_or_ask_subdomain()

    # 1. Запустить Serveo туннель ПЕРВЫМ (чтобы получить PUBLIC_URL)
    print("  Starting Serveo tunnel...", end=" ", flush=True)
    tunnel_mgr = ServeoTunnelManager(port=ADAPTER_PORT, subdomain=subdomain)
    try:
        public_url = tunnel_mgr.start(timeout=15.0)
    except TimeoutError as e:
        print(f"\n✗ Failed to start tunnel: {e}")
        return
    except RuntimeError as e:
        print(f"\n✗ SSH not available: {e}")
        return
    print("✓")

    # Save PUBLIC_URL and token for multi-user access
    _save_tunnel_url(subdomain, public_url)
    _save_tunnel_token(subdomain, token)

    # 2. Запустить OAuth адаптер с PUBLIC_URL
    print("  Starting OAuth adapter...", end=" ", flush=True)
    # Kill any process still holding ADAPTER_PORT before binding
    from mnemostroma.integration.tunnel.state import _kill_port_occupants
    _kill_port_occupants(ADAPTER_PORT)
    await asyncio.sleep(0.3)
    adapter_log_path = MNEMO_DIR / "adapter.log"
    adapter_log_file = open(adapter_log_path, "a", encoding="utf-8")  # noqa: WPS515
    adapter_proc: asyncio.subprocess.Process = await _spawn_adapter_proc(public_url, adapter_log_file)
    print("✓\n")

    _print_connection_guide(public_url, token)

    # 3. Ждать сигнала остановки, супервизируя OAuth-адаптер (crash + hang)
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    stop_event: asyncio.Event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows

    adapter_proc = await _supervise_adapter(public_url, adapter_log_file, stop_event, adapter_proc)
    adapter_log_file.close()
    await _shutdown(adapter_proc, tunnel_mgr)


async def _shutdown(
    adapter_proc: asyncio.subprocess.Process,
    tunnel_mgr: "ServeoTunnelManager | None" = None,
) -> None:
    print("\n  Stopping tunnel and adapter...")
    if tunnel_mgr is not None:
        try:
            tunnel_mgr.stop()
        except Exception as e:
            print(f"    Warning: Failed to stop tunnel: {e}")

    try:
        adapter_proc.terminate()
        await asyncio.wait_for(adapter_proc.wait(), timeout=5)
    except Exception:
        try:
            adapter_proc.kill()
        except Exception:
            pass

    print("  ✓ Stopped.")


def _print_connection_guide(url: str, token: str) -> None:
    print(f"""  ┌─────────────────────────────────────────────────────────────┐
  │ 🌐  YOUR BASE MCP SERVER URL:                                │
  │     {url:<48}│
  └─────────────────────────────────────────────────────────────┘

  🚀 CONNECT YOUR CHATS (STEP-BY-STEP):
  
  [Phase 0] Perplexity:
    1. Log into Perplexity and open Settings (from the left menu)
    2. On the right side, below the search bar, click the "+ Custom connector" button
    3. In the popup, enter a short Name (e.g. mnemo). Description is optional
    4. Paste EXACT URL: {url}/mcp
    5. Select Authorization: None and Type: Streamable HTTP
    6. Press "Done" and refresh the page (F5) to see the tools

  [Phase 1] Claude.ai:
    1. Open settings -> Connectors -> Customize
    2. Next to the "Connectors" title (near the search icon), click the plus (+) button
    3. Select 'Add custom connector'
    4. Set Name to: mnemo
    5. Paste EXACT URL: {url}/sse
    6. Leave 'Advanced' section as-is and click 'Add'
    7. On the right, under 'Tool permissions' -> 'Other tools'
    8. Select 'Always allow' for all listed tools

  [Phase 2] ChatGPT:
    1. Go to ChatGPT settings -> GPTs / Integrations -> Add MCP
    2. Select Type: HTTP
    3. Paste EXACT URL: {url}/mcp

  [Phase 3] Grok:
    1. Go to Grok settings -> Connected Services -> Add MCP
    2. Select Type: SSE
    3. Paste EXACT URL: {url}/sse
    4. Paste Bearer Token: {token}

  ℹ️ To stop the tunnel at any time, run:
     mnemostroma tunnel stop

  📋 Adapter debug log: ~/.mnemostroma/adapter.log
""")
