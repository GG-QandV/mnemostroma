# SPDX-License-Identifier: FSL-1.1-MIT
"""MCP stdio adapter — thin proxy between Claude Code and the Mnemostroma daemon.

Zero-dependency MCP implementation: JSON-RPC 2.0 over stdin/stdout.
No mcp SDK, no pydantic, no anyio — stdlib only (asyncio + json).

Protocol: MCP 2024-11-05
"""
import asyncio
import json
import logging
import os
import stat
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("mnemostroma.mcp_adapter")

_MNEMO_DIR            = Path.home() / ".mnemostroma"
_SOCKET_PATH          = _MNEMO_DIR / "daemon.sock"
_PIPE_NAME            = r"\\.\pipe\mnemostroma"
_CURRENT_SESSION_FILE = _MNEMO_DIR / "current_session"

_VERSION  = "1.11.0"
_PROTOCOL = "2024-11-05"

# ── Tool definitions — plain dicts, no pydantic ───────────────────────

_TOOLS = [
    {
        "name": "ctx_semantic",
        "description": "Semantic search in memory. Returns relevant sessions based on meaning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_n": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ctx_get",
        "description": "Retrieve a specific session by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "ctx_search",
        "description": "Search for sessions using tags, importance, or age filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "string"},
                "age": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["tags"],
        },
    },
    {
        "name": "ctx_full",
        "description": "Get the complete session transcript including full content from SQLite.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "ctx_anchors",
        "description": "Retrieve subconscious layer anchors: decisions, facts, people, events, or deadlines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "anchor_type": {"type": "string"},
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "ctx_precision",
        "description": "Retrieve high-precision artifacts: links, formulas, quotes, or specific data points.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "precision_type": {"type": "string"},
                "importance": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "content_search",
        "description": "Semantic search across the content branch (code, docs, configs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project_id": {"type": "string"},
                "status": {"type": "string", "default": "active"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },

    {
        "name": "content_raw",
        "description": "Retrieve the full raw text of a specific content version.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content_id": {"type": "string"},
                "version": {"type": "integer"},
            },
            "required": ["content_id"],
        },
    },
    {
        "name": "content_history",
        "description": "Retrieve the version history for a specific content block.",
        "inputSchema": {
            "type": "object",
            "properties": {"content_id": {"type": "string"}},
            "required": ["content_id"],
        },
    },
    {
        "name": "ctx_bridge",
        "description": "Generate a structured context bridge package for handoff to the next agent.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ctx_recent",
        "description": "Retrieve sessions from the last N days, filtered by creation or access date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "number", "default": 7.0},
                "by": {"type": "string", "enum": ["created", "accessed"], "default": "created"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]

# ── IPC client ────────────────────────────────────────────────────────

_msg_id = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


if sys.platform == "win32":
    async def _open_connection() -> tuple:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.create_pipe_connection(lambda: protocol, _PIPE_NAME)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer
else:
    async def _open_connection() -> tuple:
        return await asyncio.open_unix_connection(str(_SOCKET_PATH))


async def _ipc_call(tool: str, args: dict) -> Any:
    try:
        reader, writer = await _open_connection()
    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        raise ConnectionError("Mnemostroma daemon not running. Start with: mnemostroma on") from e

    try:
        payload = json.dumps({"id": _next_id(), "tool": tool, "args": args}, ensure_ascii=False)
        writer.write((payload + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        response = json.loads(line.decode())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result")
    except asyncio.TimeoutError:
        raise ConnectionError("Mnemostroma daemon did not respond within 10s")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ── JSON-RPC 2.0 handler ──────────────────────────────────────────────

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle(req: dict) -> Optional[dict]:
    method = req.get("method", "")
    rid    = req.get("id")          # None for notifications
    params = req.get("params") or {}

    # Notifications — no response
    if rid is None:
        return None

    if method == "initialize":
        return _ok(rid, {
            "protocolVersion": _PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mnemostroma", "version": _VERSION},
        })

    if method == "ping":
        return _ok(rid, {})

    if method == "tools/list":
        return _ok(rid, {"tools": _TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            result = await _ipc_call(name, args)
            text = json.dumps(result, default=str, ensure_ascii=False)
        except ConnectionError as e:
            text = json.dumps({"error": str(e)})
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e, exc_info=True)
            text = json.dumps({"error": str(e)})
        return _ok(rid, {"content": [{"type": "text", "text": text}]})

    return _err(rid, -32601, f"Method not found: {method}")


# ── Entry point ───────────────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Write current session_id for proxy_passthrough
    try:
        result = await asyncio.wait_for(_ipc_call("ctx_active", {}), timeout=3.0)
        sid = (result or {}).get("session_id") or f"passthrough-{date.today().isoformat()}"
    except Exception:
        sid = f"passthrough-{date.today().isoformat()}"
    _CURRENT_SESSION_FILE.write_text(sid, encoding="utf-8")

    # Connect stdin/stdout as async streams.
    # Use get_running_loop() — get_event_loop() is deprecated in Python 3.12.
    #
    # Pre-flight check: only use connect_read_pipe when stdin is an actual
    # pipe or socket.  When an IDE (Antigravity, Cursor, etc.) launches the
    # adapter with stdin redirected to /dev/null or a regular file the kernel
    # refuses to epoll fd=0, raising PermissionError deep inside an asyncio
    # callback — too late for try/except around the await to catch it.
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    try:
        st = os.stat(sys.stdin.fileno())
        _stdin_is_pipe = stat.S_ISFIFO(st.st_mode) or stat.S_ISSOCK(st.st_mode)
    except Exception:
        _stdin_is_pipe = False

    if _stdin_is_pipe:
        try:
            await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
            )
            use_pipe = True
        except (PermissionError, OSError) as exc:
            logger.warning("connect_read_pipe failed (%s); falling back to blocking readline", exc)
            use_pipe = False
    else:
        logger.debug("stdin is not a pipe/socket — using blocking readline fallback")
        use_pipe = False

    if use_pipe:
        async for raw in reader:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = await _handle(req)
            if resp is not None:
                sys.stdout.buffer.write(json.dumps(resp, ensure_ascii=False).encode() + b"\n")
                sys.stdout.buffer.flush()
    else:
        # Fallback: read stdin line-by-line via executor (blocking I/O off the loop)
        while True:
            raw = await loop.run_in_executor(None, sys.stdin.readline)
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = await _handle(req)
            if resp is not None:
                sys.stdout.buffer.write(json.dumps(resp, ensure_ascii=False).encode() + b"\n")
                sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())
