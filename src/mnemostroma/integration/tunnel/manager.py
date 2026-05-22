# manager.py — lifecycle туннеля + OAuth адаптера как единый процесс
import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

from .providers.cloudflare import start_tunnel
from .token import get_or_create_tunnel_token

TUNNEL_URL_PATH: Path = Path.home() / ".mnemostroma" / "tunnel_url"
ADAPTER_PORT: int = 8769   # OAuth адаптер (не конфликтует с 8768 mcphttpadapter)


async def run(provider: str = "cloudflare") -> None:
    token: str = get_or_create_tunnel_token()

    # 1. Запустить OAuth адаптер
    print("  Starting OAuth adapter...", end=" ", flush=True)
    adapter_proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "mnemostroma.integration.mcp_oauth_adapter",
        "--port", str(ADAPTER_PORT),
    )
    print("✓")

    # 2. Запустить туннель
    print("  Starting Cloudflare tunnel...", end=" ", flush=True)
    tunnel_proc, public_url = await start_tunnel(port=ADAPTER_PORT)
    TUNNEL_URL_PATH.write_text(public_url)
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
    await _shutdown(adapter_proc, tunnel_proc)


async def _shutdown(adapter_proc: asyncio.subprocess.Process, tunnel_proc: asyncio.subprocess.Process) -> None:
    print("\n  Stopping tunnel and adapter...")
    for proc in (tunnel_proc, adapter_proc):
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    TUNNEL_URL_PATH.unlink(missing_ok=True)
    print("  ✓ Stopped.")


def _print_connection_guide(url: str, token: str) -> None:
    print(f"""  ┌─────────────────────────────────────────────────────────────┐
  │  Your MCP URL:  {url:<43}│
  │  Bearer token:  cat ~/.mnemostroma/tunnel_token              │
  └─────────────────────────────────────────────────────────────┘

  Connect your chats:
  [Phase 0] Perplexity → paste URL, no auth needed
  [Phase 1] Claude.ai  → paste URL, OAuth auto (SSE transport)
  [Phase 2] ChatGPT    → paste URL, OAuth auto (HTTP transport)
  [Phase 3] Grok       → paste URL + Bearer token shown above

  Run `mnemostroma tunnel stop` to shutdown.
""")
