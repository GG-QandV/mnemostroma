# manager.py — lifecycle туннеля + OAuth адаптера как единый процесс
import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from .providers.serveo import ServeoTunnelManager
from .token import get_or_create_tunnel_token

MNEMO_DIR: Path = Path.home() / ".mnemostroma"
TUNNEL_CONFIG_PATH: Path = MNEMO_DIR / "tunnel_config.json"
TUNNEL_URLS_DIR: Path = MNEMO_DIR / "tunnel_urls"
TUNNEL_TOKENS_DIR: Path = MNEMO_DIR / "tunnel_tokens"
ADAPTER_PORT: int = 8769   # OAuth адаптер (не конфликтует с 8768 mcphttpadapter)


def _load_tunnel_config() -> dict[str, Any]:
    """Load tunnel config from ~/.mnemostroma/tunnel_config.json."""
    if TUNNEL_CONFIG_PATH.exists():
        return json.loads(TUNNEL_CONFIG_PATH.read_text(encoding="utf-8"))
    return {"provider": "serveo", "subdomain": None, "port": ADAPTER_PORT}


def _save_tunnel_config(config: dict[str, Any]) -> None:
    """Save tunnel config to ~/.mnemostroma/tunnel_config.json."""
    MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    TUNNEL_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _get_or_ask_subdomain() -> Optional[str]:
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


def _save_tunnel_url(subdomain: Optional[str], public_url: str) -> None:
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


def _save_tunnel_token(subdomain: Optional[str], token: str) -> None:
    """Save token to ~/.mnemostroma/tunnel_tokens/user-{subdomain}.txt."""
    TUNNEL_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"user-{subdomain}.txt" if subdomain else "user-anonymous.txt"
    token_file = TUNNEL_TOKENS_DIR / filename
    token_file.write_text(token, encoding="utf-8")


async def run(provider: str = "serveo") -> None:
    token: str = get_or_create_tunnel_token()
    subdomain: Optional[str] = _get_or_ask_subdomain()

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
    adapter_proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "mnemostroma.integration.mcp_oauth_adapter",
        "--port", str(ADAPTER_PORT),
        "--public-url", public_url,
    )
    print("✓\n")

    _print_connection_guide(public_url, token)

    # 3. Ждать сигнала остановки
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    stop_event: asyncio.Event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows

    await stop_event.wait()
    await _shutdown(adapter_proc, tunnel_mgr)


async def _shutdown(adapter_proc: asyncio.subprocess.Process, tunnel_mgr: ServeoTunnelManager) -> None:
    print("\n  Stopping tunnel and adapter...")
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
""")
