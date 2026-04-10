# SPDX-License-Identifier: FSL-1.1-MIT
"""IPC Connection Pool — постоянные соединения к daemon socket.

Latency: 2ms → 0.1ms per call.
Прозрачное переподключение при обрыве.
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
    """Одно постоянное Unix-socket соединение к daemon."""

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
            if not self.alive:
                await self.connect()
            payload = json.dumps(
                {"id": _next_id(), "tool": tool, "args": args},
                ensure_ascii=False,
            )
            self._writer.write((payload + "\n").encode())
            await self._writer.drain()
            line = await asyncio.wait_for(self._reader.readline(), timeout=10.0)
            if not line:
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
    """Пул из N постоянных соединений к daemon IPC socket.

    Использование:
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
            # Пересоздать соединение перед возвратом в пул
            try:
                await conn.close()
                await conn.connect()
            except Exception:
                pass
            raise
        finally:
            await self._pool.put(conn)
