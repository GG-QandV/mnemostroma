# SPDX-License-Identifier: FSL-1.1-MIT
"""IPC server for Mnemostroma daemon.

Exposes a Unix socket (Linux/macOS) or Named Pipe (Windows) that accepts
newline-framed JSON-RPC requests and dispatches them to the conductor's
tool functions.

Protocol:
    → {"id": 1, "tool": "ctx_search", "args": {"tags": ["arch"]}}\n
    ← {"id": 1, "result": [...]}\n
    ← {"id": 1, "error": "message"}\n   (on failure)

All framing is \n-delimited. JSON escaping guarantees no embedded newlines.
No external dependencies — stdlib only.
"""
import asyncio
import json
import logging
import sys
import time as _time
from pathlib import Path
from typing import Any

logger = logging.getLogger("mnemostroma.ipc")


def _serialize(obj: Any) -> Any:
    """Convert SessionBrief / numpy types to JSON-safe dicts."""
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        import dataclasses
        d = dataclasses.asdict(obj)
        return {k: _serialize(v) for k, v in d.items()
                if k != "embedding"}  # skip raw vector
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return None  # drop embeddings
    except ImportError:
        pass
    return obj

_MNEMO_DIR = Path.home() / ".mnemostroma"
SOCKET_PATH = _MNEMO_DIR / "daemon.sock"
PIPE_NAME = r"\\.\pipe\mnemostroma"
_READY_FILE = _MNEMO_DIR / "daemon.ready"


class IPCServer:
    """Accepts tool calls from adapter processes over a local socket.

    Instantiated once in _run_daemon() after conductor.start().
    Owns no state beyond a reference to the conductor.
    """

    def __init__(self, conductor: Any) -> None:
        self._conductor = conductor
        self._server: asyncio.AbstractServer | None = None

    async def serve(self) -> None:
        """Start the socket server and run until cancelled."""
        if sys.platform == "win32":
            try:
                self._server = await asyncio.start_server(
                    self._handle_client,
                    pipe=PIPE_NAME,
                    limit=1024 * 1024 * 16,
                )
                logger.info(f"IPC server listening on {PIPE_NAME}")
            except OSError as e:
                # TCP fallback if Named Pipe fails
                self._server = await asyncio.start_server(
                    self._handle_client,
                    host="127.0.0.1",
                    port=8767,
                    limit=1024 * 1024 * 16,
                )
                logger.info(f"IPC server listening on TCP 127.0.0.1:8767 (pipe failed: {e})")
        else:
            SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOCKET_PATH.unlink(missing_ok=True)
            try:
                self._server = await asyncio.start_unix_server(
                    self._handle_client,
                    path=str(SOCKET_PATH),
                    limit=1024 * 1024 * 16,
                )
                logger.info(f"IPC server listening on {SOCKET_PATH}")
            except OSError as e:
                # TCP fallback for Unix as well
                self._server = await asyncio.start_server(
                    self._handle_client,
                    host="127.0.0.1",
                    port=8767,
                    limit=1024 * 1024 * 16,
                )
                logger.info(f"IPC server listening on TCP 127.0.0.1:8767 (unix socket failed: {e})")

        # Signal readiness to _cmd_on() after bind, before serve_forever
        try:
            _READY_FILE.write_text(str(int(_time.time())))
        except Exception:
            pass

        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError as e:
                    response = json.dumps({"id": None, "error": f"invalid JSON: {e}"})
                    writer.write((response + "\n").encode())
                    await writer.drain()
                    continue

                try:
                    result = await self._conductor.dispatch(
                        msg["tool"], msg.get("args", {})
                    )
                    response = json.dumps(
                        {"id": msg.get("id"), "result": _serialize(result)},
                        default=str, ensure_ascii=False,
                    )
                except KeyError as e:
                    response = json.dumps({
                        "id":    msg.get("id"),
                        "error": f"missing required argument: {e}",
                        "code":  "missing_arg",
                    })
                except ValueError as e:
                    response = json.dumps({
                        "id":    msg.get("id"),
                        "error": str(e),
                        "code":  "unknown_tool",
                    })
                except Exception as e:
                    logger.error(f"dispatch {msg.get('tool')!r}: {e}", exc_info=True)
                    response = json.dumps({"id": msg.get("id"), "error": str(e)})

                writer.write((response + "\n").encode())
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
