# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import json
from pathlib import Path
from mnemostroma.integration.mcp_sse_adapter import _check_auth, handle_mcp_config, TOKEN

class MockRequest:
    def __init__(self, headers=None, query_params=None):
        self.headers = headers or {}
        self.query_params = query_params or {}

def test_check_auth_bearer_ok():
    req = MockRequest(headers={"Authorization": f"Bearer {TOKEN}"})
    assert _check_auth(req) is True

def test_check_auth_query_ok():
    req = MockRequest(query_params={"token": TOKEN})
    assert _check_auth(req) is True

def test_check_auth_bearer_wrong():
    req = MockRequest(headers={"Authorization": "Bearer wrong-token"})
    assert _check_auth(req) is False

def test_check_auth_query_wrong():
    req = MockRequest(query_params={"token": "wrong-token"})
    assert _check_auth(req) is False

def test_check_auth_empty():
    req = MockRequest()
    assert _check_auth(req) is False

@pytest.mark.asyncio
async def test_mcp_config_no_serveo(monkeypatch):
    monkeypatch.setattr("mnemostroma.integration.tunnel.state.get_tunnel_url", lambda: None)
    response = await handle_mcp_config(None)
    data = json.loads(response.body.decode("utf-8"))
    
    assert data["public_url"] is None
    assert f"token={TOKEN}" in data["local_url"]
    assert "127.0.0.1:8765" in data["local_url"]

@pytest.mark.asyncio
async def test_mcp_config_with_serveo(monkeypatch):
    monkeypatch.setattr("mnemostroma.integration.tunnel.state.get_tunnel_url", lambda: "https://xyz.serveo.net")
    
    response = await handle_mcp_config(None)
    data = json.loads(response.body.decode("utf-8"))
    
    assert data["public_url"] == f"https://xyz.serveo.net/sse?token={TOKEN}"
    assert f"token={TOKEN}" in data["local_url"]
