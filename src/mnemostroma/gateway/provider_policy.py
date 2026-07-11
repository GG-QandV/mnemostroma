# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import re

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayConfigError
from mnemostroma.gateway.provider_url_policy import validate_provider_base_url

_PROVIDER_TOKEN_ENV_RE: re.Pattern = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_MIN_TIMEOUT: float = 1.0
_MAX_TIMEOUT: float = 120.0


def validate_provider_config(config: GatewayConfig) -> None:
    if config.dispatch_mode not in ("dry_run", "fake", "http"):
        raise GatewayConfigError(
            f"gateway.dispatch_mode must be 'dry_run', 'fake', or 'http', "
            f"got {config.dispatch_mode!r}"
        )

    if config.provider_mode not in ("disabled", "configured"):
        raise GatewayConfigError(
            f"gateway.provider_mode must be 'disabled' or 'configured', "
            f"got {config.provider_mode!r}"
        )

    if config.dispatch_mode in ("fake", "http") and config.provider_mode != "configured":
        raise GatewayConfigError(
            f"gateway.dispatch_mode={config.dispatch_mode!r} requires "
            "provider_mode='configured'"
        )

    if config.provider_mode == "disabled":
        return

    if not config.provider_base_url:
        raise GatewayConfigError(
            "gateway.provider_base_url is required when "
            "provider_mode='configured'"
        )

    validate_provider_base_url(config.provider_base_url)

    if not config.provider_token_env:
        raise GatewayConfigError(
            "gateway.provider_token_env is required when "
            "provider_mode='configured'"
        )

    if not _PROVIDER_TOKEN_ENV_RE.match(config.provider_token_env):
        raise GatewayConfigError(
            f"gateway.provider_token_env {config.provider_token_env!r} "
            f"is not a valid environment variable name"
        )

    timeout = config.provider_timeout_seconds
    if not isinstance(timeout, (int, float)):
        cond = True
    else:
        cond = timeout < _MIN_TIMEOUT or timeout > _MAX_TIMEOUT
    if cond:
        raise GatewayConfigError(
            f"gateway.provider_timeout_seconds must be between "
            f"{_MIN_TIMEOUT} and {_MAX_TIMEOUT}, got {timeout}"
        )
