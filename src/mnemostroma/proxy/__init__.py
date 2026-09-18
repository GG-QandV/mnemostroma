# SPDX-License-Identifier: FSL-1.1-MIT
"""Scoped MITM/passthrough proxy (ADR-005): client registry + selective interception.
"""

from mnemostroma.proxy.models import (
    ClientProfile,
    MitmProxyConfig,
    ProxyCaptureMode,
    UnmatchedHostAction,
)
from mnemostroma.proxy.registry import resolve_client
from mnemostroma.proxy.validation import (
    MitmProxyConfigError,
    MitmProxyCredentialLeakError,
    MitmProxyHostCollisionError,
    MitmProxyReservedPortError,
    validate_mitm_proxy_config,
)

__all__ = [
    "ClientProfile",
    "MitmProxyConfig",
    "MitmProxyConfigError",
    "MitmProxyCredentialLeakError",
    "MitmProxyHostCollisionError",
    "MitmProxyReservedPortError",
    "ProxyCaptureMode",
    "UnmatchedHostAction",
    "resolve_client",
    "validate_mitm_proxy_config",
]
