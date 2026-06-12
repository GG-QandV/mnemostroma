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
from mcp.server.lowlevel import NotificationOptions
from mcp.types import TextContent, Tool

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

_orig_create_init = app.create_initialization_options
app.create_initialization_options = lambda *a, **kw: _orig_create_init(
    notification_options=NotificationOptions(tools_changed=True),
    experimental_capabilities=kw.get("experimental_capabilities", {}),
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Expose Mnemostroma memory tools to the agent."""
    return [
        Tool(
            name="ctx_help",
            description="Returns a brief markdown cheat sheet on when and how to use Mnemostroma memory tools. Call this if you are unsure which tool to use.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ctx_semantic",
            description="Semantic search in memory. Use this FIRST when you need to find past context, decisions, or code based on meaning or vague descriptions. (~20ms)",
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
            description=(
                "Search for sessions using exact tags (e.g., bug, docs) OR by exact time. "
                "Faster than semantic search. "
                "Combination guide: You can pass tags only, exact_time only, or both. "
                "For exact_time, use masks like '27/04/26 21:18:XX' (minute precision)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags to filter by. Pass [] if searching only by time."},
                    "exact_time": {"type": "string", "description": "Time string with optional X-mask, e.g. '27/04/26 21:18:XX'"},
                    "importance": {"type": "string", "description": "critical | important | background | principle"},
                    "age": {"type": "string", "description": "Filter by age signal"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": []
            }
        ),
        Tool(
            name="ctx_full",
            description="Get the complete session transcript from SQLite. Use this ONLY when you need the exact verbatim text, code snippets, or full history that was truncated in search results. Heavy call.",
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
            description="Retrieve subconscious layer anchors: decisions, deadlines, facts, or events. Use this when you need to check hard constraints, agreed decisions, or project deadlines. Fast RAM access.",
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
            description="Semantic search across the content branch (code, configs, docs). Use this to find specific project files or documentation blocks.",
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
            description="Generate a structured context bridge package. Use this BEFORE ending a session if work continues, a decision was made, or a blocker remains.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ctx_recent",
            description="Retrieve sessions from the last N days. Use this to catch up on what happened recently (e.g., 'what did I do yesterday?').",
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


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route MCP tool calls to Mnemostroma async functions.

    Each branch delegates to the corresponding function in tools/,
    injecting SystemContext automatically. The agent never touches ctx directly.
    """
    if _conductor is None or _conductor.ctx is None:
        return [TextContent(type="text", text='{"error": "Mnemostroma not initialized"}')]

    ctx = _conductor.ctx
    if ctx is not None and ctx.session_repo is None:
        try:
            from mnemostroma.adapters.sqlite.anchor_repo import AnchorRepo
            from mnemostroma.adapters.sqlite.precision_repo import PrecisionRepo
            from mnemostroma.adapters.sqlite.session_repo import SessionRepo
            if hasattr(ctx, 'persistence') and ctx.persistence is not None:
                ctx.session_repo = SessionRepo(ctx.persistence._manager)
                ctx.precision_repo = PrecisionRepo(ctx.persistence._manager)
                ctx.anchor_repo = AnchorRepo(ctx.persistence._manager)
                logger.info("Dynamically healed SessionRepo and PrecisionRepo inside MCP session")
        except Exception as e:
            logger.warning(f"Failed dynamic SessionRepo healing: {e}")

    try:
        if name == "ctx_help":
            help_text = (
                "## Mnemostroma Tools Guide\n\n"
                "| Tool | When to use |\n"
                "|---|---|\n"
                "| `ctx_semantic` | **DEFAULT.** Find past context by meaning/topic. Use this FIRST. (~20ms) |\n"
                "| `ctx_anchors` | Find explicit decisions, deadlines, or constraints. (<1ms) |\n"
                "| `ctx_search` | Find sessions by exact tags (e.g. 'bug', 'docs'). (<1ms) |\n"
                "| `ctx_full` | Retrieve the FULL verbatim text of a session. Heavy call, use only for exact code/quotes. |\n"
                "| `ctx_bridge` | Call this BEFORE ending your turn if work is unfinished or a decision was made. |\n"
                "| `content_search` | Find documentation or code snippets in the Content Branch. |\n"
                "| `ctx_recent` | See what happened in the last N days. |\n\n"
                "**MANDATORY RULE:** Never claim you don't have context without trying `ctx_semantic` first."
            )
            return [TextContent(type="text", text=json.dumps({"guide": help_text}, ensure_ascii=False))]

        elif name == "ctx_semantic":
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
                tags=arguments.get("tags", []),
                ctx=ctx,
                importance=arguments.get("importance"),
                age=arguments.get("age"),
                limit=arguments.get("limit", 10),
                exact_time=arguments.get("exact_time"),
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

    Path resolution order for data files:
        1. MNEMOSTROMA_DIR env var (set by IDE MCP config)
        2. ~/.mnemostroma (default install location)
        3. project root relative paths (legacy dev mode)
    """
    global _conductor

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    # Resolve data directory: prefer MNEMOSTROMA_DIR, fall back to ~/.mnemostroma,
    # then project-root-relative paths for dev/legacy mode.
    mnemo_dir_env = os.environ.get("MNEMOSTROMA_DIR", "")
    if mnemo_dir_env:
        mnemo_dir = Path(mnemo_dir_env).expanduser()
    else:
        mnemo_dir = Path.home() / ".mnemostroma"

    if mnemo_dir.exists():
        config_path = str(mnemo_dir / "config.json")
        db_path = str(mnemo_dir / "mnemostroma.db")
        model_dir = str(mnemo_dir / "models")
        logger.info("MCP server using MNEMOSTROMA_DIR: %s", mnemo_dir)
    else:
        # Legacy dev mode: CWD must be project root
        project_root = Path(__file__).resolve().parents[2]
        os.chdir(project_root)
        config_path = "config.json"
        db_path = "mnemostroma.db"
        model_dir = "models"
        logger.info("MCP server using legacy project-root mode: %s", project_root)

    _conductor = Conductor()
    try:
        logger.info("Bootstrapping Mnemostroma for MCP...")
        await _conductor.start(  # init DB, matrix search, models, workers
            config_path=config_path,
            db_path=db_path,
            model_dir=model_dir,
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
