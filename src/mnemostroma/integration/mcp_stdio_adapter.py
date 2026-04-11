# SPDX-License-Identifier: FSL-1.1-MIT
"""MCP stdio adapter — thin proxy between Claude Code and the Mnemostroma daemon.

Replaces mcp_server.py as the MCP entry point for Claude Code.
Speaks MCP protocol on stdio; forwards tool/call to the daemon IPC socket.

The daemon must be running before this adapter is spawned.
If the socket is unavailable, all tool calls return an error — this is
correct behaviour: MCP without the daemon is meaningless.

Usage (in ~/.claude.json mcpServers config):
    "command": "/path/to/.venv/bin/python"
    "args": ["-m", "mnemostroma.integration.mcp_stdio_adapter"]
"""
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

logger = logging.getLogger("mnemostroma.mcp_adapter")

_MNEMO_DIR            = Path.home() / ".mnemostroma"
_SOCKET_PATH          = _MNEMO_DIR / "daemon.sock"
_PIPE_NAME            = r"\\.\pipe\mnemostroma"
_CURRENT_SESSION_FILE = _MNEMO_DIR / "current_session"

# ── Tool list (mirrors mcp_server.py — keep in sync when adding tools) ─

_TOOLS: list[Tool] = [
    Tool(
        name="ctx_semantic",
        description="Семантический поиск по памяти. Возвращает релевантные сессии.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_n": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="ctx_get",
        description="Получить сессию по ID.",
        inputSchema={
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    ),
    Tool(
        name="ctx_search",
        description="Поиск сессий по тегам.",
        inputSchema={
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "string"},
                "age": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["tags"],
        },
    ),
    Tool(
        name="ctx_full",
        description="Полный текст сессии из SQLite включая content_full.",
        inputSchema={
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    ),
    Tool(
        name="ctx_anchors",
        description="Якоря субсознательного слоя: решения, факты, персоны, события, дедлайны. type=deadline заменяет ctx_urgent.",
        inputSchema={
            "type": "object",
            "properties": {
                "anchor_type": {"type": "string"},
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="ctx_precision",
        description="Прецизионные артефакты: ссылки, формулы, цитаты, данные.",
        inputSchema={
            "type": "object",
            "properties": {
                "precision_type": {"type": "string"},
                "importance": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="content_search",
        description="Семантический поиск по контентной ветке.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project_id": {"type": "string"},
                "status": {"type": "string", "default": "active"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="content_get",
        description="Метаданные блока контента по ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "content_id": {"type": "string"},
                "version": {"type": "integer"},
            },
            "required": ["content_id"],
        },
    ),
    Tool(
        name="content_raw",
        description="Полный текст версии контента.",
        inputSchema={
            "type": "object",
            "properties": {
                "content_id": {"type": "string"},
                "version": {"type": "integer"},
            },
            "required": ["content_id"],
        },
    ),
    Tool(
        name="content_history",
        description="История всех версий контентного блока.",
        inputSchema={
            "type": "object",
            "properties": {"content_id": {"type": "string"}},
            "required": ["content_id"],
        },
    ),
    Tool(
        name="ctx_bridge",
        description="Структурированный пакет передачи контекста следующему агенту.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="ctx_recent",
        description="Вернуть сессии за последние N дней. by='created' — по дате создания, by='accessed' — по дате последнего обращения.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "number", "default": 7.0},
                "by": {"type": "string", "enum": ["created", "accessed"], "default": "created"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
]

# ── IPC client ────────────────────────────────────────────────────────

_msg_id = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


# ── Windows Named Pipe helper ─────────────────────────────────────────

if sys.platform == "win32":
    async def _open_pipe() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Открыть Named Pipe через ProactorEventLoop (Windows-only).

        ProactorEventLoop — дефолт на Windows начиная с Python 3.8.
        create_pipe_connection() — низкоуровневый API, аналог open_unix_connection.
        """
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        transport, _ = await loop.create_pipe_connection(
            lambda: protocol,
            _PIPE_NAME,
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer


async def _ipc_call(tool: str, args: dict) -> Any:
    """Send one request to the daemon IPC socket, return result or raise."""
    if sys.platform == "win32":
        try:
            reader, writer = await _open_pipe()
        except OSError as e:
            raise ConnectionError(
                f"Mnemostroma daemon not running (pipe unavailable): {e}\n"
                "Start with: mnemostroma start"
            ) from e
    else:
        try:
            reader, writer = await asyncio.open_unix_connection(str(_SOCKET_PATH))
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise ConnectionError(
                "Mnemostroma daemon not running. Start with: mnemostroma start"
            ) from e

    try:
        msg_id = _next_id()
        payload = json.dumps({"id": msg_id, "tool": tool, "args": args}, ensure_ascii=False)
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


# ── MCP Server ────────────────────────────────────────────────────────

app = Server("mnemostroma")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        result = await _ipc_call(name, arguments)
        if isinstance(result, (dict, list)):
            text = json.dumps(result, default=str, ensure_ascii=False)
        else:
            text = json.dumps({"result": result}, default=str, ensure_ascii=False)
        return [TextContent(type="text", text=text)]
    except ConnectionError as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception as exc:
        logger.error(f"Tool {name} failed: {exc}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Entry point ───────────────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    async with stdio_server() as (read_stream, write_stream):
        # Write current session_id for proxy_passthrough to pick up.
        # Hard deadline: 3s. If daemon is unresponsive, fall back to date-id
        # and proceed — app.run() must not be delayed by a hung daemon.
        try:
            result = await asyncio.wait_for(_ipc_call("ctx_active", {}), timeout=3.0)
            sid = (result or {}).get("session_id") or f"passthrough-{date.today().isoformat()}"
        except Exception:
            sid = f"passthrough-{date.today().isoformat()}"
        _CURRENT_SESSION_FILE.write_text(sid, encoding="utf-8")

        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
