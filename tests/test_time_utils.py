import pytest
from mnemostroma.tools.time_utils import unix_to_str, enrich_with_time

def test_unix_to_str_utc():
    # 1714210000 = 2024-04-27 09:26:40 UTC
    res = unix_to_str(1714210000, utc=True)
    assert res == "2024-04-27 09:26:40 UTC"

def test_unix_to_str_local():
    res = unix_to_str(1714210000, utc=False)
    assert "LOCAL" in res
    # Точное время зависит от таймзоны хоста, проверяем только суффикс

def test_enrich_normal():
    obj = {"created_at": 1714210000, "brief": "test"}
    res = enrich_with_time(obj)
    assert res["exact_time_str"] == "2024-04-27 09:26:40 UTC"
    assert res["exact_time_unix"] == 1714210000
    assert res["brief"] == "test"

def test_enrich_missing_ts():
    obj = {"brief": "test"}
    res = enrich_with_time(obj)
    assert "exact_time_str" not in res
    assert "exact_time_unix" not in res

def test_enrich_zero_ts():
    obj = {"created_at": 0, "brief": "test"}
    res = enrich_with_time(obj)
    assert "exact_time_str" not in res

def test_enrich_custom_field():
    obj = {"accessed_at": 1714210000}
    res = enrich_with_time(obj, ts_field="accessed_at")
    assert res["exact_time_str"] == "2024-04-27 09:26:40 UTC"

from mnemostroma.tools.time_utils import parse_exact_time_with_mask

def test_parse_mask_second():
    lo, hi = parse_exact_time_with_mask("14/04/26 21:18:55")
    assert lo is not None
    assert hi - lo == 1

def test_parse_mask_minute():
    lo, hi = parse_exact_time_with_mask("14/04/26 21:18:XX")
    assert lo is not None
    assert hi - lo == 60

def test_parse_mask_hour():
    lo, hi = parse_exact_time_with_mask("14/04/26 21:XX")
    assert lo is not None
    assert hi - lo == 3600

def test_parse_mask_day():
    lo, hi = parse_exact_time_with_mask("14/04/26")
    assert lo is not None
    assert hi - lo == 86400

def test_parse_iso_with_mask():
    lo, hi = parse_exact_time_with_mask("2026-04-14T21:18:XX")
    assert lo is not None
    assert hi - lo == 60

def test_parse_unix_str():
    lo, hi = parse_exact_time_with_mask("1714210000")
    assert lo == 1714210000
    assert hi == 1714210001

def test_parse_invalid():
    lo, hi = parse_exact_time_with_mask("yesterday")
    assert lo is None
    assert isinstance(hi, str)

def test_parse_year_too_old():
    # Год 2019 < 2020
    lo, hi = parse_exact_time_with_mask("14/04/19 21:18:55")
    assert lo is None
    assert isinstance(hi, str)

def test_parse_year_too_new():
    # Год 2036 > 2035
    lo, hi = parse_exact_time_with_mask("14/04/36 21:18:55")
    assert lo is None
    assert isinstance(hi, str)
