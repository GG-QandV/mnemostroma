# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Literal

from mnemostroma.gateway.provider_url_policy import validate_provider_base_url


@dataclass(frozen=True)
class GatewayLimitsConfig:
    max_request_bytes: int = 8 * 1024 * 1024
    max_concurrent_streams: int = 16
    max_context_tokens: int = 600
    connect_timeout_sec: float = 10.0
    first_byte_timeout_sec: float = 60.0
    stream_idle_timeout_sec: float = 300.0


@dataclass(frozen=True)
class GatewayOutboxConfig:
    batch_size: int = 25
    max_attempts: int = 12
    retention_hours: int = 168


@dataclass(frozen=True)
class GatewayConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8780
    auth_mode: Literal["local_bearer", "none"] = "local_bearer"
    token_env: str = "MNEMO_GATEWAY_TOKEN"
    limits: GatewayLimitsConfig = field(default_factory=GatewayLimitsConfig)
    outbox: GatewayOutboxConfig = field(default_factory=GatewayOutboxConfig)
    profiles: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    memory_mode: Literal["off", "planned", "active"] = "off"
    memory_max_tokens: int = 600
    provider_mode: Literal["disabled", "configured"] = "disabled"
    provider_base_url: str | None = None
    provider_token_env: str | None = None
    provider_timeout_seconds: float = 30.0
    dispatch_mode: Literal["dry_run", "fake", "http"] = "dry_run"
    observation_mode: Literal["off", "active"] = "off"
    max_concurrent_dispatches: int = 8
    max_concurrent_memory_requests: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GatewayConfig:
        def _filter(c: type, d: dict[str, Any]) -> dict[str, Any]:
            sig = inspect.signature(c.__init__)
            return {k: v for k, v in d.items() if k in sig.parameters}

        limits = GatewayLimitsConfig(
            **_filter(GatewayLimitsConfig, data.get('limits', {}))
        )
        outbox = GatewayOutboxConfig(
            **_filter(GatewayOutboxConfig, data.get('outbox', {}))
        )
        top = _filter(cls, {k: v for k, v in data.items() if k not in ('limits', 'outbox')})
        top['limits'] = limits
        top['outbox'] = outbox
        url = top.get('provider_base_url')
        if isinstance(url, str):
            top['provider_base_url'] = validate_provider_base_url(url)
        return cls(**top)
