# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from fastapi import APIRouter

from mnemostroma.gateway.config import GatewayConfig


def make_models_router(gateway_config: GatewayConfig) -> APIRouter:
    """Build GET /v1/models handler that aggregates all enabled providers."""

    router = APIRouter()

    @router.get("/v1/models")
    async def list_models():
        models = []
        for provider_id, profile in gateway_config.providers.items():
            if not profile.enabled:
                continue
            for model_id in profile.exposed_models:
                models.append({
                    "id": model_id,
                    "object": "model",
                    "owned_by": provider_id,
                    "created": 0,
                })
        return {"object": "list", "data": models}

    return router
