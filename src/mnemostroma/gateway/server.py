# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import StreamingResponse

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError, ModelNotFoundError
from mnemostroma.gateway.memory_injector import MemoryInjector
from mnemostroma.gateway.models import MemoryPolicy, UpstreamTarget
from mnemostroma.gateway.observer_bridge import ObserverBridge
from mnemostroma.gateway.outbox import GatewayOutbox
from mnemostroma.gateway.routing import ModelRouter
from mnemostroma.gateway.upstream_router import UpstreamRouter

logger = logging.getLogger(__name__)


class GatewayServer:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        ctx: Any,
        proxy: Any,
        db: Any,
    ) -> None:
        self._config = config
        self._ctx = ctx
        self._proxy = proxy
        self._db = db
        self._outbox: GatewayOutbox | None = None
        self._upstream_router: UpstreamRouter | None = None
        self._facades: dict[str, Any] = {}
        self._model_router: ModelRouter | None = None
        self._app: FastAPI | None = None
        self._ready_event = asyncio.Event()
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None
        self._outbox_worker_task: asyncio.Task | None = None
        self._outbox_cleanup_task: asyncio.Task | None = None
        self._draining = False
        self._concurrent_sem: asyncio.Semaphore | None = None

    # ── App construction (called from start(), not __init__) ────────────

    def _build_app(self) -> FastAPI:
        self._concurrent_sem = asyncio.Semaphore(self._config.limits.max_concurrent_streams)
        app = FastAPI(title="Mnemostroma Gateway", docs_url=None, redoc_url=None)

        @app.get("/healthz")
        async def healthz() -> dict:
            return {"status": "ok"}

        @app.get("/readyz")
        async def readyz() -> dict:
            if not self._ready_event.is_set():
                raise HTTPException(status_code=503, detail="not ready")
            return {"status": "ready"}

        @app.get("/v1/models")
        async def list_models() -> dict:
            routes = self._model_router.all_routes() if self._model_router else {}
            return {
                "object": "list",
                "data": [
                    {"id": model_id, "object": "model", "owned_by": route.provider_id}
                    for model_id, route in routes.items()
                ],
            }

        @app.post("/v1/chat/completions")
        async def chat_completions(request: Request) -> Any:
            self._check_auth(request)
            sem = self._concurrent_sem
            if sem is not None:
                if sem.locked():
                    logger.warning("max concurrent streams reached (%d)", self._config.limits.max_concurrent_streams)
                    raise HTTPException(status_code=503, detail="too many concurrent requests")
                await sem.acquire()
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self._config.limits.max_request_bytes:
                if sem: sem.release()
                logger.warning("request body too large: %s bytes (max %d)", content_length, self._config.limits.max_request_bytes)
                raise HTTPException(status_code=413, detail="request body too large")
            try:
                body = await request.json()
            except Exception:
                if sem: sem.release()
                raise
            requested_model = body.get("model", "")
            if not requested_model or not isinstance(requested_model, str):
                if sem: sem.release()
                raise HTTPException(status_code=400, detail="field 'model' is required and must be a non-empty string")
            if len(requested_model) > self._config.limits.max_model_len:
                if sem: sem.release()
                logger.warning("request validation: model name too long (%d chars, max %d)", len(requested_model), self._config.limits.max_model_len)
                raise HTTPException(status_code=400, detail=f"model name too long (max {self._config.limits.max_model_len})")
            messages = body.get("messages", [])
            if len(messages) > self._config.limits.max_messages:
                if sem: sem.release()
                logger.warning("request validation: too many messages (%d, max %d)", len(messages), self._config.limits.max_messages)
                raise HTTPException(status_code=400, detail=f"too many messages (max {self._config.limits.max_messages})")
            try:
                route = self._model_router.resolve(requested_model)
            except ModelNotFoundError:
                if sem: sem.release()
                raise HTTPException(
                    status_code=404,
                    detail=f"model '{requested_model}' is not registered on any enabled provider",
                )
            facade = self._facades.get(route.provider_id)
            if facade is None:
                if sem: sem.release()
                raise HTTPException(
                    status_code=501,
                    detail=f"protocol '{route.protocol}' facade not implemented",
                )
            try:
                response = await facade.handle_chat_completions(request, upstream_model=route.upstream_model)
            except Exception:
                if sem: sem.release()
                raise
            if isinstance(response, StreamingResponse):
                return _release_on_done(response, sem) if sem else response
            if sem: sem.release()
            return response

        # Native protocol facades — path-based per ADR-005
        @app.post("/anthropic/v1/messages")
        async def anthropic_messages(request: Request) -> Any:
            self._check_auth(request)
            raise HTTPException(status_code=501, detail="anthropic facade not implemented (R4 scope)")

        @app.post("/gemini/v1beta/models/{model_path:path}")
        async def gemini_generate(request: Request, model_path: str) -> Any:
            self._check_auth(request)
            raise HTTPException(status_code=501, detail="gemini facade not implemented (R5 scope)")

        return app

    def _check_auth(self, request: Request) -> None:
        if self._config.auth_mode == "none":
            return
        expected = os.environ.get(self._config.token_env)
        if not expected:
            raise HTTPException(status_code=503, detail="token not configured")
        header = request.headers.get("authorization", "")
        if header != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="unauthorized")

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._config.enabled:
            logger.info("gateway.server: enabled=false, skipping startup")
            return

        self._outbox = GatewayOutbox(
            self._db, max_attempts=self._config.outbox.max_attempts,
        )
        self._upstream_router = UpstreamRouter(
            limits=self._config.limits,
            connect_timeout_s=self._config.limits.connect_timeout_sec,
        )
        observer_bridge = ObserverBridge(self._outbox)
        memory_injector = MemoryInjector(self._proxy, self._ctx)

        for provider_id, profile in self._config.providers.items():
            if not profile.enabled:
                continue
            upstream = UpstreamTarget(
                provider_id=provider_id,
                protocol=str(profile.protocol),
                base_url=profile.base_url,
                credential_ref=profile.credential_env,
                allowed_hosts=profile.allowed_hosts,
                connect_timeout_s=self._config.limits.connect_timeout_sec,
                first_byte_timeout_s=self._config.limits.first_byte_timeout_sec,
                idle_timeout_s=self._config.limits.stream_idle_timeout_sec,
            )
            memory_mode = "read_only" if self._config.memory_mode != "off" else "off"
            memory_policy = MemoryPolicy(
                mode=memory_mode,
                fail_mode="open",
                max_context_tokens=self._config.memory_max_tokens,
            )
            from mnemostroma.gateway.openai_facade import OpenAICompatibleFacade

            self._facades[provider_id] = OpenAICompatibleFacade(
                provider_id=provider_id,
                profile=profile,
                upstream=upstream,
                memory_policy=memory_policy,
                memory_injector=memory_injector,
                upstream_router=self._upstream_router,
                observer_bridge=observer_bridge,
                outbox=self._outbox,
            )

        for provider_id, facade in self._facades.items():
            ok = await facade.probe()
            if not ok:
                logger.warning("upstream %s unreachable at startup", provider_id)
                if self._config.strict_startup:
                    raise GatewayStartupError(f"upstream {provider_id} unreachable")

        self._model_router = ModelRouter(self._config.providers)
        self._app = self._build_app()

        uv_config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(uv_config)
        self._server.install_signal_handlers = False

        original_startup = self._server.startup

        async def _safe_startup(sockets: object = None) -> None:
            try:
                await original_startup(sockets=sockets)
            except (OSError, SystemExit, GatewayStartupError):
                raise GatewayStartupError(
                    f"failed to bind {self._config.host}:{self._config.port}"
                ) from None

        self._server.startup = _safe_startup

        self._server_task = asyncio.create_task(
            self._server.serve(), name="gateway-http-server"
        )
        self._outbox_worker_task = asyncio.create_task(
            self._outbox_worker_loop(), name="gateway-outbox-worker"
        )
        self._outbox_cleanup_task = asyncio.create_task(
            self._outbox_cleanup_loop(), name="gateway-outbox-cleanup"
        )

        for _ in range(50):
            if getattr(self._server, "started", False):
                break
            if self._server_task and self._server_task.done():
                exc = self._server_task.exception()
                if isinstance(exc, GatewayStartupError):
                    raise exc
                if isinstance(exc, OSError):
                    raise GatewayStartupError(
                        f"failed to bind {self._config.host}:{self._config.port}"
                    ) from exc
                break
            await asyncio.sleep(0.05)
        self._ready_event.set()
        logger.info(
            "gateway.server: listening on %s:%d",
            self._config.host, self._config.port,
        )

    async def stop(self, drain_timeout: float = 5.0) -> None:
        if self._outbox_worker_task and not self._outbox_worker_task.done():
            self._draining = True
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._outbox_worker_task), timeout=drain_timeout
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._outbox_worker_task.cancel()

        if self._outbox_cleanup_task and not self._outbox_cleanup_task.done():
            self._outbox_cleanup_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._outbox_cleanup_task), timeout=2.0
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if self._server is None or self._server_task is None:
            return

        self._ready_event.clear()
        self._server.should_exit = True

        try:
            await asyncio.wait_for(self._server_task, timeout=drain_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "gateway.server: shutdown exceeded %.1fs, forcing task cancel",
                drain_timeout,
            )
            self._server_task.cancel()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await self._server_task

        if self._upstream_router:
            await self._upstream_router.aclose()

        logger.info("gateway.server: stopped")

    # ── Outbox worker ───────────────────────────────────────────────────

    async def _outbox_worker_loop(self) -> None:
        import time
        while not self._draining:
            try:
                now = int(time.time())
                rows = await self._outbox.fetch_ready_batch(
                    batch_size=self._config.outbox.batch_size, now=now
                )
                for row in rows:
                    await self._deliver_one(row)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("gateway outbox worker error")
            await asyncio.sleep(1.0)

    async def _deliver_one(self, row: Any) -> None:
        from mnemostroma.observer.pipeline import observer_pipeline

        try:
            payload = json.loads(row["payload_json"])
            await observer_pipeline(
                payload["text"], payload["conversation_id"], self._ctx,
                intent_vector=self._ctx.current_intent_vector,
                role=payload["role"],
            )
            await self._outbox.mark_delivered(row["event_id"])
        except Exception as e:
            await self._outbox.mark_retry(
                row["event_id"], error_code=str(e)[:64],
                backoff_sec=2.0 ** min(row["attempts"], 6),
            )

    async def _outbox_cleanup_loop(self) -> None:
        while not self._draining:
            await asyncio.sleep(3600)
            try:
                removed = await self._outbox.cleanup_delivered(
                    retention_hours=self._config.outbox.retention_hours
                )
                if removed:
                    logger.info(f"gateway outbox cleanup: {removed} records removed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("gateway outbox cleanup error")

    @property
    def is_ready(self) -> bool:
        return self._ready_event.is_set()

    @property
    def started(self) -> bool:
        return self._ready_event.is_set()


def _release_on_done(response: StreamingResponse, sem: asyncio.Semaphore | None) -> StreamingResponse:
    """Wrap a StreamingResponse to release a semaphore when the stream completes."""
    original_iterator = response.body_iterator
    if sem is None:
        return response

    async def _wrapped_iterator():
        try:
            async for chunk in original_iterator:
                yield chunk
        finally:
            sem.release()

    return StreamingResponse(
        _wrapped_iterator(),
        media_type=response.media_type,
        headers=dict(response.headers),
        status_code=response.status_code,
    )
