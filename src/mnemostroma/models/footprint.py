# SPDX-License-Identifier: FSL-1.1-MIT
"""Process-wide tracker of ONNX model memory footprints.

Why this exists: `onnx_baseline_mb` used to be a single RSS snapshot taken once at
bootstrap. Models load lazily, so anything created after that snapshot counted as
*evictable* memory in `Dissolver._maybe_evict` (`evictable_mb = rss - baseline`) —
and sessions were evicted to make room for model weights that eviction cannot free.

Each session records its own RSS delta here at creation and drops it at release, so
the baseline follows the actual set of loaded models. The tracker is module-level on
purpose: engines and NER/reranker wrappers have no SystemContext to reach through.

Without psutil the tracker degrades to zeros — callers keep working, the baseline
simply stays static as before.
"""
import logging
import os
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_footprints: dict[str, float] = {}


def _rss_mb() -> float | None:
    """Current process RSS in MB, or None when psutil is unavailable."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return None


@contextmanager
def measure(name: str):
    """Record the RSS delta produced by loading a model under `name`.

    Re-measuring the same name replaces the previous value: a reloaded model has
    one footprint, not two.
    """
    before = _rss_mb()
    try:
        yield
    finally:
        after = _rss_mb()
        if before is None or after is None:
            return
        delta = max(0.0, after - before)
        with _lock:
            _footprints[name] = delta
        logger.info("footprint.measure | %s = %.1f MB (total %.1f MB)", name, delta, total_mb())


def release(name: str) -> None:
    """Drop a footprint after the model session is released."""
    with _lock:
        removed = _footprints.pop(name, None)
    if removed is not None:
        logger.info("footprint.release | %s -%.1f MB (total %.1f MB)", name, removed, total_mb())


def total_mb() -> float:
    with _lock:
        return sum(_footprints.values())


def snapshot() -> dict[str, float]:
    """Copy of the current per-model footprints — for diagnostics and health output."""
    with _lock:
        return dict(_footprints)


def reset() -> None:
    """Drop all footprints. Tests only."""
    with _lock:
        _footprints.clear()
