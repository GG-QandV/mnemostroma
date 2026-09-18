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


class ModelNotFoundError(KeyError):
    """Raised when ModelRouter.validate_model_for_provider() finds no match."""

    def __init__(self, model_id: str) -> None:
        super().__init__(f"No route found for model: {model_id!r}")
        self.model_id = model_id


class ProviderNotFoundError(KeyError):
    """Raised when path-based routing resolves an unknown or disabled provider."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(f"Provider not found or disabled: {provider_id!r}")
        self.provider_id = provider_id


class InvalidClientIdError(GatewayConfigError):
    """Raised when require_client_id_header=True and header is missing."""


class ConversationIdDerivationError(Exception):
    """Raised when conversation_id cannot be safely derived."""
