# SPDX-License-Identifier: FSL-1.1-MIT
"""OpenAICompatibleFacade: /openai/{provider}/v1/chat/completions

Implements the request lifecycle from spec v1.0 § "Обычный запрос" —
including Observer bridge calls: user_received after protocol validation
and before upstream call; assistant_finalized on complete or partial;
never on failed upstream.
"""
from __future__ import annotations

import json as _json
import logging
import os
import time
from typing import Any, AsyncIterator

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from mnemostroma.gateway.memory_injector import MemoryInjector, wrap_memory_context
from mnemostroma.gateway.models import GatewayProfile, GatewayRequest, MemoryPolicy, UpstreamTarget
from mnemostroma.gateway.observer_bridge import ObserverBridge
from mnemostroma.gateway.outbox import GatewayOutbox
from mnemostroma.gateway.request_normalizer import normalize_openai_request
from mnemostroma.gateway.upstream_router import UpstreamDispatchError, UpstreamRouter

logger = logging.getLogger("mnemostroma.gateway.openai_facade")


def _extract_last_user_text_for_observe(request: GatewayRequest) -> str:
    for msg in reversed(request.messages):
        if msg.role != "user":
            continue
        parts = [p.content for p in msg.parts if p.type == "text"]
        if parts:
            return " ".join(parts)
    return ""


def _extract_response_text(result: dict[str, Any]) -> str:
    try:
        return result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


class OpenAICompatibleFacade:
    def __init__(
        self,
        *,
        provider_id: str,
        profile: GatewayProfile,
        upstream: UpstreamTarget,
        memory_policy: MemoryPolicy,
        memory_injector: MemoryInjector,
        upstream_router: UpstreamRouter,
        observer_bridge: ObserverBridge,
        outbox: GatewayOutbox,
        observer_capture_max_chars: int = 20000,
    ) -> None:
        self._provider_id = provider_id
        self._profile = profile
        self._upstream = upstream
        self._memory_policy = memory_policy
        self._injector = memory_injector
        self._router = upstream_router
        self._observer = observer_bridge
        self._outbox = outbox
        self._capture_max_chars = observer_capture_max_chars

    async def probe(self) -> bool:
        try:
            self._router._validate_host(self._upstream)
            token = os.environ.get(self._upstream.credential_ref)
            if not token:
                return False
            return True
        except Exception:
            return False

    async def handle_chat_completions(self, http_request: Request, upstream_model: str | None = None) -> Any:
        body = await http_request.json()
        if not upstream_model:
            raise HTTPException(status_code=500, detail=f"upstream_model not resolved for '{body.get('model', '?')}'")
        headers = {k.lower(): v for k, v in http_request.headers.items()}

        request = normalize_openai_request(
            body=body,
            headers=headers,
            provider_id=self._provider_id,
            upstream=self._upstream,
            profile=self._profile,
            memory_policy=self._memory_policy,
            model_override=upstream_model,
        )

        user_text = _extract_last_user_text_for_observe(request)
        await self._observer.record_user_received(request, user_text)

        memory_text: str | None = None
        already_injected = self._injector.has_injection_marker(headers)

        if not already_injected:
            try:
                block = await self._injector.inject(request)
                if block is not None:
                    memory_text = wrap_memory_context(block.text)
            except Exception as e:
                logger.warning(f"memory injection failed request_id={request.request_id}: {e}")
                if self._memory_policy.fail_mode == "closed":
                    raise HTTPException(status_code=503, detail="memory subsystem unavailable")

        header_name, header_value = self._injector.injection_header()
        conv_header = (header_name, header_value)
        response_headers = {header_name: header_value}
        if request.conversation_id:
            response_headers["x-mnemo-conversation-id"] = request.conversation_id

        if request.stream:
            stream_start = int(time.time())
            return StreamingResponse(
                self._stream_response(request, memory_text, start_time=stream_start),
                media_type="text/event-stream",
                headers=response_headers,
            )

        now = int(time.time())
        try:
            result = await self._router.dispatch_json(request, memory_text)
        except UpstreamDispatchError as e:
            await self._outbox.record_audit(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                client_id=request.client_id,
                provider_id=request.provider_id,
                model=request.model,
                memory_injected=memory_text is not None,
                status="failed",
                created_at=now,
                completed_at=int(time.time()),
            )
            raise HTTPException(status_code=e.status_code, detail=str(e))

        assistant_text = _extract_response_text(result)
        truncated = assistant_text[: self._capture_max_chars]
        await self._observer.record_assistant_finalized(request, truncated, status="complete")

        await self._outbox.record_audit(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            client_id=request.client_id,
            provider_id=request.provider_id,
            model=request.model,
            memory_injected=memory_text is not None,
            status="complete",
            created_at=now,
            completed_at=int(time.time()),
        )

        return JSONResponse(content=result, headers=response_headers)

    async def _stream_response(self, request, memory_text: str | None, *, start_time: int) -> AsyncIterator[bytes]:
        collected: list[str] = []
        collected_len = 0
        status: str = "complete"
        audit_written = False

        try:
            async for chunk in self._router.dispatch_stream(request, memory_text):
                yield chunk
                if collected_len < self._capture_max_chars:
                    text_fragment = self._extract_sse_text_fragment(chunk)
                    if text_fragment:
                        collected.append(text_fragment)
                        collected_len += len(text_fragment)
        except UpstreamDispatchError as e:
            await self._outbox.record_audit(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                client_id=request.client_id,
                provider_id=request.provider_id,
                model=request.model,
                memory_injected=memory_text is not None,
                status="failed",
                created_at=start_time,
            )
            audit_written = True
            error_event = f'data: {_json.dumps({"error": {"message": str(e), "code": e.status_code}})}\n\n'
            yield error_event.encode()
            yield b"data: [DONE]\n\n"
            return
        except Exception:
            status = "cancelled"
            raise
        finally:
            if not audit_written:
                await self._outbox.record_audit(
                    request_id=request.request_id,
                    conversation_id=request.conversation_id,
                    client_id=request.client_id,
                    provider_id=request.provider_id,
                    model=request.model,
                    memory_injected=memory_text is not None,
                    status=status,
                    created_at=start_time,
                )
            if status == "cancelled":
                if collected and len("".join(collected)) > 20:
                    await self._observer.record_assistant_finalized(
                        request, "".join(collected)[: self._capture_max_chars], status="partial"
                    )
            else:
                if collected:
                    await self._observer.record_assistant_finalized(
                        request, "".join(collected)[: self._capture_max_chars], status="complete"
                    )

    @staticmethod
    def _extract_sse_text_fragment(chunk: bytes) -> str:
        text = chunk.decode("utf-8", errors="ignore")
        fragment = ""
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                continue
            try:
                payload = _json.loads(data)
                delta = payload.get("choices", [{}])[0].get("delta", {})
                fragment += delta.get("content", "") or ""
            except Exception:
                continue
        return fragment
