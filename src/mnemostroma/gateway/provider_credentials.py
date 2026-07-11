# SPDX-License-Identifier: FSL-1.1-MIT
"""Provider credential resolution — minimal, isolated, and testable."""
from __future__ import annotations

import os
from typing import Protocol

from mnemostroma.gateway.provider_errors import ProviderTransportError


class ProviderCredentialResolver(Protocol):
    def resolve(self, env_name: str) -> str: ...


class ProviderCredentialError(ProviderTransportError):
    """Raised when credentials are unavailable, invalid, or malformed."""

    def __init__(self) -> None:
        super().__init__(
            503, "provider_credentials_unavailable",
            "credentials are unavailable",
        )


class EnvironmentCredentialResolver:
    def resolve(self, env_name: str) -> str:
        raw = os.environ.get(env_name)
        if raw is None or not raw:
            raise ProviderCredentialError()
        stripped = raw.strip()
        if not stripped or stripped != raw:
            raise ProviderCredentialError()
        for ch in raw:
            if ord(ch) < 0x20 or ch in "\x7f":
                raise ProviderCredentialError()
        return raw
