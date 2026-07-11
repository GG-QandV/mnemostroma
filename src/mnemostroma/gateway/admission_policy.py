# SPDX-License-Identifier: FSL-1.1-MIT
"""Admission control config validation."""
from __future__ import annotations

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayConfigError


def validate_admission_config(config: GatewayConfig) -> None:
    d = config.max_concurrent_dispatches
    if not isinstance(d, int) or d < 1 or d > 64:
        raise GatewayConfigError(
            f"gateway.max_concurrent_dispatches must be 1–64, got {d!r}"
        )
    m = config.max_concurrent_memory_requests
    if not isinstance(m, int) or m < 1 or m > d:
        raise GatewayConfigError(
            f"gateway.max_concurrent_memory_requests must be 1–"
            f"{config.max_concurrent_dispatches}, got {m!r}"
        )
