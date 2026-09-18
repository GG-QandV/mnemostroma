# SPDX-License-Identifier: FSL-1.1-MIT
"""Connection handling for the scoped MITM proxy (ADR-005 §7–§8).

Ключевой инвариант: соединение никогда не закрывается «тихим» RST без
записанных байт — любой отказ это детерминированный HTTP-ответ (502/503/504)
или прозрачный туннель (fail-open passthrough).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from mnemostroma.proxy.models import (
    ClientProfile,
    MitmProxyConfig,
    ProxyCaptureMode,
    UnmatchedHostAction,
)
from mnemostroma.proxy.registry import resolve_client

logger = logging.getLogger("mnemostroma.proxy.tunnel")

_READ_CHUNK = 65536

# Глобальный счётчик активных туннелей. Инкремент/декремент выполняются без
# await между проверкой и изменением — атомарно внутри одного event loop,
# поэтому отдельный lock не нужен и не зависит от привязанного loop'а.
_active_tunnels = 0


def _try_acquire_slot(cfg: MitmProxyConfig) -> bool:
    global _active_tunnels
    if _active_tunnels >= cfg.max_concurrent_tunnels:
        return False
    _active_tunnels += 1
    return True


def _release_slot() -> None:
    global _active_tunnels
    _active_tunnels -= 1


async def handle_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
    cfg: MitmProxyConfig,
) -> None:
    """Оркестрация CONNECT-соединения через Client Registry (ADR-005 §7)."""
    client = resolve_client(target_host, cfg.clients)

    if client is None:
        if cfg.log_unmatched_hosts:
            logger.info(
                "proxy.unmatched_host host=%s action=%s",
                target_host,
                cfg.unmatched_host_action.value,
            )
        if cfg.unmatched_host_action is UnmatchedHostAction.REJECT:
            await respond_and_close(
                writer, 502, "Host not registered for interception"
            )
            return
        await _run_tunnel(reader, writer, target_host, target_port, cfg)
        return

    logger.info(
        "proxy.connection client_id=%s mode=%s host=%s",
        client.client_id,
        client.capture_mode.value,
        target_host,
    )

    if client.capture_mode is ProxyCaptureMode.PASSTHROUGH:
        await _run_tunnel(
            reader,
            writer,
            client.upstream_host or target_host,
            target_port,
            cfg,
        )
        return

    # INTERCEPT: существующая MITM-логика (self-signed CA, декрипт, inject, форвард)
    _warn_inject_hook_unused(client)
    await mitm_intercept(reader, writer, target_host, client, target_port, cfg)


# Профили, для которых уже сообщено о недиспетчеризуемом inject_hook — предупреждаем
# один раз на клиента, а не на каждое соединение.
_inject_hook_warned: set[str] = set()


def _warn_inject_hook_unused(client: ClientProfile) -> None:
    """Сообщить, что ``inject_hook`` объявлен в конфиге, но ещё не вызывается.

    ``validate_mitm_proxy_config`` требует ``inject_hook`` для INTERCEPT, однако
    MITM-адаптер пока не диспетчеризует его (наблюдение идёт через
    ``observe``/``observe_raw`` в ``mnemo_mitm_proxy``). Молчать об этом нельзя:
    конфиг обещает обработчик, которого в тракте нет.
    """
    if not client.inject_hook or client.client_id in _inject_hook_warned:
        return
    _inject_hook_warned.add(client.client_id)
    logger.warning(
        "proxy.inject_hook_not_dispatched client_id=%s hook=%s — "
        "перехват работает, но обработчик не вызывается",
        client.client_id,
        client.inject_hook,
    )


async def _run_tunnel(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    upstream_host: str,
    upstream_port: int,
    cfg: MitmProxyConfig,
) -> None:
    if not _try_acquire_slot(cfg):
        logger.info(
            "proxy.tunnel_error type=max_concurrent_exceeded host=%s:%s "
            "max=%d",
            upstream_host,
            upstream_port,
            cfg.max_concurrent_tunnels,
        )
        await respond_and_close(writer, 503, "Too many concurrent tunnels")
        return
    try:
        await raw_tcp_tunnel(
            reader,
            writer,
            upstream_host,
            upstream_port,
            connect_timeout=cfg.connect_timeout_sec,
            idle_timeout=cfg.tunnel_idle_timeout_sec,
        )
    except TimeoutError:
        logger.info(
            "proxy.tunnel_error type=connect_timeout host=%s:%s",
            upstream_host,
            upstream_port,
        )
        await respond_and_close(writer, 504, "Upstream connect timeout")
    except (OSError, ConnectionError) as exc:
        logger.warning(
            "proxy.tunnel_error type=upstream_reset host=%s:%s error=%s",
            upstream_host,
            upstream_port,
            exc,
        )
        await respond_and_close(writer, 502, "Upstream unavailable")
    finally:
        _release_slot()


async def raw_tcp_tunnel(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    upstream_host: str,
    upstream_port: int,
    connect_timeout: float = 10.0,
    idle_timeout: float = 0.0,
) -> None:
    """Прозрачный TCP-туннель без расшифровки (fail-open passthrough).

    Читает остаток CONNECT-заголовков, отвечает ``200 Connection Established``
    и гоняет байты в обе стороны постранично. ``upstream_writer`` всегда
    закрывается; клиентский ``writer`` закрывает вызывающий (server handler).

    ``idle_timeout`` — максимальное время полного бездействия (в обе стороны),
    после которого туннель закрывается. Отсчёт сбрасывается каждым переданным
    чанком, поэтому долгий LLM-стрим никогда не попадает под нож: пока идут
    токены, туннель живой. ``0`` = без лимита.

    NB: это НЕ потолок времени жизни соединения. Ровно такая подмена (обёртка
    ``wait_for`` вокруг обоих релеев) и рвала многоминутные генерации на
    середине, отдавая клиенту ``Connection error``.
    """
    upstream_reader, upstream_writer = await asyncio.wait_for(
        asyncio.open_connection(upstream_host, upstream_port),
        timeout=connect_timeout,
    )
    try:
        await _drain_connect_headers(reader)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await _run_relays(
            reader, writer, upstream_reader, upstream_writer,
            idle_timeout, upstream_host, upstream_port,
        )
        logger.debug("tunnel closed cleanly for %s:%s", upstream_host, upstream_port)
    except Exception:
        logger.exception("tunnel aborted for %s:%s", upstream_host, upstream_port)
    finally:
        await _close_quietly(upstream_writer)


async def _run_relays(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
    idle_timeout: float,
    upstream_host: str,
    upstream_port: int,
) -> None:
    """Гонять оба направления до закрытия одного из концов или idle-таймаута.

    Правило разрыва разное для двух исходов, и смешивать их нельзя:

    * релей **завершился штатно** (прочитал EOF) — второй продолжает работать.
      Это обычный half-close: клиент дослал запрос и молчит, пока сервер
      стримит ответ. Снести здесь сиблинга — снова порезать долгий стрим.
    * релей **упал с ошибкой** — туннель мёртв, сиблинг снимается сразу.
      Раньше ``gather`` без ``return_exceptions`` пробрасывал исключение
      наружу и оставлял второй релей сиротой писать в writer, который
      вызывающий уже закрывал.
    """
    activity = _Activity()
    tasks = [
        asyncio.create_task(_relay(reader, upstream_writer, activity)),
        asyncio.create_task(_relay(upstream_reader, writer, activity)),
    ]
    watchdog: asyncio.Task | None = None
    if idle_timeout and idle_timeout > 0:
        watchdog = asyncio.create_task(
            _idle_watchdog(
                activity, idle_timeout, tasks, f"{upstream_host}:{upstream_port}"
            )
        )
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            failed = False
            for t in done:
                exc = t.exception() if not t.cancelled() else None
                if exc is not None:
                    failed = True
                    logger.warning(
                        "proxy.relay_error host=%s:%s error=%r",
                        upstream_host,
                        upstream_port,
                        exc,
                    )
            if failed:
                break
    finally:
        for t in (*tasks, watchdog):
            if t is not None and not t.done():
                t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(
                *(t for t in (*tasks, watchdog) if t is not None),
                return_exceptions=True,
            )


class _Activity:
    """Отметка времени последнего переданного байта в любом направлении."""

    __slots__ = ("ts",)

    def __init__(self) -> None:
        self.ts = time.monotonic()

    def touch(self) -> None:
        self.ts = time.monotonic()


async def _idle_watchdog(
    activity: _Activity,
    idle_timeout: float,
    tasks: list[asyncio.Task],
    label: str,
) -> None:
    """Снять релеи, если в обе стороны не прошло ни байта за ``idle_timeout``.

    Общий и для passthrough, и для MITM-тракта — обе стороны должны мерить
    простой, а не время жизни соединения.
    """
    while True:
        idle_for = time.monotonic() - activity.ts
        if idle_for >= idle_timeout:
            logger.info(
                "proxy.tunnel_idle_timeout host=%s idle=%.0fs",
                label,
                idle_for,
            )
            for t in tasks:
                if not t.done():
                    t.cancel()
            return
        await asyncio.sleep(idle_timeout - idle_for)


async def _relay(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    activity: _Activity | None = None,
) -> None:
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
        logger.debug("tunnel relay reset (read side)")
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            dst.write_eof()


async def _drain_connect_headers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            return


async def _close_quietly(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    try:
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
    except Exception:
        pass


async def respond_and_close(
    writer: asyncio.StreamWriter,
    status: int = 502,
    reason: str = "Host not registered for interception",
) -> None:
    """Детерминированный HTTP-ответ с последующим закрытием (без RST)."""
    text = f"HTTP/1.1 {status} {reason}\r\nConnection: close\r\n\r\n"
    writer.write(text.encode())
    with contextlib.suppress(ConnectionResetError, OSError):
        await writer.drain()
    await _close_quietly(writer)


# ── INTERCEPT routing ──────────────────────────────────────────────────

_conductor = None


def set_conductor(conductor) -> None:
    global _conductor
    _conductor = conductor


async def mitm_intercept(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target_host: str,
    client: ClientProfile,
    target_port: int,
    cfg: MitmProxyConfig,
) -> None:
    """Направить INTERCEPT-клиента в существующий MITM-адаптер.

    Позиционные аргументы: ``(reader, writer, target_host, client, target_port,
    cfg)`` — ``client`` на позиции 3 (гарантия контракта из интеграционных
    тестов). Ленивый импорт исключает цикл с ``integration.mnemo_mitm_proxy``.

    ``client.upstream_host`` перекрывает хост из CONNECT (сертификат клиенту
    по-прежнему выписывается на ``target_host`` — иначе клиент отвергнет его по
    SNI). До этого поле молча игнорировалось.
    """
    from mnemostroma.integration.mnemo_mitm_proxy import handle_connect_mitm

    await handle_connect_mitm(
        reader,
        writer,
        target_host,
        target_port,
        conductor=_conductor,
        upstream_host=client.upstream_host or target_host,
        idle_timeout=cfg.tunnel_idle_timeout_sec,
    )
