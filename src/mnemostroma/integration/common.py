# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import itertools
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("mnemostroma.integration.common")

_MNEMO_DIR: Path = Path.home() / ".mnemostroma"
_SOCKET_PATH: Path = _MNEMO_DIR / "daemon.sock"
_PIPE_NAME: str = r"\\.\pipe\mnemostroma"

# Tokens paths
TOKEN_PATH: Path = _MNEMO_DIR / "sse_token"
OBSERVE_TOKEN_PATH: Path = _MNEMO_DIR / "observe_token"

# ── Auth & Token (Atomic loading) ──────────────────────────────────────

def atomic_token_loader(token_path: Path, token_name: str) -> str:
    """Atomasically load or create a security token to prevent race conditions.
    
    Uses tempfile + rename pattern and safe file permissions.
    """
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    if not token_path.exists():
        token: str = secrets.token_urlsafe(32)
        tmp_path: Path = token_path.with_name(f"{token_path.name}.tmp")
        try:
            tmp_path.write_text(token, encoding="utf-8")
            tmp_path.chmod(0o600)
            os.replace(str(tmp_path), str(token_path))
            logger.info(f"Generated new {token_name} in {token_path}")
            return token
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Failed to write token file {token_path}: {e}") from e
    return token_path.read_text(encoding="utf-8").strip()

TOKEN: str = atomic_token_loader(TOKEN_PATH, "SSE/HTTP token")
OBSERVE_TOKEN: str = atomic_token_loader(OBSERVE_TOKEN_PATH, "observe token")

# ── Host Normalization & Localhost Checks ──────────────────────────────

def normalize_host(host: str) -> str:
    """Normalize IPv4-mapped IPv6 address (e.g. ::ffff:127.0.0.1 -> 127.0.0.1)."""
    if host and host.startswith("::ffff:"):
        return host[7:]
    return host or ""

def check_localhost(request: Request) -> bool:
    """Safely check if the request originates from localhost, supporting IPv6 loopback."""
    client = request.client
    if not client:
        return False
    host: str = normalize_host(client.host)
    return host in ("127.0.0.1", "localhost", "::1")

# ── Private Network Access (PNA) Middleware ────────────────────────────

class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    """Starlette middleware handling W3C Private Network Access (PNA) preflight queries."""
    
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # PNA Preflight is an OPTIONS request with special headers
        if request.method == "OPTIONS":
            if "access-control-request-private-network" in request.headers:
                origin: str = request.headers.get("origin", "*")
                response = Response(
                    content="",
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": request.headers.get("access-control-request-method", "GET, POST, OPTIONS, DELETE"),
                        "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
                        "Access-Control-Allow-Private-Network": "true",
                        "Access-Control-Max-Age": "86400",
                    }
                )
                return response
        
        response: Response = await call_next(request)
        if "origin" in request.headers:
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

# ── IPC Client with Timeouts ───────────────────────────────────────────

_msg_id_counter = itertools.count(1)

def _next_id() -> int:
    return next(_msg_id_counter)

if sys.platform == "win32":
    async def _open_pipe() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open Windows Named Pipe connection using Proactor loop."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.create_pipe_connection(
            lambda: protocol,
            _PIPE_NAME,
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer

async def safe_ipc_call(tool: str, args: dict[str, Any], timeout: float = 5.0) -> Any:
    """Send one request to the daemon IPC socket/pipe, with explicit timeout.
    
    Returns Any to accommodate diverse dynamic JSON return types.
    """
    if sys.platform == "win32":
        try:
            reader, writer = await _open_pipe()
        except OSError as e:
            raise ConnectionError(
                f"Mnemostroma daemon not running (pipe unavailable): {e}\n"
                "Start with: mnemostroma start"
            ) from e
    else:
        if not _SOCKET_PATH.exists():
            raise ConnectionError("Mnemostroma daemon not running.")
        reader, writer = await asyncio.open_unix_connection(str(_SOCKET_PATH))

    try:
        msg_id: int = _next_id()
        payload: str = json.dumps({"id": msg_id, "tool": tool, "args": args}, ensure_ascii=False)
        writer.write((payload + "\n").encode())
        await writer.drain()

        # Read with an explicit timeout to prevent thread starvation
        line: bytes = await asyncio.wait_for(reader.readline(), timeout=timeout)
        response: dict[str, Any] = json.loads(line.decode())

        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result")
    except asyncio.TimeoutError as te:
        raise TimeoutError(f"Mnemostroma daemon IPC call timed out after {timeout} seconds") from te
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
