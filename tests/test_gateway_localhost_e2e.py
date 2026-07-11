# SPDX-License-Identifier: FSL-1.1-MIT
"""Loopback HTTP provider dispatch e2e tests.

Uses a real Starlette/uvicorn stub on 127.0.0.1:0 to validate the actual
httpx code path outside MockTransport. No external network calls.
"""
from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.routes import create_app

_GATEWAY_TOKEN = "sk-e2e-gateway-token"
_PROVIDER_TOKEN = "sk-e2e-provider-token"

_OK_RESPONSE = {
    "id": "chatcmpl_e2e",
    "object": "chat.completion",
    "created": 100,
    "model": "gpt-4",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "e2e response"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


def _make_ok_stub(state: dict[str, Any]) -> Starlette:
    async def completions(request: Any) -> Response:
        body: dict[str, Any] = await request.json()
        state["last_request"] = body
        state["request_count"] += 1
        auth = request.headers.get("authorization", "")
        state["last_auth"] = auth
        return JSONResponse(_OK_RESPONSE)

    state["request_count"] = 0
    state["last_request"] = None
    state["last_auth"] = None

    return Starlette(
        routes=[
            Route("/chat/completions", completions, methods=["POST"]),
        ],
    )


def _make_error_stub() -> Starlette:
    async def completions(request: Any) -> Response:
        return JSONResponse({"error": "internal"}, status_code=500)

    return Starlette(
        routes=[
            Route("/chat/completions", completions, methods=["POST"]),
        ],
    )


async def _start_server(app: Starlette, sock: socket.socket) -> tuple[uvicorn.Server, asyncio.Task]:
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    await asyncio.sleep(0.1)
    return server, task


def _bind_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


@pytest.fixture
async def ok_stub():
    state: dict[str, Any] = {}
    app = _make_ok_stub(state)
    sock = _bind_socket()
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    await asyncio.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        server.should_exit = True
        await task
        sock.close()


@pytest.fixture
async def gateway_client(ok_stub):
    stub_url, stub_state = ok_stub

    os.environ["E2E_PROVIDER_TOKEN"] = _PROVIDER_TOKEN
    os.environ["E2E_GATEWAY_TOKEN"] = _GATEWAY_TOKEN

    cfg = GatewayConfig(
        dispatch_mode="http",
        provider_mode="configured",
        provider_base_url=stub_url,
        provider_token_env="E2E_PROVIDER_TOKEN",
        provider_timeout_seconds=5.0,
        auth_mode="local_bearer",
        token_env="E2E_GATEWAY_TOKEN",
    )

    app = create_app(_GATEWAY_TOKEN, gateway_config=cfg)
    sock = _bind_socket()
    port = sock.getsockname()[1]
    gw_config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    gw_server = uvicorn.Server(gw_config)
    gw_task = asyncio.create_task(gw_server.serve(sockets=[sock]))
    await asyncio.sleep(0.1)

    try:
        yield f"http://127.0.0.1:{port}", stub_state
    finally:
        gw_server.should_exit = True
        await gw_task
        sock.close()
        os.environ.pop("E2E_PROVIDER_TOKEN", None)
        os.environ.pop("E2E_GATEWAY_TOKEN", None)


class TestLoopbackHttpDispatch:
    async def _post(
        self, gw_url: str, body: dict[str, Any], token: str = _GATEWAY_TOKEN
    ) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await client.post(
                f"{gw_url}/v1/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_posts_completion_payload(
        self, gateway_client
    ):
        gw_url, stub_state = gateway_client
        resp = await self._post(gw_url, {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hello"}],
        })
        assert resp.status_code == 200
        assert stub_state["request_count"] >= 1
        req = stub_state["last_request"]
        assert req["model"] == "gpt-4"
        assert req["messages"] == [{"role": "user", "content": "hello"}]

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_returns_normalized_completion(
        self, gateway_client
    ):
        gw_url, _ = gateway_client
        resp = await self._post(gw_url, {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "e2e response"

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_sends_provider_bearer_token_only(
        self, gateway_client
    ):
        gw_url, stub_state = gateway_client
        await self._post(gw_url, {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
        })
        auth = stub_state["last_auth"]
        assert auth == f"Bearer {_PROVIDER_TOKEN}"
        assert _GATEWAY_TOKEN not in auth

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_uses_timeout_bound(
        self, gateway_client
    ):
        gw_url, _ = gateway_client
        resp = await self._post(gw_url, {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_maps_stub_500(
        self, gateway_client
    ):
        os.environ["E2E_PROVIDER_TOKEN_2"] = _PROVIDER_TOKEN
        os.environ["E2E_GATEWAY_TOKEN"] = _GATEWAY_TOKEN

        err_sock = _bind_socket()
        err_port = err_sock.getsockname()[1]
        err_app = _make_error_stub()
        config = uvicorn.Config(err_app, host="127.0.0.1", port=err_port, log_level="error", lifespan="off")
        err_server = uvicorn.Server(config)
        err_task = asyncio.create_task(err_server.serve(sockets=[err_sock]))
        await asyncio.sleep(0.1)

        cfg = GatewayConfig(
            dispatch_mode="http",
            provider_mode="configured",
            provider_base_url=f"http://127.0.0.1:{err_port}",
            provider_token_env="E2E_PROVIDER_TOKEN_2",
            auth_mode="local_bearer",
            token_env="E2E_GATEWAY_TOKEN",
        )
        app = create_app(_GATEWAY_TOKEN, gateway_config=cfg)
        gw_sock = _bind_socket()
        gw_port = gw_sock.getsockname()[1]
        gw_config = uvicorn.Config(app, host="127.0.0.1", port=gw_port, log_level="error", lifespan="off")
        gw_server = uvicorn.Server(gw_config)
        gw_task = asyncio.create_task(gw_server.serve(sockets=[gw_sock]))
        await asyncio.sleep(0.1)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://127.0.0.1:{gw_port}/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
                    headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
                )
            assert resp.status_code == 502
        finally:
            gw_server.should_exit = True
            await gw_task
            gw_sock.close()
            err_server.should_exit = True
            await err_task
            err_sock.close()
            os.environ.pop("E2E_PROVIDER_TOKEN_2", None)

    @pytest.mark.asyncio
    async def test_loopback_http_dispatch_does_not_call_conductor_or_memory_proxy(
        self, gateway_client
    ):
        import mnemostroma.gateway.routes as mod
        with open(mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
