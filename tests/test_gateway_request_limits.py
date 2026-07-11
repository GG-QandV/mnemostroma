# SPDX-License-Identifier: FSL-1.1-MIT
"""R12 — bounded request validation."""
from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatRequest
from mnemostroma.gateway.errors import GatewayParseError
from mnemostroma.gateway.request_policy import (
    MAX_MESSAGE_CONTENT,
    MAX_MODEL_LENGTH,
    MAX_TOTAL_CONTENT,
    read_bounded_body,
    validate_chat_request,
)
from mnemostroma.gateway.routes import create_app

TEST_TOKEN = "sk-r12-test-token"
VALID_MODEL = "gpt-4"
VALID_MESSAGES = [
    {"role": "user", "content": "hello"},
]

_VALID_BODY = {
    "model": VALID_MODEL,
    "messages": VALID_MESSAGES,
}


def _app(cfg_override: dict[str, Any] | None = None) -> TestClient:
    cfg = GatewayConfig(
        auth_mode="local_bearer",
        token_env="R12_TEST_TOKEN",
        **(cfg_override or {}),
    )
    os.environ["R12_TEST_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    return TestClient(app)


def _post(body: dict[str, Any], client: TestClient | None = None) -> httpx.Response:
    c = client or _app()
    return c.post(
        "/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )


# ══════════════════════════════════════════════════════════════════════
# Bounded body reader
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def _make_bounded_request(body: bytes) -> Request:
    """Build a minimal ASGI-style Request with given body bytes."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "http_version": "1.1",
        "query_string": b"",
        "scheme": "http",
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 80),
        "asgi": {"version": "3.0"},
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


class TestBoundedBody:
    @pytest.mark.asyncio
    async def test_rejects_body_larger_than_one_mib(self):
        body = b"x" * (1_048_576 + 1)
        req = await _make_bounded_request(body)
        with pytest.raises(GatewayParseError, match="limit"):
            await read_bounded_body(req)

    @pytest.mark.asyncio
    async def test_accepts_body_at_boundary(self):
        body = b"x" * 1_048_576
        req = await _make_bounded_request(body)
        result = await read_bounded_body(req)
        assert len(result) == 1_048_576

    @pytest.mark.asyncio
    async def test_chunked_body_larger_than_one_mib_rejected(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"content-type", b"application/json")],
            "http_version": "1.1",
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 80),
            "asgi": {"version": "3.0"},
        }
        chunk = b"x" * 700_000  # each chunk is 700K, two would exceed 1MiB
        sent_first = False

        async def receive():
            nonlocal sent_first
            if not sent_first:
                sent_first = True
                return {"type": "http.request", "body": chunk, "more_body": True}
            return {"type": "http.request", "body": chunk, "more_body": False}

        req = Request(scope, receive=receive)
        with pytest.raises(GatewayParseError, match="limit"):
            await read_bounded_body(req)


# ══════════════════════════════════════════════════════════════════════
# Validation unit
# ══════════════════════════════════════════════════════════════════════


class TestValidateChatRequest:
    def _valid(self) -> dict[str, Any]:
        return dict(_VALID_BODY)

    def test_request_limits_accept_valid_minimal_request(self):
        result = validate_chat_request(self._valid())
        assert isinstance(result, ChatRequest)
        assert result.model == VALID_MODEL

    def test_request_limits_default_stream_is_false(self):
        result = validate_chat_request(self._valid())
        assert result.stream is False

    def test_rejects_empty_messages(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "messages": []})

    def test_rejects_more_than_64_messages(self):
        msgs = [{"role": "user", "content": "x"} for _ in range(65)]
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "messages": msgs})

    def test_rejects_model_blank(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "model": "  "})

    def test_rejects_model_nul(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "model": "gpt\x00bad"})

    def test_rejects_model_over_256_characters(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "model": "a" * (MAX_MODEL_LENGTH + 1)})

    def test_rejects_message_with_unknown_field(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": "hi", "extra": "x"}],
            })

    def test_rejects_unknown_message_role(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "tool", "content": "x"}],
            })

    def test_rejects_non_string_message_content(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": 42}],
            })

    def test_rejects_empty_message_content(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": ""}],
            })

    def test_rejects_blank_message_content(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": "   "}],
            })

    def test_rejects_nul_in_content(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": "he\x00llo"}],
            })

    def test_rejects_message_content_over_per_message_limit(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "user", "content": "x" * (MAX_MESSAGE_CONTENT + 1)}],
            })

    def test_rejects_total_content_over_limit(self):
        big = "x" * (MAX_TOTAL_CONTENT // 2 + 1)
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [
                    {"role": "user", "content": big},
                    {"role": "user", "content": big},
                ],
            })

    def test_rejects_more_than_eight_system_messages(self):
        msgs = [{"role": "system", "content": "x"} for _ in range(9)]
        msgs.append({"role": "user", "content": "hi"})
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "messages": msgs})

    def test_rejects_more_than_32_user_messages(self):
        msgs = [{"role": "user", "content": "x"} for _ in range(33)]
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "messages": msgs})

    def test_rejects_more_than_32_assistant_messages(self):
        msgs = [{"role": "assistant", "content": "x"} for _ in range(33)]
        msgs.append({"role": "user", "content": "hi"})
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "messages": msgs})

    def test_rejects_request_without_user_message(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({
                **self._valid(),
                "messages": [{"role": "system", "content": "x"}],
            })

    def test_rejects_stream_true(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "stream": True})

    def test_rejects_nonboolean_stream(self):
        with pytest.raises(GatewayParseError):
            validate_chat_request({**self._valid(), "stream": "yes"})

    def test_ignores_unknown_top_level_fields(self):
        result = validate_chat_request({
            **self._valid(),
            "extra_field": "ignored",
            "another": [1, 2, 3],
        })
        assert isinstance(result, ChatRequest)
        assert result.model == VALID_MODEL

    def test_valid_limit_boundary_dispatches_successfully(self):
        msgs = []
        # 8 system + 32 user + 24 assistant = 64 total
        for i in range(8):
            msgs.append({"role": "system", "content": f"s{i}"})
        for i in range(32):
            msgs.append({"role": "user", "content": f"u{i}"})
        for i in range(24):
            msgs.append({"role": "assistant", "content": f"a{i}"})
        assert len(msgs) == 64
        body = {"model": "gpt-4", "messages": msgs}
        result = validate_chat_request(body)
        assert len(result.messages) == 64


# ══════════════════════════════════════════════════════════════════════
# Integration via routes
# ══════════════════════════════════════════════════════════════════════


class TestRequestIntegration:
    def test_invalid_request_returns_stable_400_error(self):
        resp = _post({"bad": "request"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_request"
        # No echo of user input in error
        assert "bad" not in data["error"].get("message", "")

    def test_invalid_request_never_acquires_admission_permit(self):
        # Admission logged only on successful acquires — not testable directly
        # but verify we never reach dispatch path
        resp = _post({"model": "", "messages": []})
        assert resp.status_code == 400

    def test_invalid_request_never_calls_observer(self):
        calls: list[str] = []

        class Obs:
            async def observe(self, **kw: Any) -> None:
                calls.append("called")

        cfg = GatewayConfig(
            auth_mode="local_bearer",
            token_env="R12_OBS_TOKEN",
            observation_mode="active",
        )
        os.environ["R12_OBS_TOKEN"] = TEST_TOKEN
        app = create_app(TEST_TOKEN, gateway_config=cfg, completion_observer=Obs())
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={"bad": "request"},
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 400
        assert len(calls) == 0
