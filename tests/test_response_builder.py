import pytest
from mnemostroma.tools.response_builder import build_search_response, SOFT_LIMIT, HARD_LIMIT

def test_build_small_response():
    results = [{"session_id": f"s_{i}", "brief": "b", "created_at": 100} for i in range(20)]
    res = build_search_response(results, total_matched=20)
    assert res["total_matched"] == 20
    assert res["compact_mode"] is False
    assert res["warning"] is None
    assert len(res["results"]) == 20

def test_build_soft_limit():
    results = [{"session_id": f"s_{i}", "brief": "b", "created_at": 100} for i in range(40)]
    res = build_search_response(results, total_matched=40)
    assert res["compact_mode"] is False
    assert "Large result set" in res["warning"]
    assert len(res["results"]) == 40

def test_build_hard_limit():
    results = [{"session_id": f"s_{i}", "brief": "b", "created_at": 100, "extra": "data", "exact_time_str": "time"} for i in range(60)]
    res = build_search_response(results, total_matched=60)
    assert res["compact_mode"] is True
    assert "LARGE RESPONSE" in res["warning"]
    assert "Use ctx_full" in res["hint"]
    
    # Check compact format
    first = res["results"][0]
    assert "session_id" in first
    assert "brief" in first
    assert "extra" not in first

def test_build_empty():
    res = build_search_response([], total_matched=0)
    assert res["total_matched"] == 0
    assert res["compact_mode"] is False
    assert res["warning"] is None
