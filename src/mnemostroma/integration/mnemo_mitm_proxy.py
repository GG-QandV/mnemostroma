# SPDX-License-Identifier: FSL-1.1-MIT
"""Forward HTTPS proxy with MITM TLS for opencode → arbitrary LLM upstream.

Unlike proxy_passthrough.py / http_proxy.py, this is NOT an ASGI app and
does not target a single fixed upstream. opencode is pointed at this
proxy via HTTPS_PROXY and issues a standard HTTP CONNECT for whichever
host it talks to (api.cursor.sh, api.anthropic.com, ...). We:

  1. accept the CONNECT, reply 200, and take over the raw socket
  2. terminate TLS towards the client using a leaf cert for that host,
     signed by the local MITM CA (trusted via NODE_EXTRA_CA_CERTS)
  3. open our own TLS connection to the real host
  4. pipe bytes both ways, recording request/response text via the
     existing daemon IPC ("observe") as a side effect

Observer/IPC failures must never break the tunnel: a broken `observe`
call is logged and swallowed, traffic keeps flowing either way.

Entry point: run() — started from mcp_sse_adapter.run() on a dedicated
port, separate from :8767 (passthrough), :8768 (MCP HTTP adapter) and
:8769 (OAuth adapter, supervised by integration/tunnel/manager.py).
"""
import asyncio
import contextlib
import logging
import re
import ssl
from pathlib import Path

from .common import safe_ipc_call as _ipc_call
from ..proxy.models import MitmProxyConfig
from ..proxy.tunnel import _Activity, _idle_watchdog
from ..setup.mitm_ca import get_or_create_leaf_cert

logger = logging.getLogger("mnemostroma.mitm_proxy")

_MNEMO_DIR = Path.home() / ".mnemostroma"
_CA_CERT = _MNEMO_DIR / "mitm-ca-cert.pem"
_CA_KEY = _MNEMO_DIR / "mitm-ca-key.pem"

_CONNECT_RE = re.compile(rb"^CONNECT\s+([^\s:]+):(\d+)\s+HTTP/1\.\d", re.IGNORECASE)

_READ_CHUNK = 65536
_MAX_OBSERVE_BUF = 102400  # 100KB — flush accumulated data when buffer exceeds this
_UPSTREAM_CONNECT_TIMEOUT = 10.0  # seconds — bound the upstream TCP+TLS handshake
_UPSTREAM_IDLE_TIMEOUT = 300.0    # 5 minutes — close tunnel if upstream is silent

# Cache one SSLContext per host process-wide — building a context from
# disk certs on every CONNECT would add a syscall-heavy stat+read per
# connection on top of the (cached) keypair generation.
_ctx_cache: dict[str, ssl.SSLContext] = {}
# Per-host locks (not one global lock) — generating a cert for a new host
# must not stall a concurrent CONNECT to an unrelated new host.
_ctx_cache_locks: dict[str, asyncio.Lock] = {}
_ctx_cache_locks_guard = asyncio.Lock()

# Hosts to skip observation (noisy LLM API calls that flood the DB)
_OBSERVE_SKIP_HOSTS: frozenset = frozenset({
    "api.deepseek.com",
    "api.openai.com",
    "api.anthropic.com",
    "opencode.ai",
    "openrouter.ai",
    "models.dev",
    "github.com",
    "api.github.com",
    "graph.threads.net",
    "registry.npmjs.org",
    "raw.githubusercontent.com",
    "pypi.org",
    "developers.facebook.com",
    "mcp.exa.ai",
    "console.opencode.ai",
    "www.alchemy.com",
    "www.work.ua",
    "release-assets.githubusercontent.com",
    "search.parallel.ai",
    "api.oanor.com",
    "api.telegram.org",
    "core.telegram.org",
    "developers.google.com",
    "developers.zoom.us",
    "marketplace.zoom.us",
    "jobs.dou.ua",
})

_metrics: dict[str, int] = {
    "connects": 0,
    "observed": 0,
    "skipped": 0,
    "tls_errors": 0,
    "observe_errors": 0,
}

# ADR-005 client scoping. Когда _scoped_config задан — handle_client маршрутизирует
# CONNECT через proxy/tunnel.py (registry → intercept/passthrough/reject).
# run() всегда его задаёт: при нечитаемом конфиге — пустой passthrough-реестр,
# а не None. None означает «безусловный MITM на любой хост» и остаётся только
# для прямых вызовов handle_client в тестах.
_scoped_config: MitmProxyConfig | None = None


def _passthrough_only_config(port: int) -> MitmProxyConfig:
    """Реестр без единого клиента: перехвата нет, всё уходит в туннель."""
    return MitmProxyConfig(port=port, clients=())


def set_proxy_config(cfg: MitmProxyConfig | None) -> None:
    """Задать конфигурацию scoping'а. Валидация fail-fast до открытия сокетов."""
    global _scoped_config
    if cfg is not None:
        from ..proxy.validation import _MITM_RESERVED_PORTS, validate_mitm_proxy_config

        validate_mitm_proxy_config(cfg, reserved_ports=set(_MITM_RESERVED_PORTS))
    _scoped_config = cfg


def _parse_connect(first_line: bytes) -> tuple[str, int] | None:
    m = _CONNECT_RE.match(first_line)
    if not m:
        return None
    return m.group(1).decode("ascii"), int(m.group(2))


async def _consume_headers(reader: asyncio.StreamReader) -> None:
    """Drain the CONNECT request's header block (we don't need it)."""
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            return


async def _get_host_lock(host: str) -> asyncio.Lock:
    lock = _ctx_cache_locks.get(host)
    if lock is not None:
        return lock
    async with _ctx_cache_locks_guard:
        lock = _ctx_cache_locks.setdefault(host, asyncio.Lock())
        return lock


async def _build_server_ctx_for_host(host: str) -> ssl.SSLContext:
    cached = _ctx_cache.get(host)
    if cached is not None:
        return cached

    host_lock = await _get_host_lock(host)
    async with host_lock:
        cached = _ctx_cache.get(host)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()
        cert_path, key_path = await loop.run_in_executor(
            None, get_or_create_leaf_cert, host, _CA_CERT, _CA_KEY, _MNEMO_DIR
        )

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        _ctx_cache[host] = ctx
        return ctx


async def _observe(host: str, direction: str, data: bytes, conductor=None) -> None:
    # Skip noisy LLM API hosts to prevent flooding the DB
    if host in _OBSERVE_SKIP_HOSTS:
        _metrics["skipped"] += 1
        return
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return
    is_user = direction == "request"
    try:
        if is_user:
            args = {"session_id": f"opencode-{host}", "text": text, "role": direction}
            if conductor is not None:
                await conductor.dispatch("observe_raw", args)
            else:
                await _ipc_call("observe_raw", args)
        else:
            args = {"session_id": f"opencode-{host}", "text": f"[assistant]\n{text}"}
            if conductor is not None:
                await conductor.dispatch("observe", args)
            else:
                await _ipc_call("observe", args)
        _metrics["observed"] += 1
    except Exception as exc:
        _metrics["observe_errors"] += 1
        logger.debug("observe failed for %s (%s): %s", host, direction, exc)


async def _pipe_and_observe(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    host: str,
    direction: str,
    conductor=None,
    activity: "_Activity | None" = None,
) -> None:
    # Pure pipe for noisy hosts — no buffer accumulation, no observe
    if host in _OBSERVE_SKIP_HOSTS:
        try:
            while True:
                chunk = await src.read(_READ_CHUNK)
                if not chunk:
                    break
                if activity is not None:
                    activity.touch()
                dst.write(chunk)
                await dst.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                dst.write_eof()
            except (OSError, RuntimeError):
                pass
        return

    buffer = bytearray()
    # Track pending observe tasks to await/cancel them on connection close
    pending_observe_tasks: set[asyncio.Task] = set()

    def _track_observe(task: asyncio.Task) -> None:
        pending_observe_tasks.add(task)
        task.add_done_callback(pending_observe_tasks.discard)

    try:
        while True:
            chunk = await src.read(_READ_CHUNK)
            if not chunk:
                break
            if activity is not None:
                activity.touch()
            dst.write(chunk)
            await dst.drain()
            buffer.extend(chunk)
            if len(buffer) >= _MAX_OBSERVE_BUF:
                _track_observe(asyncio.create_task(_observe(host, direction, bytes(buffer), conductor=conductor)))
                buffer.clear()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    except asyncio.CancelledError:
        # On cancellation, await observe tasks before re-raising
        if pending_observe_tasks:
            await asyncio.shield(asyncio.gather(*pending_observe_tasks, return_exceptions=True))
            pending_observe_tasks.clear()
        raise
    finally:
        # Wait for all pending observe tasks to complete
        if pending_observe_tasks:
            await asyncio.shield(asyncio.gather(*pending_observe_tasks, return_exceptions=True))
            pending_observe_tasks.clear()

        if buffer:
            # Final flush - await directly since we're in finally
            await _observe(host, direction, bytes(buffer), conductor=conductor)
            buffer.clear()
        try:
            dst.write_eof()
        except (OSError, RuntimeError):
            pass


async def _close_quietly(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    try:
        writer.close()
        # Add timeout and catch ALL exceptions to prevent task destruction warnings
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
    except Exception:
        # Catch all exceptions including CancelledError, TimeoutError, etc.
        pass


async def handle_connect_mitm(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    port: int,
    conductor=None,
    upstream_host: str | None = None,
    idle_timeout: float | None = None,
) -> None:
    """MITM-перехват одного CONNECT.

    ``host`` — имя из CONNECT: на него выписывается leaf-сертификат и по нему
    ведётся observe. ``upstream_host`` (если задан профилем клиента) — куда
    реально идти за данными.

    ``idle_timeout`` — простой без единого байта в обе стороны. Отсчёт
    сбрасывается каждым чанком: раньше здесь стоял ``wait_for`` вокруг обоих
    пайпов, то есть жёсткий потолок времени жизни, который рубил многоминутные
    генерации на середине.
    """
    _metrics["connects"] += 1
    connect_host = upstream_host or host
    if idle_timeout is None:
        idle_timeout = _UPSTREAM_IDLE_TIMEOUT

    await _consume_headers(reader)
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()

    raw_transport = writer.transport
    raw_socket = raw_transport.get_extra_info("socket")
    if raw_socket is None:
        logger.error("no raw socket for CONNECT %s:%s — aborting", host, port)
        await _close_quietly(writer)
        return

    loop = asyncio.get_running_loop()

    try:
        server_ctx = await _build_server_ctx_for_host(host)
    except Exception:
        logger.exception("leaf cert generation failed for %s — aborting tunnel", host)
        _metrics["tls_errors"] += 1
        await _close_quietly(writer)
        return

    try:
        client_reader = asyncio.StreamReader()
        client_protocol = asyncio.StreamReaderProtocol(client_reader)
        client_transport = None
        client_transport = await loop.start_tls(
            raw_transport, client_protocol, server_ctx, server_side=True
        )
        client_writer = asyncio.StreamWriter(client_transport, client_protocol, client_reader, loop)
    except (ssl.SSLError, OSError) as exc:
        logger.warning("client TLS handshake failed for %s: %s", host, exc)
        _metrics["tls_errors"] += 1
        await _close_quietly(writer)
        # Ensure the raw transport is closed if start_tls created a transport that failed
        try:
            raw_transport.close()
        except Exception:
            pass
        # Also close client_transport if it was created
        try:
            if client_transport is not None:
                client_transport.close()
        except Exception:
            pass
        return

    upstream_reader: asyncio.StreamReader | None = None
    upstream_writer: asyncio.StreamWriter | None = None
    pipe_task_1: asyncio.Task | None = None
    pipe_task_2: asyncio.Task | None = None

    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(
                connect_host, port, ssl=ssl.create_default_context(), server_hostname=host
            ),
            timeout=_UPSTREAM_CONNECT_TIMEOUT,
        )
    except (OSError, ssl.SSLError) as exc:
        logger.warning("upstream connect failed for %s:%s: %s", connect_host, port, exc)
        await _close_quietly(client_writer)
        return
    except TimeoutError:
        logger.warning(
            "upstream connect timed out for %s:%s after %.0fs",
            connect_host, port, _UPSTREAM_CONNECT_TIMEOUT,
        )
        await _close_quietly(client_writer)
        return

    watchdog: asyncio.Task | None = None
    try:
        activity = _Activity()
        pipe_task_1 = asyncio.create_task(
            _pipe_and_observe(
                client_reader, upstream_writer, host, "request",
                conductor=conductor, activity=activity,
            )
        )
        pipe_task_2 = asyncio.create_task(
            _pipe_and_observe(
                upstream_reader, client_writer, host, "response",
                conductor=conductor, activity=activity,
            )
        )
        if idle_timeout and idle_timeout > 0:
            watchdog = asyncio.create_task(
                _idle_watchdog(
                    activity, idle_timeout, [pipe_task_1, pipe_task_2], host
                )
            )
        results = await asyncio.gather(
            pipe_task_1, pipe_task_2, return_exceptions=True
        )
        for r in results:
            if isinstance(r, BaseException) and not isinstance(
                r, asyncio.CancelledError
            ):
                logger.error("pipe failed for %s: %r", host, r)
    except asyncio.CancelledError:
        raise
    finally:
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await watchdog
        # Explicitly await/cancel pipe tasks to ensure their finally blocks run
        for task in (pipe_task_1, pipe_task_2):
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.shield(asyncio.wait_for(task, timeout=2.0))
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        await _close_quietly(upstream_writer)
        await _close_quietly(client_writer)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, conductor=None) -> None:
    try:
        first_line = await reader.readline()
    except (ConnectionResetError, OSError):
        await _close_quietly(writer)
        return

    if not first_line:
        await _close_quietly(writer)
        return

    target = _parse_connect(first_line)
    if target is None:
        logger.warning("non-CONNECT request rejected: %s", first_line[:80])
        writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
        try:
            await writer.drain()
        except (ConnectionResetError, OSError):
            pass
        await _close_quietly(writer)
        return

    host, port = target
    try:
        if _scoped_config is not None:
            from ..proxy.tunnel import handle_connect as scoped_handle_connect

            await scoped_handle_connect(reader, writer, host, port, _scoped_config)
        else:
            await handle_connect_mitm(reader, writer, host, port, conductor=conductor)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("unhandled error in MITM tunnel for %s:%s", host, port)
    finally:
        # Feed EOF to reader to unblock any pending readline
        reader.feed_eof()
        await _close_quietly(writer)


async def run(
    conductor=None,
    port: int = 8764,
    proxy_config: MitmProxyConfig | None = None,
) -> None:
    if not (_CA_CERT.exists() and _CA_KEY.exists()):
        logger.warning(
            "MITM CA missing (%s) — opencode proxy disabled. Run: mnemostroma setup",
            _CA_CERT,
        )
        return

    # ADR-005: проводник контекста в tunnel-модуль (для INTERCEPT-клиентов)
    from ..proxy.tunnel import set_conductor

    set_conductor(conductor)

    # Загрузить секцию mitm_proxy из ~/.mnemostroma/config.json.
    # Любая ошибка конфига (включая отсутствие файла/секции) → перехват
    # отключается, но прокси продолжает работать как прозрачный туннель.
    if _scoped_config is None:
        if proxy_config is not None:
            set_proxy_config(proxy_config)
        else:
            user_cfg = _MNEMO_DIR / "config.json"
            if not user_cfg.exists():
                logger.warning(
                    "%s отсутствует — перехват отключён, весь трафик "
                    "идёт passthrough",
                    user_cfg,
                )
                set_proxy_config(_passthrough_only_config(port))
            else:
                try:
                    from ..proxy.validation import load_mitm_proxy_config_from_file

                    set_proxy_config(load_mitm_proxy_config_from_file(user_cfg))
                    logger.info(
                        "MITM proxy client scoping active "
                        "(%d clients, unmatched=%s)",
                        len(_scoped_config.clients) if _scoped_config else 0,
                        _scoped_config.unmatched_host_action.value
                        if _scoped_config
                        else "n/a",
                    )
                except Exception as exc:
                    # Fail-CLOSED. Раньше здесь оставалось _scoped_config=None,
                    # то есть безусловный MITM на КАЖДЫЙ хост — ровно то
                    # состояние, которое сводило запросы к 000. Одна опечатка в
                    # рантайм-конфиге (или просто отсутствие секции mitm_proxy —
                    # load_* бросает именно на этом) откатывала весь scoping.
                    # Вместо этого — пустой реестр: не перехватываем ничего,
                    # проксируем всё прозрачно.
                    logger.warning(
                        "invalid mitm_proxy config in %s (%s) — "
                        "перехват отключён, весь трафик идёт passthrough",
                        user_cfg,
                        exc,
                    )
                    set_proxy_config(_passthrough_only_config(port))

    import functools
    handler = functools.partial(handle_client, conductor=conductor)
    server = await asyncio.start_server(handler, host="127.0.0.1", port=port)
    logger.info("opencode MITM proxy listening on http://127.0.0.1:%d", port)
    async with server:
        await server.serve_forever()
