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
            description="Semantic search in memory. Returns relevant sessions based on meaning.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or topic"},
                    "top_k": {"type": "integer", "default": 20, "description": "Number of candidates for initial ranking"},
                    "top_n": {"type": "integer", "default": 5, "description": "Number of final results after reranking"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="ctx_get",
            description="Retrieve a specific session by its ID. Loads from RAM or SQLite.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Unique session identifier"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_search",
            description="Search for sessions using tags. Faster than semantic search, requires exact tag matches.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags to filter by"},
                    "importance": {"type": "string", "description": "critical | important | background | principle"},
                    "age": {"type": "string", "description": "Filter by age signal"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["tags"]
            }
        ),
        Tool(
            name="ctx_full",
            description="Get the complete session transcript including full content from SQLite. Use only when exact wording is required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Unique session identifier"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="ctx_anchors",
            description="Retrieve subconscious layer anchors: decisions, facts, people, events, or deadlines. Fast RAM access. type=deadline replaces ctx_urgent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "anchor_type": {"type": "string", "description": "decision | constraint | milestone | event | observation | deadline"},
                    "session_id": {"type": "string", "description": "Filter by specific session ID"},
                    "limit": {"type": "integer", "default": 20}
                }
            }
        ),
        Tool(
            name="ctx_precision",
            description="Retrieve high-precision artifacts: links, formulas, quotes, or specific data points. Stored verbatim.",
            inputSchema={
                "type": "object",
                "properties": {
                    "precision_type": {"type": "string", "description": "link | concept | quote | formula | data"},
                    "importance": {"type": "string", "description": "Filter by importance"},
                    "limit": {"type": "integer", "default": 20}
                }
            }
        ),
        Tool(
            name="content_search",
            description="Semantic search across the content branch (code, configs, docs). Returns block metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or topic"},
                    "project_id": {"type": "string", "description": "Filter by project identifier"},
                    "status": {"type": "string", "default": "active", "description": "active | archived | all"},
                    "top_k": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        ),
        # DISABLED content_get — API minimization 2026-04-28
        # Tool(
        #     name="content_get",
        #     description="Retrieve metadata for a specific content block by ID. version=null returns the latest active version.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "content_id": {"type": "string"},
        #             "version": {"type": "integer", "description": "Specific version number (optional)"}
        #         },
        #         "required": ["content_id"]
        #     }
        # ),
        Tool(
            name="content_raw",
            description="Retrieve the full raw text of a content version. High latency call — use only when exact text is needed.",
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
            description="Retrieve the history of all versions for a content block, including rejected ones. Returns metadata only.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_id": {"type": "string"}
                },
                "required": ["content_id"]
            }
        ),
        Tool(
            name="ctx_bridge",
            description="Generate a structured context bridge package for handoff to the next agent (intent, decisions, conflicts, deadlines).",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ctx_recent",
            description="Retrieve sessions from the last N days. by='created' (creation date) or by='accessed' (last access date).",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "number", "default": 7.0},
                    "by": {"type": "string", "enum": ["created", "accessed"], "default": "created"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        # Tool(
        #     name="ctx_active",
        #     description="Summary of current active context: goals, variables, deadlines, conflicts.",
        #     inputSchema={"type": "object", "properties": {}}
        # ),
        # Tool(
        #     name="ctx_urgent",
        #     description="Urgent tasks and deadlines for the near future.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "hours_ahead": {"type": "number", "default": 72.0}
        #         }
        #     }
        # ),
        # Tool(
        #     name="ctx_expire",
        #     description="Mark a session's urgency status as expired.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "session_id": {"type": "string", "description": "Session ID"}
        #         },
        #         "required": ["session_id"]
        #     }
        # ),
        # Tool(
        #     name="ctx_load",
        #     description="Lazy load a session from cold storage into the RAM index.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "session_id": {"type": "string", "description": "Session ID"}
        #         },
        #         "required": ["session_id"]
        #     }
        # ),
        # Tool(
        #     name="save_content",
        #     description="Save a new version of a content block (code, text, data).",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "content_id": {"type": "string"},
        #             "text": {"type": "string", "description": "Full content text"},
        #             "why_changed": {"type": "string", "description": "Reason for change"}
        #         },
        #         "required": ["content_id", "text"]
        #     }
        # ),
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

        # DISABLED ctx_active — replaced by ConductorProxy XML injection
        # DISABLED ctx_urgent — merged into ctx_anchors(type="deadline")
        # DISABLED ctx_expire — API minimization 2026-04-10
        # DISABLED ctx_load   — internal only
        # DISABLED save_content — API minimization 2026-04-10

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

        # DISABLED content_get 2026-04-28
        # elif name == "X_content_get":
        #     from mnemostroma.tools.content import content_get
        #     result = await content_get(
        #         content_id=arguments["content_id"],
        #         ctx=ctx,
        #         version=arguments.get("version"),
        #     )
        #     if result is None:
        #         return [TextContent(type="text", text='{"error": "content not found"}')]
        #     return [TextContent(type="text", text=_serialize(result))]

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

        elif name == "ctx_bridge":
            from mnemostroma.tools.admin import ctx_bridge
            result = await ctx_bridge(ctx)
            return [TextContent(type="text", text=_serialize(result))]

        elif name == "ctx_recent":
            from mnemostroma.tools.read import ctx_recent
            result = await ctx_recent(
                ctx=ctx,
                days=arguments.get("days", 7.0),
                by=arguments.get("by", "created"),
                limit=arguments.get("limit", 20),
            )
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

    # parents[2]: mcp_server.py → integration/ → mnemostroma/ → project_root/
    project_root = Path(__file__).resolve().parents[2]
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
