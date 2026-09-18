# SPDX-License-Identifier: FSL-1.1-MIT
"""Domain models for the scoped MITM/passthrough proxy (ADR-005).

Frozen dataclasses / StrEnum, consistent with ``gateway/models.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProxyCaptureMode(StrEnum):
    INTERCEPT = "intercept"      # MITM: расшифровка + inject + форвард
    PASSTHROUGH = "passthrough"  # прозрачный TCP-туннель, TLS не трогается


class UnmatchedHostAction(StrEnum):
    PASSTHROUGH = "passthrough"  # fail-open (рекомендуется для prod по умолчанию)
    REJECT = "reject"            # strict mode: явный HTTP 502, без сброса


@dataclass(frozen=True)
class ClientProfile:
    client_id: str
    match_hosts: tuple[str, ...]          # exact или "*.suffix" wildcard
    capture_mode: ProxyCaptureMode
    upstream_host: str | None = None      # None => host из CONNECT как есть
    inject_hook: str | None = None  # dotted path обработчика, только для INTERCEPT
    enabled: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        # Нормализация из строкового JSON-конфига; StrEnum бросает ValueError
        # на неизвестном значении.
        object.__setattr__(self, "capture_mode", ProxyCaptureMode(self.capture_mode))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientProfile:
        import inspect

        sig = inspect.signature(cls.__init__)
        kwargs = {k: v for k, v in data.items() if k in sig.parameters}
        if "match_hosts" in kwargs:
            kwargs["match_hosts"] = tuple(kwargs["match_hosts"])
        return cls(**kwargs)


@dataclass(frozen=True)
class MitmProxyConfig:
    host: str = "127.0.0.1"
    port: int = 8764
    clients: tuple[ClientProfile, ...] = field(default_factory=tuple)
    unmatched_host_action: UnmatchedHostAction = UnmatchedHostAction.PASSTHROUGH
    connect_timeout_sec: float = 10.0
    tunnel_idle_timeout_sec: float = 300.0
    max_concurrent_tunnels: int = 256
    log_unmatched_hosts: bool = True

    def __post_init__(self) -> None:
        # Нормализация из строкового JSON-конфига; StrEnum бросает ValueError
        # на неизвестном значении.
        object.__setattr__(
            self,
            "unmatched_host_action",
            UnmatchedHostAction(self.unmatched_host_action),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MitmProxyConfig:
        import inspect

        sig = inspect.signature(cls.__init__)
        clients_raw = data.get("clients", ())
        clients = tuple(
            c if isinstance(c, ClientProfile) else ClientProfile.from_dict(c)
            for c in clients_raw
        )
        kwargs = {
            k: v
            for k, v in data.items()
            if k != "clients" and k in sig.parameters
        }
        kwargs["clients"] = clients
        return cls(**kwargs)
