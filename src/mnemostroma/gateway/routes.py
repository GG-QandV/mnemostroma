# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from mnemostroma.gateway.admission import DispatchAdmission
from mnemostroma.gateway.auth import verify_token
from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import (
    GatewayExecutionError,
    GatewayParseError,
    MemoryUnavailable,
)
from mnemostroma.gateway.metrics import GatewayMetrics
from mnemostroma.gateway.observer import (
    ObservationTaskRegistry,
    assistant_content,
    last_user_content,
)
from mnemostroma.gateway.provider_errors import ProviderTransportError


def _make_auth_check(expected_token: str) -> Callable[[Any], Any]:
    async def _check(request: Any) -> bool:
        raw: str = request.headers.get("authorization", "")
        if not raw.startswith("Bearer "):
            return False
        token = raw[len("Bearer "):]
        return verify_token(token, expected_token)
    return _check


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "unauthorized", "message": "authentication required"}},
        status_code=401,
        headers={"www-authenticate": "Bearer"},
    )


def _error_response(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )


def _with_auth(
    endpoint: Callable[[Any], Any],
    auth_check: Callable[[Any], Any],
) -> Callable[[Any], Any]:
    async def wrapper(request: Any) -> Any:
        if not await auth_check(request):
            return _unauthorized_response()
        return await endpoint(request)
    return wrapper


def _schedule_observer(
    cfg: GatewayConfig,
    request: Request,
    chat_request: Any,
    completion: dict[str, Any],
) -> None:
    if cfg.observation_mode != "active":
        return
    observer = getattr(request.app.state, "completion_observer", None)
    if observer is None:
        return
    registry = getattr(request.app.state, "observation_registry", None)
    if registry is None:
        return
    user_msg = last_user_content(chat_request)
    assistant_msg = assistant_content(completion)
    if user_msg is None or assistant_msg is None:
        return
    registry.schedule(observer, user_msg, assistant_msg)


def _record_invalid(
    metrics: GatewayMetrics | None,
    req_start_s: float,
    validation_start_s: float,
) -> None:
    if metrics is None:
        return
    metrics.record_end("gateway_validation_duration_ms", validation_start_s)
    metrics.increment("gateway_requests_rejected_invalid_total")
    metrics.record_end("gateway_request_duration_ms", req_start_s)


def _record_request_end(
    metrics: GatewayMetrics | None,
    req_start_s: float,
) -> None:
    if metrics is None:
        return
    metrics.record_end("gateway_request_duration_ms", req_start_s)


async def _healthz(request: Any) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "mnemo-gateway"})


async def _readyz(request: Any) -> JSONResponse:
    return JSONResponse({"status": "ready", "memory": "ready"})


async def _gateway_info(request: Any) -> JSONResponse:
    return JSONResponse({
        "version": "0.1.0",
        "capabilities": ["health", "readiness", "info", "chat"],
        "memory_mode": "off",
    })


async def _not_found(request: Any) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "not_found", "message": "not found"}},
        status_code=404,
    )


async def _chat_completions(request: Request) -> JSONResponse:
    from mnemostroma.gateway.execution import GatewayExecutor
    from mnemostroma.gateway.request_policy import (
        read_bounded_body,
        validate_chat_request,
    )
    from mnemostroma.gateway.routing import resolve_route

    metrics = getattr(request.app.state, "metrics", None)
    req_start = metrics.record_start() if metrics is not None else 0.0

    try:
        v_start = metrics.record_start() if metrics is not None else 0.0
        raw = await read_bounded_body(request)
        body = json.loads(raw)
        chat_request = validate_chat_request(body)
        if metrics is not None:
            metrics.record_end("gateway_validation_duration_ms", v_start)
            metrics.increment("gateway_requests_total")
    except json.JSONDecodeError:
        _record_invalid(metrics, req_start, v_start)
        return _error_response("invalid_json", "request body is not valid JSON")
    except GatewayParseError as e:
        _record_invalid(metrics, req_start, v_start)
        return _error_response("invalid_request", str(e))

    cfg: GatewayConfig = request.app.state.gateway_config
    plan = resolve_route(chat_request, cfg)

    if cfg.dispatch_mode == "http" and cfg.provider_mode == "configured":
        from mnemostroma.gateway.httpx_transport import HttpxProviderTransport

        injector = request.app.state.memory_injector
        admission = request.app.state.dispatch_admission
        transport = HttpxProviderTransport(
            base_url=cfg.provider_base_url,
            token_env=cfg.provider_token_env,
            timeout=cfg.provider_timeout_seconds,
        )
        executor = GatewayExecutor(
            transport=transport,
            memory_injector=injector,
            admission=admission,
            metrics=metrics,
        )
        try:
            completion = await executor.execute(chat_request, plan.memory)
        except asyncio.CancelledError:
            if metrics is not None:
                metrics.increment("gateway_requests_cancelled_total")
                metrics.record_end("gateway_request_duration_ms", req_start)
            raise
        except GatewayExecutionError as e:
            _record_request_end(metrics, req_start)
            return _error_response("unsupported_parameter", str(e))
        except ProviderTransportError as e:
            _record_request_end(metrics, req_start)
            if metrics is not None and e.code == "provider_busy":
                metrics.increment("gateway_requests_rejected_busy_total")
            return _error_response(e.code, e.message, e.status)
        except MemoryUnavailable as e:
            _record_request_end(metrics, req_start)
            return _error_response("memory_unavailable", str(e), 503)
        if metrics is not None:
            metrics.increment("gateway_requests_succeeded_total")
            metrics.record_end("gateway_request_duration_ms", req_start)
        _schedule_observer(cfg, request, chat_request, completion)
        return JSONResponse(completion)

    if cfg.dispatch_mode == "fake" and cfg.provider_mode == "configured":
        injector = request.app.state.memory_injector
        admission = request.app.state.dispatch_admission
        executor = GatewayExecutor(
            memory_injector=injector,
            admission=admission,
            metrics=metrics,
        )
        try:
            completion = await executor.execute(chat_request, plan.memory)
        except asyncio.CancelledError:
            if metrics is not None:
                metrics.increment("gateway_requests_cancelled_total")
                metrics.record_end("gateway_request_duration_ms", req_start)
            raise
        except GatewayExecutionError as e:
            _record_request_end(metrics, req_start)
            return _error_response("unsupported_parameter", str(e))
        except ProviderTransportError as e:
            _record_request_end(metrics, req_start)
            if metrics is not None and e.code == "provider_busy":
                metrics.increment("gateway_requests_rejected_busy_total")
            return _error_response(e.code, e.message, e.status)
        except MemoryUnavailable as e:
            _record_request_end(metrics, req_start)
            return _error_response("memory_unavailable", str(e), 503)
        if metrics is not None:
            metrics.increment("gateway_requests_succeeded_total")
            metrics.record_end("gateway_request_duration_ms", req_start)
        _schedule_observer(cfg, request, chat_request, completion)
        return JSONResponse(completion)

    resp_body: dict[str, object] = {
        "id": plan.id,
        "object": plan.object,
        "created": plan.created,
        "dry_run": plan.dry_run,
        "execution": plan.execution,
        "model": plan.model,
        "upstream_path": plan.upstream_path,
        "stream": plan.stream,
        "memory": asdict(plan.memory),
        "provider": asdict(plan.provider),
    }
    if plan.reason is not None:
        resp_body["reason"] = plan.reason
    return JSONResponse(resp_body)


@asynccontextmanager
async def _gateway_lifespan(app: Any) -> AsyncIterator[None]:
    registry: ObservationTaskRegistry = app.state.observation_registry
    try:
        yield
    finally:
        await registry.drain()


def create_app(
    expected_token: str,
    gateway_config: GatewayConfig | None = None,
    memory_injector: Any = None,
    completion_observer: Any = None,
    metrics: GatewayMetrics | None = None,
) -> ASGIApp:
    from starlette.applications import Starlette

    auth_check = _make_auth_check(expected_token)
    cfg = gateway_config or GatewayConfig()

    app = Starlette(
        routes=[
            Route("/healthz", endpoint=_healthz, methods=["GET"]),
            Route("/readyz", endpoint=_with_auth(_readyz, auth_check), methods=["GET"]),
            Route(
                "/v1/gateway/info",
                endpoint=_with_auth(_gateway_info, auth_check),
                methods=["GET"],
            ),
            Route(
                "/v1/chat/completions",
                endpoint=_with_auth(_chat_completions, auth_check),
                methods=["POST"],
            ),
            Route("/{path:path}", endpoint=_not_found),
        ],
        lifespan=_gateway_lifespan,
    )
    app.state.gateway_config = cfg
    app.state.memory_injector = memory_injector
    app.state.completion_observer = completion_observer
    app.state.observation_registry = ObservationTaskRegistry(metrics=metrics)
    app.state.dispatch_admission = DispatchAdmission(
        max_total=cfg.max_concurrent_dispatches,
        max_memory=cfg.max_concurrent_memory_requests,
    )
    app.state.metrics = metrics
    return app
