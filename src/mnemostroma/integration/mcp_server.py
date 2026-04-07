# SPDX-License-Identifier: FSL-1.1-MIT
"""MCP Server for Mnemostroma — stdio transport.

Provides external AI agents (Antigravity, etc.) with access to
Mnemostroma memory tools via the Model Context Protocol.

Architecture:
    Conductor.start() → SystemContext → tool handlers → JSON-RPC (stdio)

All tool handlers delegate to the existing async functions in tools/,
preserving the single-responsibility principle. No business logic lives here.

Expected latency: <50ms per tool call (excluding initial bootstrap).
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio

from mnemostroma.conductor import Conductor

logger = logging.getLogger("mnemostroma.mcp")

# Global conductor instance — initialized once on server start
_conductor: Conductor | None = None


def _serialize(obj: Any) -> str:
    """Safely serialize tool output to JSON string.

    Handles dataclass objects and non-serializable types by converting
    them to dicts/strings. Prevents MCP transport errors.
    """
    if obj is None:
        return json.dumps({"result": None})
    if isinstance(obj, (str, int, float, bool)):
        return json.dumps({"result": obj})
    if isinstance(obj, dict):
        return json.dumps(obj, default=str, ensure_ascii=False)
    if isinstance(obj, list):
        results = []
        for item in obj:
            if hasattr(item, '__dict__'):
                d = {k: v for k, v in item.__dict__.items()
                     if not k.startswith('_') and k != 'embedding'}
                results.append(d)
            else:
                results.append(item)
        return json.dumps(results, default=str, ensure_ascii=False)
    if hasattr(obj, '__dict__'):
        d = {k: v for k, v in obj.__dict__.items()
             if not k.startswith('_') and k != 'embedding'}
        return json.dumps(d, default=str, ensure_ascii=False)
    return json.dumps({"result": str(obj)})


# ── MCP Server Definition ────────────────────────────────────────────

app = Server("mnemostroma")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Expose Mnemostroma memory tools to the agent."""
    return [
        Tool(
            name="ctx_semantic",
            description="Семантический поиск по памяти. Возвращает релевантные сессии.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Тема для поиска в памяти"},
                    "top_k": {"type": "integer", "default": 20, "description": "Кандидаты для ранжирования"},
                    "top_n": {"type": "integer", "default": 5, "description": "Финальных результатов после rerank"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="ctx_get",
            description="Получить сессию по ID. Загружает из RAM или SQLite.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "ID сессии"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_active",
            description="Текущий активный контекст: intent, переменные, дедлайны.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ctx_search",
            description="Поиск сессий по тегам. Быстрее семантического, требует точного совпадения тегов.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Теги для фильтрации"},
                    "importance": {"type": "string", "description": "critical | important | background | principle"},
                    "age": {"type": "string", "description": "Фильтр по age_signal"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["tags"]
            }
        ),
        Tool(
            name="ctx_full",
            description="Полный текст сессии из SQLite включая content_full. Использовать только когда нужна точная цитата.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "ID сессии"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_anchors",
            description="Якоря субсознательного слоя: решения, факты, персоны, события. Быстрый RAM-доступ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "anchor_type": {"type": "string", "description": "decision | constraint | milestone | event | observation"},
                    "session_id": {"type": "string", "description": "Фильтр по сессии"},
                    "limit": {"type": "integer", "default": 20}
                }
            }
        ),
        Tool(
            name="ctx_precision",
            description="Прецизионные артефакты: ссылки, формулы, цитаты, данные. Хранятся дословно.",
            inputSchema={
                "type": "object",
                "properties": {
                    "precision_type": {"type": "string", "description": "link | concept | quote | formula | data"},
                    "importance": {"type": "string", "description": "Фильтр по важности"},
                    "limit": {"type": "integer", "default": 20}
                }
            }
        ),
        Tool(
            name="ctx_expire",
            description="Пометить срочную задачу как выполненную/истёкшую.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "ID сессии с дедлайном"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_urgent",
            description="Активные дедлайны и срочные задачи.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_ahead": {"type": "number", "default": 72.0}
                }
            }
        ),
        Tool(
            name="save_content",
            description="Сохранить блок контента (код, конфиг, текст) с версионированием.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id":   {"type": "string", "description": "Уникальный ID контента"},
                    "text":         {"type": "string", "description": "Текст контента"},
                    "content_type": {"type": "string", "description": "function | class | chapter | scene | config"},
                    "session_id":   {"type": "string", "description": "ID текущей сессии"},
                    "tags":         {"type": "array", "items": {"type": "string"}},
                    "why_changed":  {"type": "string", "description": "Причина изменения"}
                },
                "required": ["content_id", "text"]
            }
        ),
        Tool(
            name="content_search",
            description="Семантический поиск по контентной ветке (код, конфиги, тексты). Возвращает метаданные блоков.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Описание искомого контента"},
                    "project_id": {"type": "string", "description": "Фильтр по проекту"},
                    "status": {"type": "string", "default": "active", "description": "active | archived | all"},
                    "top_k": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="content_get",
            description="Метаданные блока контента по ID. version=null → последняя активная версия.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string"},
                    "version": {"type": "integer", "description": "Конкретная версия (опционально)"}
                },
                "required": ["content_id"]
            }
        ),
        Tool(
            name="content_raw",
            description="Полный текст версии контента. Дорогой вызов — только когда нужен точный текст.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string"},
                    "version": {"type": "integer"}
                },
                "required": ["content_id"]
            }
        ),
        Tool(
            name="content_history",
            description="История всех версий контентного блока включая отклонённые. Только метаданные.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string"}
                },
                "required": ["content_id"]
            }
        ),
        Tool(
            name="ctx_load",
            description="Загрузить архивную сессию из SQLite в RAM. Использовать когда ctx_get вернул null.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_bridge",
            description="Структурированный пакет передачи контекста следующему агенту: intent, решения, конфликты, дедлайны.",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route MCP tool calls to Mnemostroma async functions.

    Each branch delegates to the corresponding function in tools/,
    injecting SystemContext automatically. The agent never touches ctx directly.
    """
    if _conductor is None or _conductor.ctx is None:
        return [TextContent(type="text", text='{"error": "Mnemostroma not initialized"}')]

    ctx = _conductor.ctx

    try:
        if name == "ctx_semantic":
            from mnemostroma.tools.read import ctx_semantic
            results = await ctx_semantic(
                query=arguments["query"],
                ctx=ctx,
                top_n=arguments.get("top_n", 5)
            )
            return [TextContent(type="text", text=_serialize(results))]

        elif name == "ctx_get":
            from mnemostroma.tools.read import ctx_get
            result = await ctx_get(arguments["session_id"], ctx)
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_search":
            from mnemostroma.tools.read import ctx_search
            result = await ctx_search(
                tags=arguments["tags"],
                ctx=ctx,
                importance=arguments.get("importance"),
                age=arguments.get("age"),
                limit=arguments.get("limit", 10),
            )
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_full":
            from mnemostroma.tools.read import ctx_full
            result = await ctx_full(arguments["session_id"], ctx)
            if result is None:
                return [TextContent(type="text", text='{"error": "session not found"}')]
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_anchors":
            from mnemostroma.tools.read import ctx_anchors
            result = await ctx_anchors(
                ctx=ctx,
                anchor_type=arguments.get("anchor_type"),
                session_id=arguments.get("session_id"),
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_precision":
            from mnemostroma.tools.read import ctx_precision
            result = await ctx_precision(
                ctx=ctx,
                precision_type=arguments.get("precision_type"),
                importance=arguments.get("importance"),
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_expire":
            from mnemostroma.tools.write import ctx_expire
            await ctx_expire(arguments["session_id"], ctx)
            return [TextContent(type="text", text='{"result": "expired"}')]

        elif name == "ctx_active":
            from mnemostroma.tools.read import ctx_active
            result = await ctx_active(ctx)
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_urgent":
            from mnemostroma.tools.write import ctx_urgent
            result = await ctx_urgent(ctx, hours_ahead=arguments.get("hours_ahead", 72.0))
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "save_content":
            from mnemostroma.tools.write import save_content
            result = await save_content(
                content_id=arguments["content_id"],
                text=arguments["text"],
                ctx=ctx
            )
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "content_search":
            from mnemostroma.tools.content import content_search
            result = await content_search(
                query=arguments["query"],
                ctx=ctx,
                project_id=arguments.get("project_id"),
                status=arguments.get("status", "active"),
                top_k=arguments.get("top_k", 5),
            )
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "content_get":
            from mnemostroma.tools.content import content_get
            result = await content_get(
                content_id=arguments["content_id"],
                ctx=ctx,
                version=arguments.get("version"),
            )
            if result is None:
                return [TextContent(type="text", text='{"error": "content not found"}')]
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "content_raw":
            from mnemostroma.tools.content import content_raw
            result = await content_raw(
                content_id=arguments["content_id"],
                ctx=ctx,
                version=arguments.get("version"),
            )
            if result is None:
                return [TextContent(type="text", text='{"error": "content not found"}')]
            return [TextContent(type="text", text=json.dumps({"content": result}, ensure_ascii=False))]

        elif name == "content_history":
            from mnemostroma.tools.content import content_history
            result = await content_history(arguments["content_id"], ctx)
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_load":
            from mnemostroma.tools.admin import ctx_load
            result = await ctx_load(arguments["session_id"], ctx)
            if result is None:
                return [TextContent(type="text", text='{"error": "session not found in SQLite"}')]
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_bridge":
            from mnemostroma.tools.admin import ctx_bridge
            result = await ctx_bridge(ctx)
            return [TextContent(type="text", text=_serialize(result))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except KeyError as e:
        missing = str(e).strip("'\"")
        return [TextContent(type="text", text=json.dumps({
            "error": f"missing required argument: '{missing}'",
            "code": "missing_arg",
        }))]
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ── Entry Point ───────────────────────────────────────────────────────

async def main() -> None:
    """Bootstrap Mnemostroma and start MCP stdio server.

    Lifecycle:
        1. Conductor.start() — init DB, matrix search, models, workers
        2. stdio_server() — listen for JSON-RPC calls
        3. On exit — Conductor.stop() — flush and shutdown
    """
    global _conductor

    # Ensure CWD is the project root for config.json / models/ resolution
    project_root = Path(__file__).resolve().parents[3]
    os.chdir(project_root)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    _conductor = Conductor()
    try:
        logger.info("Bootstrapping Mnemostroma for MCP...")
        await _conductor.start(  # init DB, matrix search, models, workers
            config_path="config.json",
            db_path="mnemostroma.db",
            model_dir="models"
        )
        logger.info("Mnemostroma ready. Starting MCP stdio transport.")

        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    finally:
        if _conductor:
            await _conductor.stop()
            logger.info("Mnemostroma shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
