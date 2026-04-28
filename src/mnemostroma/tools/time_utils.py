# SPDX-License-Identifier: FSL-1.1-MIT
"""Time utilities for exact_time feature in Mnemostroma.

Provides:
- unix_to_str: Format Unix timestamp to readable string (UTC or LOCAL)
- enrich_with_time: Add exact_time_str and exact_time_unix fields to objects
- parse_exact_time_with_mask: Parse time string with X-mask to (lo_ts, hi_ts)
"""

import re
import time
from typing import Optional


def unix_to_str(unix_ts: int | float | None, utc: bool = True) -> str:
    """Format Unix timestamp to readable string.

    Args:
        unix_ts: Unix timestamp (seconds since epoch), or None/≤0
        utc: If True, format as UTC; otherwise use local time

    Returns:
        String like "2026-04-27 21:18:55 UTC" or "2026-04-27 21:18:55 LOCAL"
        Empty string "" if unix_ts is None or ≤ 0

    Examples:
        >>> unix_to_str(1777260157, utc=True)
        "2026-04-27 21:35:57 UTC"

        >>> unix_to_str(1777260157, utc=False)
        "2026-04-27 23:35:57 LOCAL"

        >>> unix_to_str(None)
        ""

        >>> unix_to_str(0)
        ""
    """
    if unix_ts is None or unix_ts <= 0:
        return ""

    if utc:
        tm = time.gmtime(unix_ts)
        suffix = "UTC"
    else:
        tm = time.localtime(unix_ts)
        suffix = "LOCAL"

    return time.strftime(f"%Y-%m-%d %H:%M:%S {suffix}", tm)


def enrich_with_time(obj: dict, ts_field: str = "created_at") -> dict:
    """Add exact_time_str and exact_time_unix fields to a dict.

    Modifies the dict in-place.

    Args:
        obj: Dictionary to enrich (typically a SessionBrief serialized to dict)
        ts_field: Name of the timestamp field (default: "created_at")

    Returns:
        The same dict object (modified in-place)

    Behavior:
        - If ts_field exists and ts > 0:
          - Add "exact_time_str" = formatted UTC string
          - Add "exact_time_unix" = int(ts)
        - Otherwise, skip (no keys added)

    Examples:
        >>> d = {"session_id": "abc", "created_at": 1777260157}
        >>> enrich_with_time(d)
        >>> d["exact_time_str"]
        "2026-04-27 21:35:57 UTC"

        >>> d2 = {"session_id": "xyz", "created_at": None}
        >>> enrich_with_time(d2)
        >>> "exact_time_str" in d2
        False
    """
    ts = obj.get(ts_field)

    if ts is not None and ts > 0:
        obj["exact_time_str"] = unix_to_str(ts, utc=True)
        obj["exact_time_unix"] = int(ts)

    return obj


# --- Plan B: Mask-based temporal search ---

# 2-digit year bounds for DD/MM/YY format
_YEAR_MIN: int = 2020
_YEAR_MAX: int = 2035

# Ordered parse format candidates.
# All non-Unix formats are tried with a fully-resolved datetime string (XX→00, date-only→midnight).
_PARSE_FORMATS: list[str] = [
    "%Y-%m-%dT%H:%M:%S",  # ISO 8601 with T
    "%Y-%m-%d %H:%M:%S",  # ISO 8601 with space
    "%d/%m/%y %H:%M:%S",  # DD/MM/YY — 2-digit year (checked against _YEAR_MIN/_YEAR_MAX)
    "%d/%m/%Y %H:%M:%S",  # DD/MM/YYYY — 4-digit year
]


def parse_exact_time_with_mask(
    s: str,
) -> tuple[int, int] | tuple[None, str]:
    """Parse a time string with optional X-mask to a half-open [lo, hi) Unix interval.

    Why LOCAL time: agent strings originate from OS logs which use the host timezone.
    Using time.mktime() ensures parity with `cat /var/log/syslog` timestamps.
    For timezone-independent search pass a Unix timestamp string instead.

    Args:
        s: Time string in one of the supported formats:
           - Unix timestamp string: "1714210000"
           - ISO 8601 T-separated: "2026-04-14T21:18:XX"
           - ISO 8601 space-separated: "2026-04-14 21:18:XX"
           - DD/MM/YY: "14/04/26 21:18:XX"
           - DD/MM/YYYY: "14/04/2026 21:18:XX"
           Mask XX replaces the seconds component (minute precision)
           or the minutes component (hour precision).

    Returns:
        (lo_ts, hi_ts): half-open interval [lo, hi) on success.
        (None, error_message): on any parse failure.

    Precision levels:
        No X, full datetime  → second precision: hi = lo + 1
        HH:MM:XX             → minute precision: hi = lo + 60
        HH:XX                → hour precision:   hi = lo + 3600
        date only            → day precision:    hi = lo + 86400
    """
    s = s.strip()

    # --- Format 1: Unix timestamp (pure digit string) ---
    if re.match(r"^\d+$", s):
        ts = int(s)
        return ts, ts + 1

    # --- Detect mask and determine precision step ---
    # Order matters: check HH:MM:XX (minute precision) before HH:XX (hour precision).
    normalized = s
    step: int

    if re.search(r"\d{2}:\d{2}:XX", normalized, re.IGNORECASE):
        # Seconds masked → minute-level window
        step = 60
        normalized = re.sub(r":XX", ":00", normalized, count=1, flags=re.IGNORECASE)

    elif re.search(r"\d{2}:XX", normalized, re.IGNORECASE):
        # Minutes masked → hour-level window; inject ":00" so strptime gets HH:MM:SS
        step = 3600
        normalized = re.sub(r":XX", ":00:00", normalized, count=1, flags=re.IGNORECASE)

    else:
        # No mask: check whether a time component is present
        if re.search(r"[\sT]\d{1,2}:\d{2}", normalized):
            step = 1        # full datetime → second precision
        else:
            step = 86400    # date only → day precision

    # For date-only inputs append midnight so all formats expect HH:MM:SS
    parse_str = normalized if step != 86400 else normalized + " 00:00:00"

    # --- Try each candidate format ---
    for fmt in _PARSE_FORMATS:
        try:
            tm = time.strptime(parse_str, fmt)
        except ValueError:
            continue

        # Bounds check for ambiguous 2-digit year
        if "%y" in fmt and not (_YEAR_MIN <= tm.tm_year <= _YEAR_MAX):
            return None, (
                f"Year {tm.tm_year} is outside the supported 2-digit-year range "
                f"[{_YEAR_MIN}, {_YEAR_MAX}]. Use a 4-digit year or a Unix timestamp."
            )

        lo_ts = int(time.mktime(tm))  # LOCAL time — matches OS log timestamps
        return lo_ts, lo_ts + step

    return None, (
        f"Cannot parse time string: {s!r}. "
        "Supported formats: Unix timestamp, ISO 8601 (YYYY-MM-DD HH:MM:SS), "
        "DD/MM/YY HH:MM:SS. Masks: XX for minute precision (:MM:XX) or hour precision (:XX)."
    )
