# SPDX-License-Identifier: FSL-1.1-MIT
"""Precision Guard — value-level artifact comparison (Phase 11.D).

Extracts URLs, version numbers, and numeric metrics from agent text and
compares them against the RAM-cached precision_log. On discrepancy →
precision_warnings field appears in ctx_active() next turn.

Zero ONNX calls. Pure regex. Runs synchronously at Observer Step 0.5.
One-turn lag by design (same pattern as Guardian/Open Loop).
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.subconscious.precision_guard")

# Reuse patterns from filter.py — precision-relevant types (expanded)
_CHECK_TYPES = ("link", "version", "number", "hash", "ip", "port", "uuid", "api", "config")

_COMPILED: Dict[str, re.Pattern] = {}


def _get_compiled() -> Dict[str, re.Pattern]:
    """Lazy-compile patterns from filter.py to avoid circular import at module load."""
    global _COMPILED
    if not _COMPILED:
        from ..observer.filter import PRECISION_PATTERNS
        _COMPILED = {
            name: re.compile(pattern)
            for name, pattern in PRECISION_PATTERNS.items()
            if name in _CHECK_TYPES
        }
    return _COMPILED


def precision_extract(text: str) -> List[Dict[str, Any]]:
    """Extract precision artifacts from text.

    Returns list of {type, value, raw} for link/version/number types only.
    """
    results = []
    for ptype, pattern in _get_compiled().items():
        for match in pattern.finditer(text):
            results.append({
                "type": ptype,
                "value": match.group(0).strip(),
                "raw": match.group(0),
            })
    return results


def _derive_context_tag(artifact: Dict[str, Any], text: str) -> str:
    """Heuristic: extract the last meaningful word before the artifact in text.

    Used as a grouping key: same artifact type + same context → same slot.
    Returns "unknown" if no meaningful word found.
    """
    value = artifact["value"]
    idx = text.find(value)
    if idx == -1:
        return "unknown"
    prefix = text[max(0, idx - 40):idx].strip()
    words = [w for w in prefix.split() if len(w) > 3 and w.isalpha()]
    return words[-1].lower() if words else "unknown"


def _same_value(a: str, b: str, ptype: str) -> bool:
    """True if a and b are considered the same value for ptype.

    link:    same netloc + path (ignores query/fragment)
    version: strip leading 'v/V', compare full string
    number:  compare numeric part only, normalise comma→dot
    hash:    compare as-is (git hashes are deterministic)
    ip:      extract IP and port, compare separately
    uuid:    canonical lowercase comparison
    api:     normalize slashes and compare path
    config:  compare key + value
    """
    if ptype == "link":
        from urllib.parse import urlparse
        try:
            pa, pb = urlparse(a), urlparse(b)
            return pa.netloc == pb.netloc and pa.path == pb.path
        except:
            return a == b
    if ptype == "version":
        return a.lstrip("vV") == b.lstrip("vV")
    if ptype == "number":
        na = re.search(r"[\d.,]+", a)
        nb = re.search(r"[\d.,]+", b)
        if na and nb:
            return na.group(0).replace(",", ".") == nb.group(0).replace(",", ".")
    if ptype == "hash":
        return a.lower() == b.lower()
    if ptype == "ip":
        # Compare IP without port
        ip_a = re.match(r"(\d+\.\d+\.\d+\.\d+)", a)
        ip_b = re.match(r"(\d+\.\d+\.\d+\.\d+)", b)
        if ip_a and ip_b:
            return ip_a.group(0) == ip_b.group(0)
    if ptype == "uuid":
        return a.lower() == b.lower()
    if ptype == "api":
        # Normalize path separators
        return a.replace("\\", "/").rstrip("/") == b.replace("\\", "/").rstrip("/")
    if ptype == "config":
        # Extract key from "key=value" and compare
        key_a = re.match(r"(\w+)\s*[:=]", a)
        key_b = re.match(r"(\w+)\s*[:=]", b)
        if key_a and key_b:
            return key_a.group(1) == key_b.group(1)
    return a == b


def precision_guard(text: str, ctx: "SystemContext") -> None:
    """Extract precision artifacts from text and compare against precision_ram.

    Appends warnings to ctx.precision_warnings in-place.
    Called synchronously at Observer Step 0.5 — no ONNX, no async.

    Args:
        text: Stripped agent output text.
        ctx: System context with precision_ram and precision_warnings.
    """
    precision_ram = getattr(ctx, "precision_ram", None)
    precision_warnings = getattr(ctx, "precision_warnings", None)
    if precision_ram is None or precision_warnings is None:
        return

    artifacts = precision_extract(text)
    for artifact in artifacts:
        ctx_tag = _derive_context_tag(artifact, text)
        key: Tuple[str, str] = (artifact["type"], ctx_tag)
        stored = precision_ram.get(key)
        if stored and not _same_value(artifact["value"], stored["value"], artifact["type"]):
            precision_warnings.append({
                "type": artifact["type"],
                "current_value": artifact["value"],
                "stored_value": stored["value"],
                "context_tag": ctx_tag,
                "stored_at": stored.get("stored_at", 0),
                "note": f"{artifact['type']} changed since last recorded",
            })
            logger.debug(
                "precision.mismatch | type=%s ctx=%s old=%s new=%s",
                artifact["type"], ctx_tag, stored["value"], artifact["value"],
            )
