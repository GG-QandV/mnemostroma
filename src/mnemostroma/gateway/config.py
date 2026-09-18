# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Literal

from mnemostroma.gateway.errors import GatewayConfigError
from mnemostroma.gateway.models import GatewayProfile
from mnemostroma.gateway.provider_url_policy import (
    validate_allowed_host,
    validate_provider_base_url,
)


@dataclass(frozen=True)
class GatewayLimitsConfig:
    max_request_bytes: int = 8 * 1024 * 1024
    max_concurrent_streams: int = 16
    max_context_tokens: int = 600
    connect_timeout_sec: float = 10.0
    first_byte_timeout_sec: float = 60.0
    stream_idle_timeout_sec: float = 300.0
    max_system_text_bytes: int = 50 * 1024
    sanitize_control_chars: bool = True
    sanitize_policy: Literal["strip", "pass", "error"] = "strip"
    max_model_len: int = 128
    max_messages: int = 1000
    expose_upstream_errors: bool = False
    sanitize_warn_on_hit: bool = True


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
    providers: dict[str, GatewayProfile] = field(default_factory=dict)
    strict_startup: bool = False
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
            **_filter(GatewayLimitsConfig, data.get("limits", {}))
        )
        outbox = GatewayOutboxConfig(
            **_filter(GatewayOutboxConfig, data.get("outbox", {}))
        )

        providers: dict[str, GatewayProfile] = {}
        for provider_id, raw_profile in data.get("providers", {}).items():
            if "/" in provider_id:
                raise GatewayConfigError(f"provider_id must not contain '/': {provider_id}")
            if isinstance(raw_profile, GatewayProfile):
                providers[provider_id] = raw_profile
                continue
            profile_kwargs = _filter(GatewayProfile, dict(raw_profile))
            for tuple_field in ("exposed_models", "allowed_hosts"):
                if tuple_field in profile_kwargs:
                    profile_kwargs[tuple_field] = tuple(profile_kwargs[tuple_field])
            profile_kwargs.setdefault("provider_id", provider_id)
            if "api_key_env" in profile_kwargs:
                profile_kwargs["credential_env"] = profile_kwargs.pop("api_key_env")

            if "base_url" in profile_kwargs:
                try:
                    validated = validate_provider_base_url(profile_kwargs["base_url"])
                    validate_allowed_host(
                        validated, profile_kwargs.get("allowed_hosts", ())
                    )
                except GatewayConfigError:
                    raise GatewayConfigError(
                        f"providers.{provider_id}.base_url is invalid"
                    )
                profile_kwargs["base_url"] = validated

            profile = GatewayProfile(**profile_kwargs)
            providers[provider_id] = profile

        top = _filter(
            cls,
            {k: v for k, v in data.items() if k not in ("limits", "outbox", "providers")},
        )
        top["limits"] = limits
        top["outbox"] = outbox
        top["providers"] = providers

        url = top.get("provider_base_url")
        if isinstance(url, str):
            top["provider_base_url"] = validate_provider_base_url(url)

        return cls(**top)
