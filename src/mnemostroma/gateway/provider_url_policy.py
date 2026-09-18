# SPDX-License-Identifier: FSL-1.1-MIT
"""Strict provider egress URL validation.

Rejects non-HTTPS (except loopback), userinfo, query, fragment,
control characters, empty hosts, malformed URLs, and relative paths.
No URL is echoed in error messages.
"""
from __future__ import annotations

from urllib.parse import urlparse

from mnemostroma.gateway.errors import GatewayConfigError

_LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1",
    "::1",
    "localhost",
})

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https", "http"})


def _raise() -> None:
    raise GatewayConfigError("gateway.provider_base_url is invalid")


def validate_provider_base_url(value: str) -> str:
    """Validate and normalize *value*.

    Returns the URL with a single trailing slash removed (safe for
    ``{base_url}/chat/completions`` concatenation).

    Raises ``GatewayConfigError`` on any violation — the error message
    never contains the input URL.
    """
    stripped = value.strip()
    if not stripped:
        _raise()

    for ch in stripped:
        if ord(ch) < 0x20 or ch in "\x7f":
            _raise()

    parsed = urlparse(stripped)

    if not parsed.scheme or parsed.scheme not in _ALLOWED_SCHEMES:
        _raise()

    if parsed.username or parsed.password:
        _raise()
    if parsed.query:
        _raise()
    if parsed.fragment:
        _raise()

    host = parsed.hostname or ""
    if not host:
        _raise()

    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        _raise()

    try:
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            _raise()
    except ValueError:
        _raise()

    path = parsed.path.rstrip("/")

    return f"{parsed.scheme}://{host}{':' + str(parsed.port) if parsed.port else ''}{path}"


def validate_allowed_host(base_url: str, allowed_hosts: tuple[str, ...]) -> None:
    """Verify that *base_url*'s hostname is present in *allowed_hosts*.

    Called AFTER validate_provider_base_url() has already normalized
    and validated the URL structure — this function only enforces the
    per-provider allowlist barrier described in ADR-005 / Gateway spec
    v1.0 (SSRF egress control).

    Empty *allowed_hosts* means the allowlist check is skipped (backward
    compatible with providers that have not yet declared allowed_hosts).
    Raises GatewayConfigError on mismatch — does not echo the host.
    """
    if not allowed_hosts:
        return

    parsed = urlparse(base_url)
    host = parsed.hostname or ""

    if host not in allowed_hosts:
        raise GatewayConfigError(
            "provider base_url host is not in allowed_hosts allowlist"
        )
