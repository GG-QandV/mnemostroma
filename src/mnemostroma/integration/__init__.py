# SPDX-License-Identifier: FSL-1.1-MIT
# Lazy imports — proxy.py not loaded until first use
__all__ = ["ConductorProxy", "MemoryBlock"]

def __getattr__(name: str):
    if name in ("ConductorProxy", "MemoryBlock"):
        from .proxy import ConductorProxy, MemoryBlock
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
