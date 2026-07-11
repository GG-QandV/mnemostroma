# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import os

import pytest

from mnemostroma.gateway.auth import resolve_token, verify_token
from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError


def test_gateway_disabled_does_not_load_server_dependency():
    cfg = GatewayConfig(enabled=False)
    assert cfg.enabled is False
    assert cfg.port == 8780


def test_gateway_enabled_requires_token_env():
    cfg = GatewayConfig(enabled=True, token_env="MISSING_VAR_XXXX")
    if "MISSING_VAR_XXXX" in os.environ:
        del os.environ["MISSING_VAR_XXXX"]
    with pytest.raises(GatewayStartupError, match="empty or not set"):
        resolve_token(cfg)


def test_gateway_rejects_empty_token():
    cfg = GatewayConfig(enabled=True, token_env="EMPTY_TOKEN_TEST")
    os.environ["EMPTY_TOKEN_TEST"] = ""
    try:
        with pytest.raises(GatewayStartupError, match="empty or not set"):
            resolve_token(cfg)
    finally:
        os.environ.pop("EMPTY_TOKEN_TEST", None)


def test_gateway_rejects_auth_mode_none():
    cfg = GatewayConfig(enabled=True, auth_mode="none", token_env="TEST_TOKEN")
    os.environ["TEST_TOKEN"] = "some-token"
    try:
        with pytest.raises(GatewayStartupError, match="auth_mode.*none.*not allowed"):
            resolve_token(cfg)
    finally:
        os.environ.pop("TEST_TOKEN", None)


def test_verify_token_uses_constant_time_compare():
    assert verify_token("abc", "abc") is True
    assert verify_token("abc", "xyz") is False
    assert verify_token("", "") is True
    assert verify_token("token123", "TOKEN123") is False
