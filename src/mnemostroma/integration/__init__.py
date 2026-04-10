# SPDX-License-Identifier: FSL-1.1-MIT
# Lazy imports: proxy.py тянет ..core и ..tools.read — не грузим при старте пакета,
# только когда кто-то явно запрашивает ConductorProxy / MemoryBlock.

__all__ = ["ConductorProxy", "MemoryBlock"]


def __getattr__(name: str):
    if name == "ConductorProxy":
        from .proxy import ConductorProxy
        return ConductorProxy
    if name == "MemoryBlock":
        from .proxy import MemoryBlock
        return MemoryBlock
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
