# SPDX-License-Identifier: FSL-1.1-MIT
"""ObserverBridge: emits user_received / assistant_finalized events into
the durable GatewayOutbox, per spec v1.0 "Observer bridge" section.

Never calls Observer synchronously in the response path — events are
written to outbox and delivered asynchronously by the outbox worker.
"""
from __future__ import annotations

import logging
from typing import Literal

from mnemostroma.gateway.models import GatewayRequest
from mnemostroma.gateway.outbox import GatewayOutbox, ObservationEvent

logger = logging.getLogger("mnemostroma.gateway.observer_bridge")

ObservationStatus = Literal["complete", "partial", "cancelled", "failed"]


class ObserverBridge:
    def __init__(self, outbox: GatewayOutbox) -> None:
        self._outbox = outbox

    async def record_user_received(self, request: GatewayRequest, text: str) -> None:
        if not request.memory_policy.observe_user:
            return

        event = ObservationEvent.create(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            client_id=request.client_id,
            project_id=request.project_id,
            role="user",
            text=text,
            status="complete",
            provider_id=request.provider_id,
            model=request.model,
            dedupe_key=f"{request.request_id}:user",
        )
        try:
            await self._outbox.enqueue(event)
        except Exception as e:
            logger.error(f"observer outbox enqueue failed (user) request_id={request.request_id}: {e}")

    async def record_assistant_finalized(
        self,
        request: GatewayRequest,
        text: str,
        *,
        status: ObservationStatus,
    ) -> None:
        if not request.memory_policy.observe_assistant:
            return

        if status == "failed":
            return

        if status == "partial" and not request.memory_policy.allow_partial_capture:
            return

        event = ObservationEvent.create(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            client_id=request.client_id,
            project_id=request.project_id,
            role="assistant",
            text=text,
            status=status,
            provider_id=request.provider_id,
            model=request.model,
            dedupe_key=f"{request.request_id}:assistant",
        )
        try:
            await self._outbox.enqueue(event)
        except Exception as e:
            logger.error(f"observer outbox enqueue failed (assistant) request_id={request.request_id}: {e}")
