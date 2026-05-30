import pytest
from unittest.mock import MagicMock, AsyncMock
from mnemostroma.tools.read import ctx_search


class MockSessionBrief:
    """Minimal SessionBrief stub for RAM index mock."""
    def __init__(self, session_id, brief, created_at, tags=None, importance="background"):
        self.session_id = session_id
        self.brief = brief
        self.created_at = created_at
        self.tags = tags or []
        self.importance = importance
        self.conflict_flag = False
        self.archived = False
        self.score = 0.5         # required by legacy path sort
        self.age_signal = None   # required by legacy path filter


def _make_result(data):
    """Build a minimal Result mock with is_ok/unwrap pattern."""
    r = MagicMock()
    r.is_ok.return_value = True
    r.unwrap.return_value = data
    return r


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()

    # RAM index with two sessions at known timestamps
    ram_data = {
        "s1": MockSessionBrief("s1", "ram session", 1714210000, tags=["test"]),
        "s2": MockSessionBrief("s2", "another",     1714210050, tags=["other"]),
    }
    ctx.ram_index = MagicMock()
    ctx.ram_index.values.return_value = list(ram_data.values())
    ctx.ram_index.__contains__ = lambda self, k: k in ram_data
    ctx.ram_index.__getitem__ = lambda self, k: ram_data[k]

    # session_repo: search_by_time_window returns empty by default
    ctx.session_repo = MagicMock()
    ctx.session_repo.search_by_time_window = AsyncMock(
        return_value=_make_result([])
    )

    # log_event needs ctx.config – MagicMock handles it silently
    return ctx


# ── Plan B: exact_time parameter ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exact_time_invalid_format(mock_ctx):
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="invalid")
    assert isinstance(res, list)
    assert len(res) == 1
    assert "error" in res[0]
    assert "exact_time_received" in res[0]


@pytest.mark.asyncio
async def test_no_tags_no_exact_time(mock_ctx):
    with pytest.raises(ValueError):
        await ctx_search(tags=[], ctx=mock_ctx)


@pytest.mark.asyncio
async def test_exact_time_second_mask_ram_hit(mock_ctx):
    # Unix ts "1714210000" → interval [1714210000, 1714210001)
    # s1.created_at == 1714210000 → matches
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="1714210000")
    assert isinstance(res, dict)
    assert "results" in res
    assert len(res["results"]) == 1
    assert res["results"][0]["session_id"] == "s1"
    assert "exact_time_str" in res["results"][0]


@pytest.mark.asyncio
async def test_exact_time_miss_ram_sql_fallback(mock_ctx):
    # Timestamp far from s1/s2 → RAM miss → SQL fallback returns one row
    sql_row = {"session_id": "sql1", "created_at": 1700000010, "brief": "from sql"}
    mock_ctx.session_repo.search_by_time_window = AsyncMock(
        return_value=_make_result([sql_row])
    )
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="1700000000")
    assert isinstance(res, dict)
    assert len(res["results"]) == 1
    assert res["results"][0]["session_id"] == "sql1"


@pytest.mark.asyncio
async def test_exact_time_miss_both(mock_ctx):
    # RAM miss + SQL returns [] → empty results list
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="1000000000")
    assert isinstance(res, dict)
    assert res["results"] == []


@pytest.mark.asyncio
async def test_exact_time_with_tags_filter(mock_ctx):
    # s2 has tag "other", interval [1714210050, 1714210051) → only s2 matches
    res = await ctx_search(tags=["other"], ctx=mock_ctx, exact_time="1714210050")
    assert isinstance(res, dict)
    assert len(res["results"]) == 1
    assert res["results"][0]["session_id"] == "s2"


@pytest.mark.asyncio
async def test_exact_time_soft_limit_warning(mock_ctx):
    # 40 results from SQL → warning present, compact_mode=False
    sql_rows = [{"session_id": f"s{i}", "created_at": 1700000010, "brief": "b"} for i in range(40)]
    mock_ctx.session_repo.search_by_time_window = AsyncMock(
        return_value=_make_result(sql_rows)
    )
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="1700000000")
    assert isinstance(res, dict)
    assert len(res["results"]) == 40
    assert res["warning"] is not None
    assert "Large result set" in res["warning"]
    assert res["compact_mode"] is False


@pytest.mark.asyncio
async def test_exact_time_hard_limit_compact(mock_ctx):
    # 60 results → compact_mode=True, extra field stripped, hint present
    sql_rows = [
        {"session_id": f"s{i}", "created_at": 1700000010, "brief": "b", "extra": "data"}
        for i in range(60)
    ]
    mock_ctx.session_repo.search_by_time_window = AsyncMock(
        return_value=_make_result(sql_rows)
    )
    res = await ctx_search(tags=[], ctx=mock_ctx, exact_time="1700000000")
    assert isinstance(res, dict)
    assert len(res["results"]) == 60
    assert res["compact_mode"] is True
    assert res["warning"] is not None
    assert res["hint"] is not None
    # compact: "extra" dropped, "exact_time_str" injected
    first = res["results"][0]
    assert "extra" not in first
    assert "exact_time_str" in first
