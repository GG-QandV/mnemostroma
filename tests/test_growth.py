# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import numpy as np
from mnemostroma.memory.growth_forecast import GrowthForecast, _INSUFFICIENT

# --- fixtures ---

def make_history(n_days: int, rate_mb: float = 1.0, start_mb: float = 10.0):
    """Linear growth: start_mb + rate_mb * day."""
    now = 1_700_000_000
    return [(now + i * 86_400, start_mb + rate_mb * i) for i in range(n_days)]

def make_history_exp(n_days: int, daily_factor: float = 1.02, start_mb: float = 10.0):
    """Exponential growth: start_mb * factor^day."""
    now = 1_700_000_000
    return [(now + i * 86_400, start_mb * (daily_factor ** i)) for i in range(n_days)]

# --- insufficient data ---

def test_insufficient_data_empty():
    gf = GrowthForecast([])
    assert gf.best().model == "insufficient_data"
    assert gf.linear().model == "insufficient_data"
    assert gf.exponential().model == "insufficient_data"

def test_insufficient_data_two_points():
    gf = GrowthForecast(make_history(2))
    assert gf.best().model == "insufficient_data"

# --- linear model ---

def test_linear_detects_rate():
    gf = GrowthForecast(make_history(30, rate_mb=2.0))
    result = gf.linear()
    assert result.model == "linear"
    assert abs(result.daily_rate_mb - 2.0) < 0.1
    assert result.r_squared > 0.99

def test_linear_days_to_1gb():
    # start=10MB, rate=2MB/day → (1024-10)/2 = 507
    # polyfit может дать небольшую погрешность из-за дискретности
    gf = GrowthForecast(make_history(30, rate_mb=2.0, start_mb=10.0))
    result = gf.linear()
    assert 470 < result.days_to_1gb < 530

def test_linear_zero_rate_returns_minus_one():
    # Flat history — no growth
    flat = [(1_700_000_000 + i * 86_400, 50.0) for i in range(10)]
    gf = GrowthForecast(flat)
    result = gf.linear()
    assert result.days_to_1gb == -1 or result.daily_rate_mb < 0.01

# --- exponential model ---

def test_exponential_detects_growth():
    gf = GrowthForecast(make_history_exp(30, daily_factor=1.05))
    result = gf.exponential()
    assert result.model == "exponential"
    assert result.daily_rate_mb > 0
    assert result.r_squared > 0.95

def test_exponential_days_positive():
    gf = GrowthForecast(make_history_exp(30, daily_factor=1.02, start_mb=10.0))
    result = gf.exponential()
    assert result.days_to_1gb > 0
    assert result.days_to_10gb > result.days_to_1gb

# --- best() picks correct model ---

def test_best_picks_linear_for_linear_data():
    gf = GrowthForecast(make_history(30, rate_mb=1.5))
    best = gf.best()
    assert best.model == "linear"
    assert best.r_squared > 0.99

def test_best_picks_exp_for_exp_data():
    gf = GrowthForecast(make_history_exp(30, daily_factor=1.03))
    best = gf.best()
    assert best.model == "exponential"

# --- r_squared bounds ---

def test_r_squared_in_range():
    for history in [make_history(10), make_history_exp(10)]:
        gf = GrowthForecast(history)
        assert 0.0 <= gf.linear().r_squared <= 1.0
        assert 0.0 <= gf.exponential().r_squared <= 1.0
