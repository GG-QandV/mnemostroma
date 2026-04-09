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
from pathlib import Path
from typing import Any

logger = logging.getLogger("mnemostroma.ipc")

_MNEMO_DIR = Path.home() / ".mnemostroma"
SOCKET_PATH = _MNEMO_DIR / "daemon.sock"
PIPE_NAME = r"\\.\pipe\mnemostroma"

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
            self._server = await asyncio.start_server(
                self._handle_client,
                pipe=PIPE_NAME,
            )
            logger.info(f"IPC server listening on {PIPE_NAME}")
        else:
            SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOCKET_PATH.unlink(missing_ok=True)
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=str(SOCKET_PATH),
            )
            logger.info(f"IPC server listening on {SOCKET_PATH}")

        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        msg_id = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                    msg_id = msg.get("id")
                    result = await self._dispatch(msg)
                    payload = json.dumps(
                        {"id": msg_id, "result": result},
                        default=str,
                        ensure_ascii=False,
                    )
                except Exception as exc:
                    payload = json.dumps(
                        {"id": msg_id, "error": str(exc)},
                        ensure_ascii=False,
                    )
                writer.write((payload + "\n").encode())
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, msg: dict) -> Any:
        tool = msg.get("tool")
        args = msg.get("args", {})
        conductor = self._conductor

        if conductor.ctx is None:
            raise RuntimeError("daemon not ready")
        ctx = conductor.ctx

        # ── Observer ─────────────────────────────────────────────────────
        if tool == "observe":
            await conductor.observe(args["session_id"], args["text"])
            return {"ok": True}

        elif tool == "observe_user":
            await conductor.observe_user(args["text"])
            return {"ok": True}

        # ── Session reads ────────────────────────────────────────────────
        elif tool == "ctx_semantic":
            from .tools.read import ctx_semantic
            return await ctx_semantic(
                args["query"], ctx,
                top_n=args.get("top_n", 5),
            )

        elif tool == "ctx_get":
            from .tools.read import ctx_get
            return await ctx_get(args["session_id"], ctx)

        elif tool == "ctx_search":
            from .tools.read import ctx_search
            return await ctx_search(
                tags=args["tags"],
                ctx=ctx,
                importance=args.get("importance"),
                age=args.get("age"),
                limit=args.get("limit", 10),
            )

        elif tool == "ctx_full":
            from .tools.read import ctx_full
            result = await ctx_full(args["session_id"], ctx)
            if result is None:
                raise KeyError(f"session not found: {args['session_id']}")
            return result

        elif tool == "ctx_anchors":
            from .tools.read import ctx_anchors
            return await ctx_anchors(
                ctx=ctx,
                anchor_type=args.get("anchor_type"),
                session_id=args.get("session_id"),
                limit=args.get("limit", 20),
            )

        elif tool == "ctx_precision":
            from .tools.read import ctx_precision
            return await ctx_precision(
                ctx=ctx,
                precision_type=args.get("precision_type"),
                importance=args.get("importance"),
                limit=args.get("limit", 20),
            )

        elif tool == "ctx_recent":
            from .tools.read import ctx_recent
            return await ctx_recent(
                ctx=ctx,
                days=args.get("days", 7.0),
                by=args.get("by", "created"),
                limit=args.get("limit", 20),
            )

        elif tool == "ctx_active":
            from .tools.read import ctx_active
            return await ctx_active(ctx)

        # ── Session writes ───────────────────────────────────────────────
        elif tool == "ctx_expire":
            from .tools.write import ctx_expire
            await ctx_expire(args["session_id"], ctx)
            return {"ok": True}

        elif tool == "ctx_urgent":
            from .tools.write import ctx_urgent
            return await ctx_urgent(ctx, hours_ahead=args.get("hours_ahead", 72.0))

        # ── Admin ────────────────────────────────────────────────────────
        elif tool == "ctx_load":
            from .tools.admin import ctx_load
            result = await ctx_load(args["session_id"], ctx)
            if result is None:
                raise KeyError(f"session not found in SQLite: {args['session_id']}")
            return result

        elif tool == "ctx_bridge":
            from .tools.admin import ctx_bridge
            return await ctx_bridge(ctx)

        # ── Content ─────────────────────────────────────────────────────
        elif tool == "save_content":
            from .tools.write import save_content
            return await save_content(
                content_id=args["content_id"],
                text=args["text"],
                ctx=ctx,
            )

        elif tool == "content_search":
            from .tools.content import content_search
            return await content_search(
                query=args["query"],
                ctx=ctx,
                project_id=args.get("project_id"),
                status=args.get("status", "active"),
                top_k=args.get("top_k", 5),
            )

        elif tool == "content_get":
            from .tools.content import content_get
            result = await content_get(
                content_id=args["content_id"],
                ctx=ctx,
                version=args.get("version"),
            )
            if result is None:
                raise KeyError(f"content not found: {args['content_id']}")
            return result

        elif tool == "content_raw":
            from .tools.content import content_raw
            result = await content_raw(
                content_id=args["content_id"],
                ctx=ctx,
                version=args.get("version"),
            )
            if result is None:
                raise KeyError(f"content not found: {args['content_id']}")
            return {"content": result}

        elif tool == "content_history":
            from .tools.content import content_history
            return await content_history(args["content_id"], ctx)

        else:
            raise ValueError(f"unknown tool: {tool!r}")
