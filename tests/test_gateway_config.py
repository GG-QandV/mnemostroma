# SPDX-License-Identifier: FSL-1.1-MIT
"""
Тесты Gateway R1 configuration schema и валидации.
Запуск: pytest tests/test_gateway_config.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from mnemostroma.gateway.config import (
    GatewayConfig,
    GatewayLimitsConfig,
    GatewayOutboxConfig,
)
from mnemostroma.gateway.errors import GatewayConfigError, GatewayProfileError
from mnemostroma.gateway.policy import validate_gateway_config

# ══════════════════════════════════════════════════════════════════════
# Defaults
# ══════════════════════════════════════════════════════════════════════


class TestGatewayDefaults:
    def test_gateway_disabled_by_default(self):
        cfg = GatewayConfig()
        assert cfg.enabled is False
        assert cfg.port == 8780
        assert cfg.host == "127.0.0.1"
        assert cfg.auth_mode == "local_bearer"
        assert cfg.token_env == "MNEMO_GATEWAY_TOKEN"

    def test_limits_defaults(self):
        cfg = GatewayLimitsConfig()
        assert cfg.max_request_bytes == 8 * 1024 * 1024
        assert cfg.max_concurrent_streams == 16
        assert cfg.max_context_tokens == 600

    def test_outbox_defaults(self):
        cfg = GatewayOutboxConfig()
        assert cfg.batch_size == 25
        assert cfg.max_attempts == 12
        assert cfg.retention_hours == 168

    def test_gateway_defaults_disabled(self):
        cfg = _load_config({})
        assert cfg.gateway is not None
        assert cfg.gateway.enabled is False


# ══════════════════════════════════════════════════════════════════════
# Loading
# ══════════════════════════════════════════════════════════════════════


class TestGatewayLoading:
    def test_gateway_explicit_config_loads(self):
        data = {
            "gateway": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 8780,
                "auth_mode": "local_bearer",
                "token_env": "MY_GATEWAY_TOKEN",
                "limits": {
                    "max_request_bytes": 4194304,
                    "max_concurrent_streams": 8,
                    "max_context_tokens": 512,
                    "connect_timeout_sec": 5.0,
                    "first_byte_timeout_sec": 30.0,
                    "stream_idle_timeout_sec": 150.0,
                },
                "outbox": {
                    "batch_size": 10,
                    "max_attempts": 5,
                    "retention_hours": 72,
                },
            }
        }
        cfg = _load_config(data)
        assert cfg.gateway is not None
        assert cfg.gateway.enabled is True
        assert cfg.gateway.port == 8780
        assert cfg.gateway.limits.max_request_bytes == 4194304
        assert cfg.gateway.outbox.batch_size == 10

    def test_legacy_config_remains_loadable(self):
        cfg = _load_config_without_gateway()
        assert cfg.gateway is None
        assert cfg.resources.session_window_size == 200


# ══════════════════════════════════════════════════════════════════════
# Port validation
# ══════════════════════════════════════════════════════════════════════


class TestPortValidation:
    @pytest.mark.parametrize("bad_port", [8762, 8765, 8766, 8767, 8768])
    def test_gateway_rejects_reserved_ports(self, bad_port):
        cfg = GatewayConfig(port=bad_port)
        with pytest.raises(GatewayConfigError, match="reserved"):
            validate_gateway_config(cfg)

    def test_gateway_accepts_free_port(self):
        cfg = GatewayConfig(port=8780)
        validate_gateway_config(cfg)

    def test_gateway_rejects_port_zero(self):
        cfg = GatewayConfig(port=0)
        with pytest.raises(GatewayConfigError, match="1–65535"):
            validate_gateway_config(cfg)

    def test_gateway_rejects_port_negative(self):
        cfg = GatewayConfig(port=-1)
        with pytest.raises(GatewayConfigError, match="1–65535"):
            validate_gateway_config(cfg)

    def test_gateway_rejects_port_out_of_range(self):
        cfg = GatewayConfig(port=70000)
        with pytest.raises(GatewayConfigError, match="1–65535"):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Host validation
# ══════════════════════════════════════════════════════════════════════


class TestHostValidation:
    @pytest.mark.parametrize("bad_host", ["0.0.0.0", "192.168.1.1", "10.0.0.1", "example.com", "*"])
    def test_gateway_rejects_non_loopback_host(self, bad_host):
        cfg = GatewayConfig(host=bad_host)
        with pytest.raises(GatewayConfigError, match="loopback"):
            validate_gateway_config(cfg)

    @pytest.mark.parametrize("good_host", ["127.0.0.1", "::1", "localhost"])
    def test_gateway_accepts_loopback_host(self, good_host):
        cfg = GatewayConfig(host=good_host)
        validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Auth validation
# ══════════════════════════════════════════════════════════════════════


class TestAuthValidation:
    def test_gateway_auth_required_on_loopback_default(self):
        cfg = GatewayConfig()
        assert cfg.auth_mode == "local_bearer"
        validate_gateway_config(cfg)

    def test_gateway_rejects_invalid_auth_mode(self):
        cfg = GatewayConfig(auth_mode="basic")
        with pytest.raises(GatewayConfigError, match="auth_mode"):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Memory config validation
# ══════════════════════════════════════════════════════════════════════


class TestMemoryConfig:
    def test_memory_mode_defaults_to_off(self):
        cfg = GatewayConfig()
        assert cfg.memory_mode == "off"

    def test_memory_mode_accepts_planned(self):
        cfg = GatewayConfig(memory_mode="planned")
        assert cfg.memory_mode == "planned"

    def test_memory_mode_rejects_unknown_value(self):
        cfg = GatewayConfig(memory_mode="on")
        with pytest.raises(GatewayConfigError, match="memory_mode"):
            validate_gateway_config(cfg)

    def test_memory_max_tokens_requires_positive_integer(self):
        cfg = GatewayConfig(memory_mode="planned", memory_max_tokens=0)
        with pytest.raises(GatewayConfigError, match="positive"):
            validate_gateway_config(cfg)

    def test_memory_max_tokens_rejects_over_hard_cap(self):
        cfg = GatewayConfig(memory_mode="planned", memory_max_tokens=5000)
        with pytest.raises(GatewayConfigError, match="hard cap"):
            validate_gateway_config(cfg)

    def test_memory_max_tokens_default(self):
        cfg = GatewayConfig()
        assert cfg.memory_max_tokens == 600


# ══════════════════════════════════════════════════════════════════════
# Provider config validation
# ══════════════════════════════════════════════════════════════════════


class TestProviderConfig:
    def test_provider_mode_defaults_disabled(self):
        cfg = GatewayConfig()
        assert cfg.provider_mode == "disabled"

    def test_provider_configured_requires_base_url(self):
        cfg = GatewayConfig(provider_mode="configured")
        with pytest.raises(GatewayConfigError, match="provider_base_url"):
            validate_gateway_config(cfg)

    def test_provider_configured_requires_token_env(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
        )
        with pytest.raises(GatewayConfigError, match="provider_token_env"):
            validate_gateway_config(cfg)

    def test_provider_token_env_name_is_validated(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="invalid!",
        )
        with pytest.raises(GatewayConfigError, match="provider_token_env"):
            validate_gateway_config(cfg)

    def test_provider_token_env_accepts_valid_name(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_API_KEY",
        )
        validate_gateway_config(cfg)

    def test_provider_base_url_accepts_https(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        validate_gateway_config(cfg)

    def test_provider_base_url_accepts_loopback_http(self):
        for url in ["http://127.0.0.1:8080", "http://localhost:8765", "http://[::1]:8080"]:
            cfg = GatewayConfig(
                provider_mode="configured",
                provider_base_url=url,
                provider_token_env="OPENAI_KEY",
            )
            validate_gateway_config(cfg)

    def test_provider_base_url_rejects_remote_http(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="http://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        with pytest.raises(GatewayConfigError, match="provider_base_url is invalid"):
            validate_gateway_config(cfg)

    def test_provider_base_url_rejects_userinfo_query_fragment(self):
        for bad in [
            "https://token@api.openai.com/v1",
            "https://api.openai.com/v1?key=val",
            "https://api.openai.com/v1#frag",
        ]:
            cfg = GatewayConfig(
                provider_mode="configured",
                provider_base_url=bad,
                provider_token_env="OPENAI_KEY",
            )
            with pytest.raises(GatewayConfigError):
                validate_gateway_config(cfg)

    def test_provider_base_url_normalizes_trailing_slash(self):
        cfg = GatewayConfig.from_dict({
            "provider_mode": "configured",
            "provider_base_url": "https://api.openai.com/v1/",
            "provider_token_env": "OPENAI_KEY",
        })
        validate_gateway_config(cfg)
        assert cfg.provider_base_url == "https://api.openai.com/v1"

    def test_provider_timeout_requires_finite_positive_bounded_value(self):
        for bad in [0, -1, 0.5, 121, 200]:
            cfg = GatewayConfig(
                provider_mode="configured",
                provider_base_url="https://api.openai.com/v1",
                provider_token_env="OPENAI_KEY",
                provider_timeout_seconds=bad,
            )
            with pytest.raises(GatewayConfigError, match="timeout"):
                validate_gateway_config(cfg)

    def test_provider_timeout_accepts_valid_range(self):
        for val in [1, 30, 120, 5.5]:
            cfg = GatewayConfig(
                provider_mode="configured",
                provider_base_url="https://api.openai.com/v1",
                provider_token_env="OPENAI_KEY",
                provider_timeout_seconds=val,
            )
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Limits validation
# ══════════════════════════════════════════════════════════════════════


class TestLimitsValidation:
    @pytest.mark.parametrize("field,val", [
        ("max_request_bytes", 0),
        ("max_concurrent_streams", -1),
        ("max_context_tokens", 0),
        ("connect_timeout_sec", 0.0),
        ("first_byte_timeout_sec", -5.0),
        ("stream_idle_timeout_sec", -0.1),
    ])
    def test_gateway_rejects_invalid_limits(self, field, val):
        kwargs = {field: val}
        limits = GatewayLimitsConfig(**kwargs)
        cfg = GatewayConfig(limits=limits)
        with pytest.raises(GatewayConfigError, match="positive"):
            validate_gateway_config(cfg)

    def test_gateway_rejects_excessive_token_budget(self):
        limits = GatewayLimitsConfig(max_context_tokens=5000)
        cfg = GatewayConfig(limits=limits)
        with pytest.raises(GatewayConfigError, match="hard cap"):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Token env validation
# ══════════════════════════════════════════════════════════════════════


class TestTokenEnvValidation:
    @pytest.mark.parametrize("bad_name", ["", "123abc", "with-dashes", "with spaces"])
    def test_gateway_rejects_invalid_token_env(self, bad_name):
        cfg = GatewayConfig(token_env=bad_name)
        with pytest.raises(GatewayConfigError, match="environment variable"):
            validate_gateway_config(cfg)

    def test_gateway_accepts_valid_token_env(self):
        cfg = GatewayConfig(token_env="MNEMO_GATEWAY_TOKEN")
        validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Credential key prohibition
# ══════════════════════════════════════════════════════════════════════


class TestCredentialProhibition:
    @pytest.mark.parametrize("bad_key", ["api_key", "authorization", "token", "secret", "password"])
    def test_gateway_rejects_literal_secrets_in_providers(self, bad_key):
        cfg = GatewayConfig(providers={"anthropic": {bad_key: "sk-xxx"}})
        with pytest.raises(GatewayProfileError, match="disallowed"):
            validate_gateway_config(cfg)

    def test_gateway_rejects_nested_secrets(self):
        cfg = GatewayConfig(profiles={"default": {"auth": {"api_key": "sk-xxx"}}})
        with pytest.raises(GatewayProfileError, match="disallowed"):
            validate_gateway_config(cfg)

    def test_gateway_allows_safe_provider_config(self):
        cfg = GatewayConfig(
            providers={"anthropic": {"model": "claude-4", "max_tokens": 4096}}
        )
        validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Profile immutability
# ══════════════════════════════════════════════════════════════════════


class TestProfileImmutability:
    def test_gateway_profile_is_immutable(self):
        from dataclasses import FrozenInstanceError

        from mnemostroma.gateway.models import FailureMode, GatewayProfile, MemoryMode
        p = GatewayProfile(name="test")
        assert p.failure_mode == FailureMode.CLOSED
        assert p.memory_mode == MemoryMode.OFF
        with pytest.raises(FrozenInstanceError):
            p.name = "changed"  # type: ignore[reportGeneralTypeIssues]


# ══════════════════════════════════════════════════════════════════════
# Default config file loading
# ══════════════════════════════════════════════════════════════════════


class TestDefaultConfig:
    def test_default_config_loads(self):
        cfg_path = Path(__file__).parent.parent / "src" / "mnemostroma" / "config_default.json"
        from mnemostroma.config import Config
        cfg = Config.load(cfg_path)
        assert cfg.gateway is not None
        assert cfg.gateway.enabled is False
        assert cfg.gateway.port == 8780
        assert cfg.gateway.limits.max_request_bytes == 8 * 1024 * 1024
        assert cfg.gateway.outbox.retention_hours == 168


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _load_config(data: dict) -> object:
    """Minimal Config loader that uses config_default.json as base."""
    from mnemostroma.config import Config

    cfg_path = Path(__file__).parent.parent / "src" / "mnemostroma" / "config_default.json"
    with open(cfg_path) as f:
        base = json.load(f)

    def _deep_merge(base: dict, overlay: dict) -> dict:
        result = dict(base)
        for k, v in overlay.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = {**result[k], **v}
            else:
                result[k] = v
        return result

    merged = _deep_merge(base, data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(merged, f)
        tmp = f.name
    try:
        return Config.load(tmp)
    finally:
        os.unlink(tmp)


def _load_config_without_gateway() -> object:
    """Load config_default.json with gateway section stripped."""
    from mnemostroma.config import Config

    cfg_path = Path(__file__).parent.parent / "src" / "mnemostroma" / "config_default.json"
    with open(cfg_path) as f:
        data = json.load(f)
    data.pop("gateway", None)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = f.name
    try:
        return Config.load(tmp)
    finally:
        os.unlink(tmp)
    """Minimal Config loader that uses config_default.json as base."""
    from mnemostroma.config import Config

    cfg_path = Path(__file__).parent.parent / "src" / "mnemostroma" / "config_default.json"
    with open(cfg_path) as f:
        base = json.load(f)

    def _deep_merge(base: dict, overlay: dict) -> dict:
        result = dict(base)
        for k, v in overlay.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = {**result[k], **v}
            else:
                result[k] = v
        return result

    merged = _deep_merge(base, data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(merged, f)
        tmp = f.name
    try:
        return Config.load(tmp)
    finally:
        os.unlink(tmp)
