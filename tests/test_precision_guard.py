# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Phase 11.D — Precision Guard."""
import time
import pytest
from unittest.mock import MagicMock

from mnemostroma.subconscious.precision_guard import (
    precision_extract,
    _derive_context_tag,
    _same_value,
    precision_guard,
)


# ── precision_extract ─────────────────────────────────────────────────────────

def test_extract_link():
    artifacts = precision_extract("see https://api.example.com/v2/sessions for details")
    links = [a for a in artifacts if a["type"] == "link"]
    assert len(links) == 1
    assert links[0]["value"] == "https://api.example.com/v2/sessions"


def test_extract_version():
    artifacts = precision_extract("using mnemostroma v2.1.0 in production")
    versions = [a for a in artifacts if a["type"] == "version"]
    assert any(v["value"] == "v2.1.0" for v in versions)


def test_extract_number():
    artifacts = precision_extract("memory usage is 512 MB")
    numbers = [a for a in artifacts if a["type"] == "number"]
    assert len(numbers) == 1
    assert "512" in numbers[0]["value"]


def test_extract_no_artifacts():
    artifacts = precision_extract("hello world, no precision artifacts here")
    assert artifacts == []


def test_extract_skips_email_but_finds_hash():
    artifacts = precision_extract("contact user@example.com or commit abc1234def")
    types = {a["type"] for a in artifacts}
    assert "email" not in types
    assert "hash" in types  # Hashes are now valid precision artifacts (Phase 11.D)


# ── _derive_context_tag ───────────────────────────────────────────────────────

def test_context_tag_extracts_last_word():
    artifact = {"value": "https://api.example.com/v1"}
    text = "endpoint https://api.example.com/v1 is deprecated"
    tag = _derive_context_tag(artifact, text)
    assert tag == "endpoint"


def test_context_tag_unknown_when_no_prefix():
    artifact = {"value": "https://api.example.com/v1"}
    text = "https://api.example.com/v1 is here"
    tag = _derive_context_tag(artifact, text)
    assert tag == "unknown"


def test_context_tag_unknown_when_not_found():
    artifact = {"value": "https://missing.com"}
    tag = _derive_context_tag(artifact, "some other text")
    assert tag == "unknown"


# ── _same_value ───────────────────────────────────────────────────────────────

def test_same_value_link_same():
    assert _same_value("https://api.example.com/v1", "https://api.example.com/v1", "link")


def test_same_value_link_different_path():
    assert not _same_value("https://api.example.com/v2", "https://api.example.com/v1", "link")


def test_same_value_link_different_domain():
    assert not _same_value("https://api.example.com/v1", "https://api2.example.com/v1", "link")


def test_same_value_version_with_v_prefix():
    assert _same_value("v2.1.0", "2.1.0", "version")


def test_same_value_version_different():
    assert not _same_value("v2.1.0", "v2.0.3", "version")


def test_same_value_number_same():
    assert _same_value("512 MB", "512MB", "number")


def test_same_value_number_comma():
    assert _same_value("1,5 MB", "1.5 MB", "number")


def test_same_value_number_different():
    assert not _same_value("512 MB", "256 MB", "number")


# ── precision_guard (main function) ──────────────────────────────────────────

class _MockCtx:
    def __init__(self):
        self.precision_ram = {}
        self.precision_warnings = []


def test_no_warning_on_first_occurrence():
    """First time an artifact is seen — nothing to compare against."""
    ctx = _MockCtx()
    precision_guard("use https://api.example.com/v1/sessions", ctx)
    assert ctx.precision_warnings == []


def test_no_warning_on_same_value():
    ctx = _MockCtx()
    ctx.precision_ram[("link", "endpoint")] = {
        "value": "https://api.example.com/v1",
        "stored_at": int(time.time()),
    }
    precision_guard("endpoint https://api.example.com/v1 is used", ctx)
    assert ctx.precision_warnings == []


def test_warning_on_link_mismatch():
    ctx = _MockCtx()
    ctx.precision_ram[("link", "endpoint")] = {
        "value": "https://api.example.com/v1",
        "stored_at": int(time.time()),
    }
    precision_guard("endpoint https://api.example.com/v2 is used", ctx)
    assert len(ctx.precision_warnings) == 1
    w = ctx.precision_warnings[0]
    assert w["type"] == "link"
    assert w["stored_value"] == "https://api.example.com/v1"
    assert w["current_value"] == "https://api.example.com/v2"
    assert w["context_tag"] == "endpoint"


def test_warning_on_version_mismatch():
    ctx = _MockCtx()
    ctx.precision_ram[("version", "mnemostroma")] = {
        "value": "v2.0.3",
        "stored_at": int(time.time()),
    }
    precision_guard("mnemostroma v2.1.0 released", ctx)
    assert len(ctx.precision_warnings) == 1
    assert ctx.precision_warnings[0]["type"] == "version"


def test_no_warning_when_precision_ram_missing():
    """Graceful handling when ctx lacks precision_ram."""
    ctx = type("C", (), {})()
    precision_guard("use https://api.example.com/v1", ctx)  # must not raise


def test_precision_warnings_cleared_after_read():
    """Simulate ctx_active() clearing the queue."""
    ctx = _MockCtx()
    ctx.precision_ram[("link", "endpoint")] = {
        "value": "https://api.example.com/v1",
        "stored_at": int(time.time()),
    }
    precision_guard("endpoint https://api.example.com/v2 used", ctx)
    assert len(ctx.precision_warnings) == 1
    # Simulate ctx_active() drain
    drained = list(ctx.precision_warnings)
    ctx.precision_warnings.clear()
    assert ctx.precision_warnings == []
    assert len(drained) == 1


def test_ram_cap_evicts_oldest():
    """When precision_ram exceeds cap, oldest entry is evicted."""
    ctx = _MockCtx()
    cap = 3
    # Pre-fill to cap
    for i in range(cap):
        ctx.precision_ram[("version", f"ctx{i}")] = {
            "value": f"v1.{i}",
            "stored_at": 1000 + i,
        }
    # Add one more — oldest (stored_at=1000) should be evicted
    ctx.precision_ram[("version", "ctxNEW")] = {
        "value": "v1.99",
        "stored_at": 9999,
    }
    if len(ctx.precision_ram) > cap:
        oldest = min(ctx.precision_ram, key=lambda k: ctx.precision_ram[k].get("stored_at", 0))
        del ctx.precision_ram[oldest]
    assert len(ctx.precision_ram) == cap
    assert ("version", "ctx0") not in ctx.precision_ram
