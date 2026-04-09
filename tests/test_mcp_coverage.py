# SPDX-License-Identifier: FSL-1.1-MIT
"""Acceptance test: MCP tool set is exactly the expected 16 agent tools.

Daemon-only functions must never appear in list_tools().
This test acts as a guardrail against accidental re-addition.
"""
import pytest

from mnemostroma.integration.mcp_server import list_tools

EXPECTED_TOOLS = {
    # 🧠 Воспоминание (8)
    "ctx_full", "ctx_anchors", "ctx_precision", "ctx_bridge",
    "content_search", "content_get", "content_raw", "content_history",
    # 🔍 Навигация (5)
    "ctx_semantic", "ctx_get", "ctx_search", "ctx_load", "ctx_recent",
    # ⚙️ Сервисный агентский (4)
    "ctx_active", "ctx_expire", "ctx_urgent", "save_content",
}

DAEMON_ONLY = {
    "ctx_inject", "ctx_status", "ctx_growth", "ctx_pulse",
    "ctx_sync", "ctx_dump", "ctx_evict",
}


@pytest.mark.asyncio
async def test_list_tools_exact_set():
    """list_tools() must return exactly EXPECTED_TOOLS — no more, no less."""
    tools = await list_tools()
    names = {t.name for t in tools}
    extra   = names - EXPECTED_TOOLS
    missing = EXPECTED_TOOLS - names
    assert not extra,   f"Unexpected tools in MCP: {extra}"
    assert not missing, f"Expected tools missing from MCP: {missing}"


@pytest.mark.asyncio
async def test_daemon_only_absent():
    """Daemon-only functions must not be exposed as MCP tools."""
    tools = await list_tools()
    names = {t.name for t in tools}
    leaked = DAEMON_ONLY & names
    assert not leaked, f"Daemon-only tools leaked into MCP: {leaked}"


@pytest.mark.asyncio
async def test_tool_count():
    """Exact count guard — fails if anything is added/removed without updating EXPECTED_TOOLS."""
    tools = await list_tools()
    assert len(tools) == len(EXPECTED_TOOLS), (
        f"MCP tool count: expected {len(EXPECTED_TOOLS)}, got {len(tools)}"
    )


@pytest.mark.asyncio
async def test_all_tools_have_description():
    """Every tool must have a non-empty description."""
    tools = await list_tools()
    for t in tools:
        assert t.description and t.description.strip(), (
            f"Tool '{t.name}' has no description"
        )


@pytest.mark.asyncio
async def test_all_tools_have_input_schema():
    """Every tool must declare an inputSchema."""
    tools = await list_tools()
    for t in tools:
        assert t.inputSchema, f"Tool '{t.name}' has no inputSchema"
