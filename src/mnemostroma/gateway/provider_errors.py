# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations


class ProviderTransportError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self._msg = message
        super().__init__(message)

    @property
    def message(self) -> str:
        return self._msg

    def __repr__(self) -> str:
        return f"ProviderTransportError(status={self.status}, code={self.code!r})"
