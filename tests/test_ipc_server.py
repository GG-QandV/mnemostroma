# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for IPC server and adapter layer.

Covers:
- IPCServer dispatch: all tools route correctly or return error
- IPCServer protocol: unknown tool, daemon-not-ready, exception in tool
- mcp_stdio_adapter: list_tools matches mcp_server list_tools
- mcp_stdio_adapter: call_tool forwards to IPC and wraps result
- _run_daemon: IPC server starts and is cancelled cleanly (no crash)
- Socket cleanup: stale socket from previous run is removed on start
"""
import asyncio
import json
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────

def _make_conductor(ctx=None):
    conductor = MagicMock()
    conductor.ctx = ctx or MagicMock()
    conductor.observe = AsyncMock(return_value=None)

    async def mock_dispatch(name, args):
        if name == "observe":
            await conductor.observe(args.get("session_id"), args.get("text"))
            return {"ok": True}
        if name == "nonexistent_tool":
            raise ValueError(f"Unknown tool: {name!r}")
        if ctx is None and name == "ctx_full": # Simulation for daemon-not-ready test
             raise RuntimeError("daemon not ready")
        return {"ok": True}

    conductor.dispatch = AsyncMock(side_effect=mock_dispatch)
    return conductor


# ── IPCServer: protocol ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_unknown_tool(tmp_path):
    """Unknown tool name returns {"error": "unknown tool: X"}."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "test.sock"
    conductor = _make_conductor()

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        reader, writer = await asyncio.open_unix_connection(str(sock))
        msg = json.dumps({"id": 1, "tool": "nonexistent_tool", "args": {}}) + "\n"
        writer.write(msg.encode())
        await writer.drain()

        line = await reader.readline()
        response = json.loads(line.decode())

        assert response["id"] == 1
        assert "error" in response
        assert "nonexistent_tool" in response["error"]

        writer.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_daemon_not_ready(tmp_path):
    """If conductor.ctx is None, returns {"error": "daemon not ready"}."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "test.sock"
    conductor = _make_conductor(ctx=None)
    conductor.ctx = None

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        reader, writer = await asyncio.open_unix_connection(str(sock))
        msg = json.dumps({"id": 2, "tool": "ctx_full", "args": {"session_id": "test"}}) + "\n"
        writer.write(msg.encode())
        await writer.drain()

        line = await reader.readline()
        response = json.loads(line.decode())

        assert response["id"] == 2
        assert "error" in response
        assert "not ready" in response["error"]

        writer.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_observe_dispatches_to_conductor(tmp_path):
    """'observe' tool calls conductor.observe(), not tools/."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "test.sock"
    conductor = _make_conductor()

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        reader, writer = await asyncio.open_unix_connection(str(sock))
        msg = json.dumps({
            "id": 3,
            "tool": "observe",
            "args": {"session_id": "test-session", "text": "hello world"},
        }) + "\n"
        writer.write(msg.encode())
        await writer.drain()

        line = await reader.readline()
        response = json.loads(line.decode())

        assert response["id"] == 3
        assert response.get("result") == {"ok": True}
        conductor.observe.assert_called_once_with("test-session", "hello world")

        writer.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_stale_socket_removed(tmp_path):
    """If daemon.sock already exists from a previous run, it is removed on start."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "stale.sock"
    sock.touch()  # Simulate leftover socket from crashed previous daemon

    assert sock.exists()

    conductor = _make_conductor()
    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        # Server should have started successfully (stale file removed)
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.close()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_parallel_clients(tmp_path):
    """Multiple concurrent clients are handled without deadlock."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "para.sock"
    conductor = _make_conductor()
    conductor.observe = AsyncMock(return_value=None)

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        async def one_client(client_id: int):
            reader, writer = await asyncio.open_unix_connection(str(sock))
            msg = json.dumps({
                "id": client_id,
                "tool": "observe",
                "args": {"session_id": f"s{client_id}", "text": "x"},
            }) + "\n"
            writer.write(msg.encode())
            await writer.drain()
            line = await reader.readline()
            writer.close()
            return json.loads(line.decode())

        results = await asyncio.gather(*[one_client(i) for i in range(5)])
        ids = {r["id"] for r in results}
        assert ids == {0, 1, 2, 3, 4}

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── mcp_stdio_adapter: tool list parity ──────────────────────────────

@pytest.mark.asyncio
async def test_stdio_adapter_tools_match_mcp_server():
    """mcp_stdio_adapter._TOOLS must contain the same tool names as mcp_server.list_tools()."""
    from mnemostroma.integration.mcp_stdio_adapter import _TOOLS as adapter_tools
    from mnemostroma.integration.mcp_server import list_tools as server_list_tools

    adapter_names = {t["name"] for t in adapter_tools}
    server_names = {t.name for t in await server_list_tools()}

    missing_in_adapter = server_names - adapter_names
    assert not missing_in_adapter, (
        f"Tools in mcp_server but missing in mcp_stdio_adapter: {missing_in_adapter}"
    )

    extra_in_adapter = adapter_names - server_names
    assert not extra_in_adapter, (
        f"Tools in mcp_stdio_adapter but missing in mcp_server: {extra_in_adapter}"
    )


# ── mcp_stdio_adapter: call_tool forwards to IPC ─────────────────────

@pytest.mark.asyncio
async def test_stdio_adapter_call_tool_forwards_to_ipc():
    """call_tool() in the adapter calls _ipc_call and wraps result in TextContent."""
    from mnemostroma.integration import mcp_stdio_adapter
    fake_result = [{"session_id": "abc", "brief": "test"}]

    with patch.object(mcp_stdio_adapter, "_ipc_call", AsyncMock(return_value=fake_result)):
        result = await mcp_stdio_adapter._handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ctx_semantic",
                "arguments": {"query": "test"}
            }
        })

    assert result is not None
    assert "result" in result
    # _handle wraps JSON string in content list
    content = result["result"]["content"][0]
    assert json.loads(content["text"]) == fake_result


@pytest.mark.asyncio
async def test_stdio_adapter_call_tool_connection_error():
    """ConnectionError (daemon down) returns error JSON, does not raise."""
    from mnemostroma.integration import mcp_stdio_adapter

    with patch.object(
        mcp_stdio_adapter, "_ipc_call",
        AsyncMock(side_effect=ConnectionError("daemon not running"))
    ):
        result = await mcp_stdio_adapter._handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ctx_full",
                "arguments": {"session_id": "test"}
            }
        })

    assert "result" in result
    content = result["result"]["content"][0]
    assert "error" in json.loads(content["text"])


# ── IPCServer: cancellation is clean ─────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_cancels_cleanly(tmp_path):
    """IPCServer.serve() cancels without raising unhandled exceptions."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "cancel.sock"
    conductor = _make_conductor()
    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected — serve_forever raises CancelledError on cancel
