# SPDX-License-Identifier: FSL-1.1-MIT
"""Client registry host matching (ADR-005 §6).

Приоритет: exact match > наиболее специфичный wildcard suffix match.
Регистронезависимо. Отключённые (enabled=False) профили игнорируются.
"""

from __future__ import annotations

from mnemostroma.proxy.models import ClientProfile

_WILDCARD_PREFIX = "*."


def resolve_client(
    target_host: str,
    registry: tuple[ClientProfile, ...],
) -> ClientProfile | None:
    """Сопоставить ``target_host`` ровно одному клиенту либо ``None``.

    Exact match всегда приоритетнее wildcard независимо от порядка объявления.
    Среди wildcard-паттернов побеждает самый специфичный (самый длинный suffix).
    """
    host = target_host.lower().rstrip(".")
    candidates = [c for c in registry if c.enabled]

    for c in candidates:
        exact = [h.lower() for h in c.match_hosts if not h.startswith(_WILDCARD_PREFIX)]
        if host in exact:
            return c

    best: tuple[int, ClientProfile] | None = None
    for c in candidates:
        for pattern in c.match_hosts:
            if pattern.startswith(_WILDCARD_PREFIX):
                suffix = pattern[1:].lower()  # ".example.com"
                if host.endswith(suffix) and (
                    best is None or len(suffix) > best[0]
                ):
                    best = (len(suffix), c)
    return best[1] if best else None
