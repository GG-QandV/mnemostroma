# SPDX-License-Identifier: FSL-1.1-MIT
"""R18 — provider URL egress policy."""
from __future__ import annotations

import os

import httpx
import pytest

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayConfigError
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.provider import ProviderRequest
from mnemostroma.gateway.provider_errors import ProviderTransportError
from mnemostroma.gateway.provider_url_policy import validate_provider_base_url

_COMPLETION_OK = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
}


# ══════════════════════════════════════════════════════════════════════
# Unit — accept
# ══════════════════════════════════════════════════════════════════════


class TestAccept:
    def test_accepts_https_hostname_base_url(self):
        result = validate_provider_base_url("https://api.openai.com/v1")
        assert "api.openai.com" in result

    def test_accepts_https_ip_literal_base_url(self):
        result = validate_provider_base_url("https://1.2.3.4/v1")
        assert "1.2.3.4" in result

    def test_accepts_https_base_path_with_trailing_slash(self):
        result = validate_provider_base_url("https://api.openai.com/v1/")
        assert result == "https://api.openai.com/v1"

    def test_accepts_http_ipv4_loopback_only(self):
        result = validate_provider_base_url("http://127.0.0.1:8781")
        assert "127.0.0.1" in result

    def test_accepts_http_localhost_only(self):
        result = validate_provider_base_url("http://localhost:8781")
        assert "localhost" in result

    def test_accepts_http_ipv6_loopback_only(self):
        result = validate_provider_base_url("http://[::1]:8781")
        assert "::1" in result or "8781" in result

    def test_normalizes_single_trailing_slash(self):
        result = validate_provider_base_url("https://api.openai.com/v1/")
        assert result.rstrip("/") == result  # no trailing slash

    def test_transport_posts_to_exact_normalized_completion_endpoint(self):
        os.environ["R18_TEST_KEY"] = "sk-test"
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=_COMPLETION_OK)

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R18_TEST_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        import asyncio
        asyncio.run(transport.send(ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))))
        assert str(requests[0].url) == "https://api.openai.com/v1/chat/completions"
        os.environ.pop("R18_TEST_KEY", None)


# ══════════════════════════════════════════════════════════════════════
# Unit — reject
# ══════════════════════════════════════════════════════════════════════


class TestReject:
    def _assert_invalid(self, url: str) -> None:
        with pytest.raises(GatewayConfigError):
            validate_provider_base_url(url)

    def test_rejects_empty_relative_or_malformed_url(self):
        self._assert_invalid("")
        self._assert_invalid("   ")
        self._assert_invalid("relative/path")
        self._assert_invalid("://missing-scheme")

    def test_rejects_non_https_non_loopback_http(self):
        self._assert_invalid("http://example.com")
        self._assert_invalid("http://192.168.1.1")
        self._assert_invalid("http://10.0.0.1")

    def test_rejects_unknown_scheme(self):
        self._assert_invalid("file:///tmp/socket")
        self._assert_invalid("unix:///tmp/socket")
        self._assert_invalid("ftp://provider.example")

    def test_rejects_userinfo_query_fragment_and_control_characters(self):
        self._assert_invalid("https://user:pass@api.openai.com/v1")
        self._assert_invalid("https://api.openai.com/v1?key=value")
        self._assert_invalid("https://api.openai.com/v1#frag")
        self._assert_invalid("https://api.openai.com/v1\x00\x1f")

    def test_rejects_invalid_port(self):
        self._assert_invalid("https://api.openai.com:0")
        self._assert_invalid("https://api.openai.com:65536")


# ══════════════════════════════════════════════════════════════════════
# Config integration
# ══════════════════════════════════════════════════════════════════════


class TestConfigIntegration:
    def test_config_validation_does_not_read_provider_token_for_invalid_url(self):
        os.environ["R18_CFG_TOKEN"] = "should-not-be-read"
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="not-a-valid-url",
            provider_token_env="R18_CFG_TOKEN",
        )
        with pytest.raises(GatewayConfigError):
            validate_gateway_config(cfg)
        os.environ.pop("R18_CFG_TOKEN", None)

    def test_invalid_url_never_creates_http_client_or_dispatches(self):
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="http://evil.example.com",
            provider_token_env="R18_CFG_TOKEN2",
        )
        with pytest.raises(GatewayConfigError):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Redirect policy
# ══════════════════════════════════════════════════════════════════════


class TestRedirect:
    @pytest.mark.asyncio
    async def test_transport_does_not_follow_redirect(self):
        os.environ["R18_REDIR_KEY"] = "sk-test"

        async def redirect_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example.com/chat/completions"},
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R18_REDIR_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)),
        )
        with pytest.raises(ProviderTransportError) as exc:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        assert exc.value.code == "provider_invalid_response"
        os.environ.pop("R18_REDIR_KEY", None)

    @pytest.mark.asyncio
    async def test_redirect_maps_to_stable_error_without_second_request(self):
        call_count: list[int] = []

        async def counting_handler(request: httpx.Request) -> httpx.Response:
            call_count.append(1)
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example.com/chat/completions"},
            )

        os.environ["R18_CNT_KEY"] = "sk-test"
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R18_CNT_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(counting_handler)),
        )
        with pytest.raises(ProviderTransportError):
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        assert len(call_count) == 1
        os.environ.pop("R18_CNT_KEY", None)


# ══════════════════════════════════════════════════════════════════════
# Privacy
# ══════════════════════════════════════════════════════════════════════


class TestPrivacy:
    @pytest.mark.asyncio
    async def test_url_policy_never_exposes_provider_url_in_public_error(self):
        os.environ["R18_PRV_KEY"] = "sk-test"
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R18_PRV_KEY",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(500)),
            ),
        )
        with pytest.raises(ProviderTransportError) as exc:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        assert "api.openai.com" not in exc.value.message
        assert "openai" not in exc.value.message.lower()
        os.environ.pop("R18_PRV_KEY", None)

    @pytest.mark.asyncio
    async def test_url_policy_never_records_provider_hostname_in_metrics(self):
        from mnemostroma.gateway.metrics import GatewayMetrics
        m = GatewayMetrics()
        # Url policy validation errors do not reach metrics at all
        with pytest.raises(GatewayConfigError):
            validate_provider_base_url("http://private.lan")
        snap = m.snapshot()
        text = repr(snap)
        assert "private" not in text.lower()
        assert "lan" not in text.lower()
