# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import hmac
import os

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError


def resolve_token(config: GatewayConfig) -> str:
    if config.auth_mode == "none":
        raise GatewayStartupError(
            "auth_mode='none' is not allowed at runtime"
        )
    token = os.environ.get(config.token_env)
    if not token:
        raise GatewayStartupError(
            f"token env {config.token_env!r} is empty or not set"
        )
    return token


def verify_token(token: str, expected: str) -> bool:
    return hmac.compare_digest(token, expected)
