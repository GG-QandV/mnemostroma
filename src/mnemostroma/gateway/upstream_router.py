# SPDX-License-Identifier: FSL-1.1-MIT
"""UpstreamRouter: dispatches normalized GatewayRequest to the allowlisted
upstream provider per Gateway spec v1.0 "Upstream router" section.

Routing is resolved ONLY via static allowlist configured by the operator
(ADR-005: path segment already fixed provider_id upstream of this class).
Client cannot supply arbitrary base_url/host/redirect target.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

import httpx

from mnemostroma.gateway.config import GatewayLimitsConfig
from mnemostroma.gateway.errors import GatewayConfigError
from mnemostroma.gateway.models import CanonicalMessage, GatewayRequest, UpstreamTarget

class UpstreamDispatchError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code

def _resolve_credential(credential_ref: str) -> str:
    value = os.environ.get(credential_ref)
    if not value:
        raise GatewayConfigError(
            "credential env var not set for upstream (ref hidden)"
        )
    return value

def _messages_to_openai_payload(
    messages: tuple[CanonicalMessage, ...],
    sanitize_fn: Callable[[str], str] | None = None,
) -> list[dict]:
    result = []
    for msg in messages:
        text_parts = [p.content for p in msg.parts if p.type == "text"]
        content = "".join(text_parts) if text_parts else None
        if sanitize_fn and content:
            content = sanitize_fn(content)
        entry: dict[str, Any] = {"role": msg.role, "content": content}
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            entry["tool_calls"] = list(msg.tool_calls)
        result.append(entry)
    return result

class UpstreamRouter:
    _CONTROL_CHARS = str.maketrans({c: None for c in range(32) if c not in (9, 10, 13)})

    def __init__(self, *, limits: GatewayLimitsConfig | None = None, connect_timeout_s: float = 10.0) -> None:
        self._client = httpx.AsyncClient(follow_redirects=False, timeout=connect_timeout_s)
        self._limits = limits or GatewayLimitsConfig()

    def _sanitize_text(self, text: str) -> str:
        if not self._limits.sanitize_control_chars:
            return text
        if self._limits.sanitize_policy == "pass":
            return text
        if self._limits.sanitize_policy == "error":
            for c in text:
                if ord(c) < 32 and ord(c) not in (9, 10, 13):
                    raise UpstreamDispatchError("payload contains control characters", status_code=400)
        cleaned = text.translate(self._CONTROL_CHARS)
        if self._limits.sanitize_warn_on_hit and len(cleaned) != len(text):
            logger.warning("sanitize removed %d control chars from payload", len(text) - len(cleaned))
        return cleaned

    async def aclose(self) -> None:
        await self._client.aclose()

    def _validate_host(self, upstream: UpstreamTarget) -> None:
        host = httpx.URL(upstream.base_url).host
        if upstream.allowed_hosts and host not in upstream.allowed_hosts:
            raise UpstreamDispatchError(
                "upstream host is not in allowed_hosts allowlist", status_code=502
            )

    def _build_payload(self, request: GatewayRequest, memory_text: str | None) -> dict[str, Any]:
        system_text = "".join(p.content for p in request.system_parts if p.type == "text")
        if memory_text:
            system_text = f"{system_text}\n\n{memory_text}" if system_text else memory_text
        system_text = self._sanitize_text(system_text)[:self._limits.max_system_text_bytes]

        messages: list[dict] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.extend(_messages_to_openai_payload(request.messages, sanitize_fn=self._sanitize_text))

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": request.stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_schema,
                    },
                }
                for t in request.tools
            ]
        return payload

    async def dispatch_json(
        self, request: GatewayRequest, memory_text: str | None
    ) -> dict[str, Any]:
        upstream = request.upstream
        self._validate_host(upstream)
        token = _resolve_credential(upstream.credential_ref)
        payload = self._build_payload(request, memory_text)

        try:
            resp = await self._client.post(
                f"{upstream.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=upstream.first_byte_timeout_s,
            )
        except httpx.TimeoutException as e:
            raise UpstreamDispatchError("upstream timeout", status_code=504) from e
        except httpx.ConnectError as e:
            raise UpstreamDispatchError("upstream connection failed", status_code=502) from e

        if resp.status_code >= 400:
            body = resp.text
            logger.warning("upstream error: status=%d body=%s", resp.status_code, body)
            detail = f"upstream error (status {resp.status_code})"
            if self._limits.expose_upstream_errors and body:
                detail = f"{detail}: {body[:500]}"
            raise UpstreamDispatchError(detail, status_code=resp.status_code)
        return resp.json()

    async def dispatch_stream(
        self, request: GatewayRequest, memory_text: str | None
    ) -> AsyncIterator[bytes]:
        upstream = request.upstream
        self._validate_host(upstream)
        token = _resolve_credential(upstream.credential_ref)
        payload = self._build_payload(request, memory_text)

        try:
            async with self._client.stream(
                "POST",
                f"{upstream.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=upstream.idle_timeout_s,
            ) as resp:
                if resp.status_code >= 400:
                    body_bytes = await resp.aread()
                    body_text = body_bytes.decode("utf-8", errors="replace")
                    logger.warning("upstream error: status=%d body=%s", resp.status_code, body_text)
                    detail = f"upstream error (status {resp.status_code})"
                    if self._limits.expose_upstream_errors and body_text:
                        detail = f"{detail}: {body_text[:500]}"
                    raise UpstreamDispatchError(detail, status_code=resp.status_code)
                async for chunk in resp.aiter_bytes():
                    yield chunk
        except httpx.TimeoutException as e:
            raise UpstreamDispatchError("upstream stream timeout", status_code=504) from e
        except httpx.ConnectError as e:
            raise UpstreamDispatchError("upstream connection failed", status_code=502) from e
