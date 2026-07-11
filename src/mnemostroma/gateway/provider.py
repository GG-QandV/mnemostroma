# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: tuple[dict[str, str], ...]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    memory_injection: str = "not_materialized"


@dataclass(frozen=True)
class ProviderResponse:
    status: int
    body: str
    headers: dict[str, str] | None = None


class ProviderTransport(Protocol):
    async def send(self, request: ProviderRequest) -> ProviderResponse: ...
