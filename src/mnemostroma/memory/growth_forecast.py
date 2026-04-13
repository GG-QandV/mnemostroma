# SPDX-License-Identifier: FSL-1.1-MIT
"""
GrowthForecast — two-model (linear + exponential) DB size forecasting.
Uses historical snapshots from db_snapshots table in logs.db.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class ForecastResult:
    model: str            # "linear" | "exponential" | "insufficient_data"
    daily_rate_mb: float  # MB/day at current rate
    days_to_1gb: int      # -1 means "never at this rate"
    days_to_10gb: int     # -1 means "never at this rate"
    r_squared: float      # goodness of fit, 0.0–1.0


_INSUFFICIENT = ForecastResult(
    model="insufficient_data",
    daily_rate_mb=0.0,
    days_to_1gb=-1,
    days_to_10gb=-1,
    r_squared=0.0,
)


class GrowthForecast:
    """
    Fits linear and exponential models to a time series of DB sizes.

    Usage:
        history = [(unix_ts_1, size_mb_1), (unix_ts_2, size_mb_2), ...]
        gf = GrowthForecast(history)
        best = gf.best()   # ForecastResult with higher R²
    """

    MIN_POINTS = 3  # require at least 3 snapshots for a meaningful fit

    def __init__(self, history: List[Tuple[int, float]]) -> None:
        """
        Args:
            history: list of (unix_timestamp_seconds, total_size_mb) tuples,
                     sorted ascending by timestamp.
        """
        self._ok = len(history) >= self.MIN_POINTS
        if not self._ok:
            return

        ts = np.array([h[0] for h in history], dtype=float)
        sizes = np.array([h[1] for h in history], dtype=float)

        # Normalise time to days from the first snapshot
        self._days: np.ndarray = (ts - ts[0]) / 86_400.0
        self._sizes: np.ndarray = sizes
        self._current_mb: float = float(sizes[-1])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def linear(self) -> ForecastResult:
        """Fit y = a*t + b."""
        if not self._ok:
            return _INSUFFICIENT

        coeffs = np.polyfit(self._days, self._sizes, 1)
        rate = float(coeffs[0])  # MB per day
        predicted = np.polyval(coeffs, self._days)
        r2 = self._r_squared(self._sizes, predicted)

        current = self._current_mb

        def days_to_linear(target_mb: float) -> int:
            if rate <= 0:
                return -1
            remaining = target_mb - current
            if remaining <= 0:
                return 0
            return int(remaining / rate)

        return ForecastResult(
            model="linear",
            daily_rate_mb=round(rate, 3),
            days_to_1gb=days_to_linear(1_024.0),
            days_to_10gb=days_to_linear(10_240.0),
            r_squared=round(r2, 3),
        )

    @staticmethod
    def _days_to(target_mb: float, rate_mb_per_day: float) -> int:
        """Unused — kept for API compatibility."""
        return -1
    def exponential(self) -> ForecastResult:
        """Fit ln(y) = a*t + b, i.e. y = e^b * e^(a*t)."""
        if not self._ok:
            return _INSUFFICIENT

        # Guard against zero/negative sizes before log
        safe = np.where(self._sizes > 0.001, self._sizes, 0.001)
        log_sizes = np.log(safe)

        coeffs = np.polyfit(self._days, log_sizes, 1)
        a = float(coeffs[0])  # growth exponent per day

        predicted_log = np.polyval(coeffs, self._days)
        r2 = self._r_squared(log_sizes, predicted_log)

        # Daily rate at the current point: dS/dt = a * S
        daily_rate = self._current_mb * (float(np.exp(a)) - 1.0)

        # Days to reach target: t = ln(target / current) / a
        def _days_to_exp(target_mb: float) -> int:
            if a <= 0 or self._current_mb <= 0:
                return -1
            try:
                return max(0, int(np.log(target_mb / self._current_mb) / a))
            except (ValueError, ZeroDivisionError):
                return -1

        return ForecastResult(
            model="exponential",
            daily_rate_mb=round(daily_rate, 3),
            days_to_1gb=_days_to_exp(1_024.0),
            days_to_10gb=_days_to_exp(10_240.0),
            r_squared=round(r2, 3),
        )

    def best(self) -> ForecastResult:
        """Return whichever model has the higher R²."""
        if not self._ok:
            return _INSUFFICIENT
        lin = self.linear()
        exp = self.exponential()
        return lin if lin.r_squared >= exp.r_squared else exp

    # ------------------------------------------------------------------
    # Helper to load history from logs.db
    # ------------------------------------------------------------------

    @staticmethod
    async def load_history(
        logs_db_path: Optional[Path] = None,
        days_back: int = 30,
    ) -> List[Tuple[int, float]]:
        """
        Load (ts, total_size_mb) rows from db_snapshots in logs.db.
        Returns list sorted ascending by ts.
        Falls back to empty list if table doesn't exist yet.
        """
        import aiosqlite

        if logs_db_path is None:
            logs_db_path = Path.home() / ".mnemostroma" / "logs.db"

        if not logs_db_path.exists():
            return []

        cutoff = int(time.time()) - days_back * 86_400
        try:
            async with aiosqlite.connect(str(logs_db_path)) as db:
                async with db.execute(
                    """
                    SELECT ts, (db_size_mb + logs_size_mb) AS total_mb
                    FROM   db_snapshots
                    WHERE  ts >= ?
                    ORDER  BY ts ASC
                    """,
                    (cutoff,),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [(int(r[0]), float(r[1])) for r in rows]
        except Exception:
            # Table may not exist on first run — that's fine
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _r_squared(actual: np.ndarray, predicted: np.ndarray) -> float:
        ss_res = float(np.sum((actual - predicted) ** 2))
        ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
        if ss_tot == 0:
            return 1.0  # flat line — perfect fit by definition
        return max(0.0, 1.0 - ss_res / ss_tot)

    def _days_to(self, target_mb: float, rate_mb_per_day: float) -> int:
        """Linear days-to-target helper."""
        if rate_mb_per_day <= 0:
            return -1
        return max(0, int((target_mb - self._current_mb) / rate_mb_per_day))
