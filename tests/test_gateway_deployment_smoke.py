# SPDX-License-Identifier: FSL-1.1-MIT
"""R15 — deployment smoke test with real config, loopback stub and fake proxy."""
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
from mnemostroma.integration.gateway_memory import create_gateway_app

_GATEWAY_TOKEN = "sk-smoke-gw-token"
_PROVIDER_TOKEN = "sk-smoke-prov-token"
_COMPLETION_BODY = {
    "choices": [{"message": {"content": "smoke ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2},
}
_MEM_XML = "<memory><d>smoke</d></memory>"


# ── stub ─────────────────────────────────────────────────────────────


class FakeProxy:
    def __init__(self) -> None:
        self.inject_calls: list[str] = []
        self.observe_event = asyncio.Event()
        self.observe_user: str | None = None
        self.observe_asst: str | None = None

    async def inject(self, user_message: str, **kw: Any) -> Any:
        self.inject_calls.append(user_message)
        return _FakeBlock(_MEM_XML)

    async def observe(self, user_message: str, assistant_message: str) -> None:
        self.observe_user = user_message
        self.observe_asst = assistant_message
        self.observe_event.set()


class _FakeBlock:
    def __init__(self, context: str) -> None:
        self.context = context
        self.tools: list = []
        self.stats: dict = {}


class _StubState:
    def __init__(self) -> None:
        self.last_auth: str | None = None
        self.last_body: dict | None = None
        self.requests: list[dict] = []


def _make_stub(state: _StubState) -> Starlette:
    async def completions(request: Any) -> Response:
        body: dict = await request.json()
        state.last_body = body
        state.requests.append(body)
        state.last_auth = request.headers.get("authorization", "")
        return JSONResponse(_COMPLETION_BODY)

    return Starlette(
        routes=[Route("/chat/completions", completions, methods=["POST"])],
    )


# ── helpers ──────────────────────────────────────────────────────────


def _bind() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


def _config(**overrides: Any) -> GatewayConfig:
    base = {
        "auth_mode": "local_bearer",
        "token_env": "SMOKE_GW_TOKEN",
        "provider_mode": "configured",
        "dispatch_mode": "http",
        "provider_base_url": None,
        "provider_token_env": "SMOKE_PROV_TOKEN",
        "provider_timeout_seconds": 5.0,
        "memory_mode": "off",
        "observation_mode": "off",
    }
    base.update(overrides)
    return GatewayConfig(**base)


@pytest.fixture
def env() -> None:
    os.environ["SMOKE_GW_TOKEN"] = _GATEWAY_TOKEN
    os.environ["SMOKE_PROV_TOKEN"] = _PROVIDER_TOKEN
    yield
    os.environ.pop("SMOKE_GW_TOKEN", None)
    os.environ.pop("SMOKE_PROV_TOKEN", None)


async def _serve(app: Starlette) -> tuple[uvicorn.Server, int, socket.socket]:
    sock = _bind()
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    await asyncio.sleep(0.1)
    return server, port, sock, task


async def _post(
    port: int, body: dict[str, Any], token: str = _GATEWAY_TOKEN
) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )


# ══════════════════════════════════════════════════════════════════════
# Positive smoke
# ══════════════════════════════════════════════════════════════════════


class TestPositiveSmoke:
    @pytest.mark.asyncio
    async def test_valid_request_returns_normalized_completion(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}")
        app = create_gateway_app(config=cfg, proxy=FakeProxy())
        s2, p2, sk2, t2 = await _serve(app)

        try:
            resp = await _post(p2, {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
            assert resp.status_code == 200
            body = resp.json()
            assert body["id"].startswith("chatcmpl_mnemo_")
            assert body["object"] == "chat.completion"
            assert body["model"] == "gpt-4"
            assert body["choices"][0]["message"]["content"] == "smoke ok"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_stub_receives_provider_bearer_and_typed_payload(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}", memory_mode="active")
        proxy = FakeProxy()
        app = create_gateway_app(config=cfg, proxy=proxy)
        s2, p2, sk2, t2 = await _serve(app)

        try:
            await _post(p2, {"model": "gpt-4", "messages": [{"role": "user", "content": "mem test"}]})
            # Stub receives provider token, not gateway token
            assert stub_state.last_auth == f"Bearer {_PROVIDER_TOKEN}"
            assert _GATEWAY_TOKEN not in (stub_state.last_auth or "")
            # Payload is typed, non-streaming, includes memory system msg
            msgs = stub_state.last_body["messages"]
            roles = [m["role"] for m in msgs]
            assert roles == ["system", "user"]
            assert msgs[0]["content"] == _MEM_XML
            assert msgs[1]["content"] == "mem test"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_fake_proxy_injector_gets_final_user_content(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}", memory_mode="active")
        proxy = FakeProxy()
        app = create_gateway_app(config=cfg, proxy=proxy)
        s2, p2, sk2, t2 = await _serve(app)

        try:
            await _post(p2, {
                "model": "gpt-4",
                "messages": [
                    {"role": "system", "content": "be brief"},
                    {"role": "user", "content": "first q"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "user", "content": "final q"},
                ],
            })
            assert len(proxy.inject_calls) == 1
            assert proxy.inject_calls[0] == "final q"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_fake_proxy_observer_receives_user_and_assistant(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}", observation_mode="active")
        proxy = FakeProxy()
        app = create_gateway_app(config=cfg, proxy=proxy)
        s2, p2, sk2, t2 = await _serve(app)

        try:
            await _post(p2, {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "observe me"}],
            })
            await asyncio.wait_for(proxy.observe_event.wait(), timeout=3.0)
            assert proxy.observe_user == "observe me"
            assert proxy.observe_asst == "smoke ok"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_response_does_not_leak_provider_metadata(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}")
        app = create_gateway_app(config=cfg, proxy=FakeProxy())
        s2, p2, sk2, t2 = await _serve(app)

        try:
            resp = await _post(p2, {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
            text = resp.text.lower()
            assert "api.openai.com" not in text
            assert _PROVIDER_TOKEN.lower() not in text
            assert "SMOKE_PROV_TOKEN".lower() not in text
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()


# ══════════════════════════════════════════════════════════════════════
# Negative smoke
# ══════════════════════════════════════════════════════════════════════


class TestNegativeSmoke:
    @pytest.mark.asyncio
    async def test_deployment_smoke_missing_token_never_reaches_stub(self, env):
        stub_app = _make_stub(_StubState())
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}")
        os.environ.pop("SMOKE_PROV_TOKEN", None)  # remove token
        app = create_gateway_app(config=cfg, proxy=FakeProxy())
        s2, p2, sk2, t2 = await _serve(app)

        try:
            resp = await _post(p2, {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
            assert resp.status_code == 503
            assert resp.json()["error"]["code"] == "provider_credentials_unavailable"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()
            os.environ["SMOKE_PROV_TOKEN"] = _PROVIDER_TOKEN

    @pytest.mark.asyncio
    async def test_active_memory_without_proxy_returns_503(self, env):
        cfg = _config(memory_mode="active", provider_base_url="http://127.0.0.1:1")
        app = create_gateway_app(config=cfg)  # no proxy
        s2, p2, sk2, t2 = await _serve(app)

        try:
            resp = await _post(p2, {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
            assert resp.status_code == 503
            assert resp.json()["error"]["code"] == "memory_unavailable"
        finally:
            s2.should_exit = True
            await t2
            sk2.close()

    @pytest.mark.asyncio
    async def test_stream_true_returns_400_without_stub_call(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}")
        app = create_gateway_app(config=cfg, proxy=FakeProxy())
        s2, p2, sk2, t2 = await _serve(app)

        try:
            resp = await _post(p2, {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            })
            assert resp.status_code == 400
            assert resp.json()["error"]["code"] == "invalid_request"
            # Stub was never called
            assert stub_state.last_body is None
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_omits_memory_when_memory_mode_off(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}", memory_mode="off")
        proxy = FakeProxy()
        app = create_gateway_app(config=cfg, proxy=proxy)
        s2, p2, sk2, t2 = await _serve(app)

        try:
            await _post(p2, {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "no mem"}],
            })
            msgs = stub_state.last_body["messages"]
            assert len(msgs) == 1
            assert msgs[0]["role"] == "user"
            assert proxy.inject_calls == []  # injector never called
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()

    @pytest.mark.asyncio
    async def test_omits_observation_when_observation_mode_off(self, env):
        stub_state = _StubState()
        stub_app = _make_stub(stub_state)
        s1, p1, sk1, t1 = await _serve(stub_app)

        cfg = _config(provider_base_url=f"http://127.0.0.1:{p1}", observation_mode="off")
        proxy = FakeProxy()
        app = create_gateway_app(config=cfg, proxy=proxy)
        s2, p2, sk2, t2 = await _serve(app)

        try:
            await _post(p2, {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "no obs"}],
            })
            await asyncio.sleep(0.05)
            assert proxy.observe_user is None  # observer never called
        finally:
            s2.should_exit = True
            await t2
            sk2.close()
            s1.should_exit = True
            await t1
            sk1.close()
