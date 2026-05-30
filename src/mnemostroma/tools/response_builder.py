# SPDX-License-Identifier: FSL-1.1-MIT
"""Response builder for tiered temporal search results.

Provides build_search_response to select response mode based on result count:
- Full (≤30): all fields, no warning
- Full + warning (31–50): all fields, add warning
- Compact (>50): only id/brief/created_at/exact_time_str, warning + hint
"""


SOFT_LIMIT = 30
HARD_LIMIT = 50


def build_search_response(results: list[dict], total_matched: int) -> dict:
    """Build tiered response based on result count.

    Selects response mode to protect context window:
    - ≤30 results: return all fields, no warning
    - 31–50 results: return all fields + warning
    - >50 results: compact mode (only key fields) + warning + hint

    Args:
        results: List of result dicts (full SessionObject records)
        total_matched: Total count of matches (may exceed len(results) if limited)

    Returns:
        Dict with fields:
            results: list[dict] — full or compact SessionObjects
            total_matched: int — total match count
            compact_mode: bool — True if compact format applied
            warning: str | None — user-facing warning message
            hint: str | None — advice for compact mode

    Examples:
        >>> resp = build_search_response([{...}, {...}], 15)
        >>> resp["compact_mode"]
        False
        >>> resp["warning"] is None
        True

        >>> resp = build_search_response([{...}] * 60, 87)
        >>> resp["compact_mode"]
        True
        >>> resp["warning"]
        "⚠️ LARGE RESPONSE: ..."
    """
    if total_matched <= SOFT_LIMIT:
        return {
            "results": results,
            "total_matched": total_matched,
            "compact_mode": False,
            "warning": None,
            "hint": None,
        }

    if total_matched <= HARD_LIMIT:
        return {
            "results": results,
            "total_matched": total_matched,
            "compact_mode": False,
            "warning": (
                f"⚠️ Large result set ({total_matched} sessions). "
                "Consider narrowing with a more precise mask or adding tags."
            ),
            "hint": None,
        }

    compact_results = [
        {
            "session_id": r.get("session_id"),
            "brief": r.get("brief"),
            "created_at": r.get("created_at"),
            "exact_time_str": r.get("exact_time_str", ""),
        }
        for r in results
    ]

    return {
        "results": compact_results,
        "total_matched": total_matched,
        "compact_mode": True,
        "warning": (
            f"⚠️ LARGE RESPONSE: {total_matched} sessions matched. "
            "Returning compact format to protect context window."
        ),
        "hint": "Use ctx_full(session_id) to load full details for specific sessions.",
    }
