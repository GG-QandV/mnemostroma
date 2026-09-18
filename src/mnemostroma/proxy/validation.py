# SPDX-License-Identifier: FSL-1.1-MIT
"""Config validation for the scoped MITM proxy (ADR-005 §10).

Выполняется при загрузке конфига (``Config.load()``), не at request time —
невалидный конфиг не даёт процессу стартовать.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import fields as dataclass_fields
from pathlib import Path

from mnemostroma.proxy.models import MitmProxyConfig, ProxyCaptureMode

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Порты, занятые другими транспортами mnemostroma:
# 8762 (http_read), 8764 (MITM), 8765/8766 (SSE), 8767 (passthrough),
# 8768 (http), 8780 (gateway). 8764 — собственный порт прокси, разрешён.
_MITM_RESERVED_PORTS: frozenset[int] = frozenset(
    {8762, 8765, 8766, 8767, 8768, 8780}
)

_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {"api_key", "authorization", "token", "secret", "password"}
)


class MitmProxyConfigError(Exception):
    pass


class MitmProxyHostCollisionError(MitmProxyConfigError):
    pass


class MitmProxyReservedPortError(MitmProxyConfigError):
    pass


class MitmProxyCredentialLeakError(MitmProxyConfigError):
    pass


def validate_mitm_proxy_config(
    cfg: MitmProxyConfig,
    reserved_ports: Set[int],
    raw_clients: list[dict] | None = None,
) -> None:
    """Провалидировать конфиг MITM-прокси.

    ``raw_clients`` — сырые словари клиентов до нормализации в
    :class:`ClientProfile`. Нужны для проверки на секреты: ``from_dict``
    молча выбрасывает незнакомые ключи, поэтому по готовому dataclass'у
    ``api_key`` в конфиге уже не увидеть.
    """
    if cfg.port in reserved_ports:
        raise MitmProxyReservedPortError(cfg.port)
    if cfg.host not in _LOOPBACK_HOSTS:
        raise MitmProxyConfigError(f"non-loopback host not allowed in R1: {cfg.host}")

    seen_exact: dict[str, str] = {}
    seen_wildcard: dict[str, str] = {}
    for client in cfg.clients:
        if not client.match_hosts:
            raise MitmProxyConfigError(
                f"{client.client_id}: match_hosts must not be empty"
            )
        for pattern in client.match_hosts:
            bucket = seen_wildcard if pattern.startswith("*.") else seen_exact
            key = pattern.lower()
            if key in bucket and bucket[key] != client.client_id:
                raise MitmProxyHostCollisionError(
                    f"host pattern '{pattern}' claimed by both "
                    f"'{bucket[key]}' and '{client.client_id}'"
                )
            bucket[key] = client.client_id

        if client.capture_mode is ProxyCaptureMode.INTERCEPT and not client.inject_hook:
            raise MitmProxyConfigError(
                f"{client.client_id}: capture_mode=intercept requires inject_hook"
            )

    _reject_credential_keys(cfg, raw_clients)


def _reject_credential_keys(
    cfg: MitmProxyConfig, raw_clients: list[dict] | None = None
) -> None:
    """Не дать положить секрет в реестр прокси.

    Поля самого ``ClientProfile`` статичны, так что проверка по
    ``dataclass_fields`` не могла сработать никогда — она осталась как
    защита от будущего расширения модели. Реальную работу делает обход
    сырых словарей.
    """
    for client in cfg.clients:
        for f in dataclass_fields(client):
            if f.name.lower() in _FORBIDDEN_KEYS:
                raise MitmProxyCredentialLeakError(client.client_id)

    for raw in raw_clients or []:
        if not isinstance(raw, dict):
            continue
        for key in raw:
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise MitmProxyCredentialLeakError(
                    f"{raw.get('client_id', '<unnamed>')}: секрет в поле '{key}' — "
                    "креденшелы берутся из окружения, не из конфига прокси"
                )


def load_mitm_proxy_config_from_file(
    path: str | Path,
    reserved_ports: Set[int] | None = None,
) -> MitmProxyConfig:
    """Загрузить и провалидировать секцию ``mitm_proxy`` из JSON-файла.

    Бросает :class:`MitmProxyConfigError` при невалидной конфигурации.
    """
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    section = data.get("mitm_proxy")
    if section is None:
        raise MitmProxyConfigError(f"'{path}' does not contain a 'mitm_proxy' section")

    cfg = MitmProxyConfig.from_dict(section)
    raw_clients = [c for c in section.get("clients", []) if isinstance(c, dict)]
    validate_mitm_proxy_config(
        cfg,
        reserved_ports=set(reserved_ports or _MITM_RESERVED_PORTS),
        raw_clients=raw_clients,
    )
    return cfg
