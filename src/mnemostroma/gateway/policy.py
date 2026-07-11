# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import re
from typing import Any

from mnemostroma.gateway.admission_policy import validate_admission_config
from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import (
    GatewayConfigError,
    GatewayProfileError,
    GatewayReservedPortError,
)
from mnemostroma.gateway.provider_policy import validate_provider_config

_RESERVED_PORTS: frozenset[int] = frozenset({8762, 8765, 8766, 8767, 8768})

_LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1",
    "::1",
    "localhost",
})

_ENV_VAR_RE: re.Pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CREDENTIAL_KEYS: frozenset[str] = frozenset({
    "api_key",
    "authorization",
    "token",
    "secret",
    "password",
})

_HARD_CAP_TOKENS: int = 4096


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS


def _check_credential_keys(obj: Any, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f"{path}.{k}" if path else k
            if k in _CREDENTIAL_KEYS:
                issues.append(f"{child}: key '{k}' is disallowed")
            issues.extend(_check_credential_keys(v, child))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            issues.extend(_check_credential_keys(item, f"{path}[{i}]"))
    return issues


def validate_gateway_config(config: GatewayConfig) -> None:
    if not isinstance(config.port, int) or not (1 <= config.port <= 65535):
        raise GatewayConfigError(
            f"gateway.port must be in 1–65535, got {config.port}"
        )

    if not _is_loopback(config.host):
        raise GatewayConfigError(
            f"R1 gateway.host must be loopback (127.0.0.1, ::1, localhost), "
            f"got {config.host!r}"
        )

    if config.auth_mode not in ("local_bearer", "none"):
        raise GatewayConfigError(
            f"gateway.auth_mode must be 'local_bearer' or 'none', "
            f"got {config.auth_mode!r}"
        )

    if config.memory_mode not in ("off", "planned", "active"):
        raise GatewayConfigError(
            f"gateway.memory_mode must be 'off', 'planned', or 'active', "
            f"got {config.memory_mode!r}"
        )

    if config.memory_max_tokens is not None and (
        not isinstance(config.memory_max_tokens, int) or config.memory_max_tokens <= 0
    ):
        raise GatewayConfigError(
            f"gateway.memory_max_tokens must be a positive integer, "
            f"got {config.memory_max_tokens!r}"
        )

    max_tok = config.memory_max_tokens
    if max_tok is not None and max_tok > _HARD_CAP_TOKENS:
        raise GatewayConfigError(
            f"gateway.memory_max_tokens ({config.memory_max_tokens}) "
            f"exceeds hard cap of {_HARD_CAP_TOKENS}"
        )

    if config.port in _RESERVED_PORTS:
        raise GatewayReservedPortError(
            f"gateway.port {config.port} is reserved for another transport "
            f"(reserved: {sorted(_RESERVED_PORTS)})"
        )

    limits = config.limits
    for field_name, val in [
        ("max_request_bytes", limits.max_request_bytes),
        ("max_concurrent_streams", limits.max_concurrent_streams),
        ("max_context_tokens", limits.max_context_tokens),
        ("connect_timeout_sec", limits.connect_timeout_sec),
        ("first_byte_timeout_sec", limits.first_byte_timeout_sec),
        ("stream_idle_timeout_sec", limits.stream_idle_timeout_sec),
    ]:
        if not isinstance(val, (int, float)) or val <= 0:
            raise GatewayConfigError(
                f"gateway.limits.{field_name} must be positive, got {val}"
            )

    if limits.max_context_tokens > _HARD_CAP_TOKENS:
        raise GatewayConfigError(
            f"gateway.limits.max_context_tokens ({limits.max_context_tokens}) "
            f"exceeds hard cap of {_HARD_CAP_TOKENS}"
        )

    if not _ENV_VAR_RE.match(config.token_env):
        raise GatewayConfigError(
            f"gateway.token_env {config.token_env!r} is not a valid "
            f"environment variable name"
        )

    credential_issues = _check_credential_keys(config.providers)
    if credential_issues:
        raise GatewayProfileError(
            "providers config contains disallowed credential keys:\n"
            + "\n".join(credential_issues)
        )

    credential_issues = _check_credential_keys(config.profiles)
    if credential_issues:
        raise GatewayProfileError(
            "profiles config contains disallowed credential keys:\n"
            + "\n".join(credential_issues)
        )

    if config.observation_mode not in ("off", "active"):
        raise GatewayConfigError(
            f"gateway.observation_mode must be 'off' or 'active', "
            f"got {config.observation_mode!r}"
        )

    validate_provider_config(config)

    validate_admission_config(config)
