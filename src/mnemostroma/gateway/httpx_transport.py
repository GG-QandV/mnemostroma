# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import json
from typing import Any

import httpx

from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse
from mnemostroma.gateway.provider_credentials import (
    EnvironmentCredentialResolver,
    ProviderCredentialError,
    ProviderCredentialResolver,
)
from mnemostroma.gateway.provider_errors import ProviderTransportError

_MNEMO_UA = "mnemo-gateway/0.1.0"
_UPSTREAM_PATH = "/chat/completions"


def _validate_token(raw: str) -> None:
    stripped = raw.strip()
    if not stripped or stripped != raw:
        raise ProviderTransportError(
            503, "provider_credentials_unavailable",
            "credentials are unavailable",
        )
    for ch in raw:
        if ord(ch) < 0x20 or ch in "\x7f":
            raise ProviderTransportError(
                503, "provider_credentials_unavailable",
                "credentials are unavailable",
            )


_STATUS_CODE_MAP: dict[int, str] = {
    302: "provider_invalid_response",
    307: "provider_invalid_response",
    400: "provider_rejected_request",
    401: "provider_auth_failed",
    403: "provider_auth_failed",
    404: "provider_rejected_request",
    422: "provider_rejected_request",
    429: "provider_rate_limited",
    500: "provider_server_error",
    502: "provider_server_error",
    503: "provider_server_error",
}

_CANONICAL_STATUS: dict[str, int] = {
    "provider_auth_failed": 502,
    "provider_rate_limited": 503,
    "provider_rejected_request": 400,
    "provider_server_error": 502,
    "provider_timeout": 504,
    "provider_unreachable": 502,
    "provider_invalid_response": 502,
    "provider_credentials_unavailable": 503,
}


def _classify_status(status: int) -> tuple[str, int]:
    code = _STATUS_CODE_MAP.get(status, "provider_server_error")
    return code, _CANONICAL_STATUS.get(code, 502)


def _build_payload(req: ProviderRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": req.model,
        "messages": list(req.messages),
        "stream": False,
    }
    if req.temperature is not None:
        payload["temperature"] = req.temperature
    if req.max_tokens is not None:
        payload["max_tokens"] = req.max_tokens
    return payload


def _validate_completion_shape(body: dict[str, Any]) -> None:
    if not isinstance(body.get("choices"), list) or len(body["choices"]) == 0:
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response missing valid choices",
        )
    choice = body["choices"][0]
    if not isinstance(choice, dict):
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response choice is not an object",
        )
    msg = choice.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), str):
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response message missing content",
        )


class HttpxProviderTransport:
    def __init__(
        self,
        base_url: str,
        token_env: str,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
        credential_resolver: ProviderCredentialResolver | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_env = token_env
        self._timeout = timeout
        self._http_client = http_client
        self._resolver: ProviderCredentialResolver = (
            credential_resolver or EnvironmentCredentialResolver()
        )

    async def send(self, request: ProviderRequest) -> ProviderResponse:
        try:
            token = self._resolver.resolve(self._token_env)
        except ProviderCredentialError:
            raise ProviderTransportError(
                503, "provider_credentials_unavailable",
                "credentials are unavailable",
            ) from None
        _validate_token(token)

        payload = _build_payload(request)
        url = f"{self._base_url}{_UPSTREAM_PATH}"

        headers: dict[str, str] = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "user-agent": _MNEMO_UA,
        }

        if self._http_client is not None:
            client = self._http_client
            return await self._send_with_client(client, url, headers, payload)

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await self._send_with_client(client, url, headers, payload)

    async def _send_with_client(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> ProviderResponse:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ProviderTransportError(
                504, "provider_timeout",
                "upstream provider did not respond in time",
            ) from None
        except httpx.ConnectError:
            raise ProviderTransportError(
                502, "provider_unreachable",
                "could not connect to upstream provider",
            ) from None
        except httpx.HTTPError as e:
            raise ProviderTransportError(
                502, "provider_unreachable",
                f"upstream request failed: {e.__class__.__name__}",
            ) from None

        if resp.status_code != 200:
            code, canonical_status = _classify_status(resp.status_code)
            safe_msg = f"upstream returned status {resp.status_code}"
            raise ProviderTransportError(canonical_status, code, safe_msg)

        try:
            body = resp.json()
        except json.JSONDecodeError:
            raise ProviderTransportError(
                502, "provider_invalid_response",
                "upstream returned non-json body",
            ) from None

        _validate_completion_shape(body)
        return ProviderResponse(status=200, body=json.dumps(body))
