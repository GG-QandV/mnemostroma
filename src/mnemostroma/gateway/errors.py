# SPDX-License-Identifier: FSL-1.1-MIT


class GatewayConfigError(ValueError):
    """Raised when gateway configuration validation fails."""


class GatewayReservedPortError(GatewayConfigError):
    """Raised when gateway port collides with a reserved transport port."""


class GatewayProfileError(GatewayConfigError):
    """Raised when profile/provider config contains disallowed keys."""


class GatewayStartupError(RuntimeError):
    """Raised when gateway fails to start (missing token, port conflict, etc)."""


class GatewayParseError(ValueError):
    """Raised when request payload parsing fails (invalid fields, types, etc)."""


class GatewayExecutionError(RuntimeError):
    """Raised when gateway execution fails (stream-in-fake, transport error, etc)."""


class MemoryUnavailable(RuntimeError):
    """Raised when memory injection is required but unavailable or invalid."""

    def __init__(self, message: str) -> None:
        self._msg = message
        super().__init__(message)

    @property
    def message(self) -> str:
        return self._msg
