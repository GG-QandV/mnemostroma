# SPDX-License-Identifier: FSL-1.1-MIT
"""Routing coverage tests for MCP call_tool().

Verifies that:
- Every tool in list_tools() has a routing branch in call_tool()
- Unknown tool returns {"error": "Unknown tool: X"}
- Missing required arg returns {"error": ..., "code": "missing_arg"}
- Uninitialised conductor returns {"error": "Mnemostroma not initialized"}
"""
import json
import re
import inspect
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from mnemostroma.integration import mcp_server
from mnemostroma.integration.mcp_server import list_tools, call_tool


# ── Static routing audit ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_listed_tool_is_routed():
    """Every tool declared in list_tools() must have a branch in call_tool()."""
    tools = await list_tools()
    listed = {t.name for t in tools}

    source = inspect.getsource(mcp_server.call_tool)
    routed = set(re.findall(r'name == ["\']([a-z_]+)["\']', source))

    missing = listed - routed
    assert not missing, (
        f"Tools in list_tools() but missing routing branch in call_tool(): {missing}"
    )


@pytest.mark.asyncio
async def test_no_phantom_routes():
    """No routing branch should handle a tool that isn't declared in list_tools()."""
    tools = await list_tools()
    listed = {t.name for t in tools}

    source = inspect.getsource(mcp_server.call_tool)
    routed = set(re.findall(r'name == ["\']([a-z_]+)["\']', source))

    phantom = routed - listed
    assert not phantom, (
        f"Routing branches without matching list_tools() entry: {phantom}"
    )


# ── Runtime error paths ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    ctx = MagicMock()
    conductor = MagicMock()
    conductor.ctx = ctx

    with patch.object(mcp_server, "_conductor", conductor):
        result = await call_tool("no_such_tool", {})

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "no_such_tool" in payload["error"]


@pytest.mark.asyncio
async def test_missing_required_arg_returns_code():
    ctx = MagicMock()
    conductor = MagicMock()
    conductor.ctx = ctx

    with patch.object(mcp_server, "_conductor", conductor):
        # ctx_semantic requires "query" — pass empty dict
        result = await call_tool("ctx_semantic", {})

    payload = json.loads(result[0].text)
    assert payload.get("code") == "missing_arg"
    assert "query" in payload["error"]


@pytest.mark.asyncio
async def test_uninitialised_conductor_returns_error():
    with patch.object(mcp_server, "_conductor", None):
        result = await call_tool("ctx_semantic", {"query": "test"})

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "not initialized" in payload["error"].lower()
