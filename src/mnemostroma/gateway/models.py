# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FailureMode(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class MemoryMode(StrEnum):
    OFF = "off"
    READ_ONLY = "read_only"
    FULL = "full"


class CaptureMode(StrEnum):
    GATEWAY = "gateway"
    LEGACY_PROXY = "legacy_proxy"
    MITM = "mitm"
    EXTENSION = "extension"
    MCP_ONLY = "mcp_only"


@dataclass(frozen=True)
class GatewayProfile:
    name: str
    failure_mode: FailureMode = FailureMode.CLOSED
    memory_mode: MemoryMode = MemoryMode.OFF
    capture_mode: CaptureMode = CaptureMode.MCP_ONLY
    allowed_providers: tuple[str, ...] = ()
    rate_limit_rps: float = 10.0
    tags: dict[str, str] = field(default_factory=dict)
