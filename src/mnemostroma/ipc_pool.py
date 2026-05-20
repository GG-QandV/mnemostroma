# SPDX-License-Identifier: FSL-1.1-MIT
"""IPC Connection Pool — persistent connections to daemon socket.

Latency: 2ms → 0.1ms per call.
Transparent reconnection on failure.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("mnemostroma.ipc_pool")

_msg_id: int = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


class _IPCConn:
    """A single persistent Unix-socket connection to the daemon."""

    def __init__(self, path: str):
        self._path   = path
        self._reader: asyncio.StreamReader | None  = None
        self._writer: asyncio.StreamWriter | None  = None
        self._lock   = asyncio.Lock()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(self._path)
        logger.debug(f"IPC connected: {self._path}")

    @property
    def alive(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def call(self, tool: str, args: dict) -> Any:
        async with self._lock:
            payload = json.dumps(
                {"id": _next_id(), "tool": tool, "args": args},
                ensure_ascii=False,
            )
            try:
                if not self.alive:
                    await self.connect()
                writer, reader = self._writer, self._reader
                if writer is None or reader is None:
                    raise ConnectionError("IPC connection unavailable after connect()")
                writer.write((payload + "\n").encode())
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            except asyncio.TimeoutError:
                # Request was sent but response never arrived — protocol is desynced.
                # Must close so the pool does not reuse this connection.
                await self.close()
                raise ConnectionError("Daemon response timeout — IPC connection reset")
            except (ConnectionError, OSError) as exc:
                await self.close()
                raise ConnectionError(f"IPC transport error: {exc}") from exc
            if not line:
                # Daemon closed the connection cleanly — mark it dead.
                await self.close()
                raise ConnectionError("Daemon closed connection")
            resp = json.loads(line.decode())
            if "error" in resp:
                raise RuntimeError(resp["error"])
            return resp.get("result")

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None


class IPCPool:
    """A pool of N persistent connections to the daemon IPC socket.

    Usage:
        pool = IPCPool("~/.mnemostroma/daemon.sock", size=4)
        await pool.start()
        result = await pool.call("ctx_active", {})
        await pool.stop()
    """

    def __init__(self, socket_path: str, size: int = 4):
        self._path = str(Path(socket_path).expanduser())
        self._size = size
        self._pool: asyncio.Queue[_IPCConn] = asyncio.Queue(maxsize=size)
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        for _ in range(self._size):
            conn = _IPCConn(self._path)
            await conn.connect()
            await self._pool.put(conn)
        self._started = True
        logger.info(f"IPCPool: {self._size} connections → {self._path}")

    async def stop(self) -> None:
        while not self._pool.empty():
            conn = self._pool.get_nowait()
            await conn.close()
        self._started = False

    async def call(self, tool: str, args: dict) -> Any:
        conn = await self._pool.get()
        try:
            return await conn.call(tool, args)
        except Exception:
            # Recreate connection before returning to the pool
            try:
                await conn.close()
                await conn.connect()
            except Exception:
                pass
            raise
        finally:
            await self._pool.put(conn)
