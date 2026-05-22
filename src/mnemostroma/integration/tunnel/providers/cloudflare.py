# cloudflare.py — скачивание и запуск cloudflared
import asyncio
import platform
import re
import stat
import sys
from pathlib import Path

import httpx

BIN_DIR: Path = Path.home() / ".mnemostroma" / "bin"
CLOUDFLARED: Path = BIN_DIR / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")

DOWNLOAD_URLS: dict[tuple[str, str], str] = {
    ("linux",  "x86_64"):  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("linux",  "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("darwin", "x86_64"):  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64",
    ("darwin", "arm64"):   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64",
    ("win32",  "AMD64"):   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
}


async def ensure_cloudflared() -> Path:
    if CLOUDFLARED.exists():
        return CLOUDFLARED
    key: tuple[str, str] = (sys.platform, platform.machine())
    url: str | None = DOWNLOAD_URLS.get(key)
    if not url:
        raise RuntimeError(f"Unsupported platform: {key}")
    print("  Downloading cloudflared...", end=" ", flush=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        r: httpx.Response = await client.get(url)
        r.raise_for_status()
        CLOUDFLARED.write_bytes(r.content)
    if sys.platform != "win32":
        CLOUDFLARED.chmod(CLOUDFLARED.stat().st_mode | stat.S_IEXEC)
    print("✓")
    return CLOUDFLARED


async def start_tunnel(port: int = 8769) -> tuple[asyncio.subprocess.Process, str]:
    """Запускает cloudflared, возвращает (process, public_url)."""
    binary: Path = await ensure_cloudflared()
    proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
        str(binary), "tunnel", "--url", f"http://localhost:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    url: str = await _wait_for_url(proc)
    return proc, url


async def _wait_for_url(proc: asyncio.subprocess.Process, timeout: int = 30) -> str:
    pattern: re.Pattern[str] = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    if proc.stdout is None:
        raise RuntimeError("cloudflared stdout stream is None")
    
    async def read() -> str:
        assert proc.stdout is not None
        async for line in proc.stdout:
            decoded: str = line.decode(errors="replace")
            m: re.Match[str] | None = pattern.search(decoded)
            if m:
                return m.group(0)
        raise RuntimeError("cloudflared exited without providing a URL")
    return await asyncio.wait_for(read(), timeout=timeout)
