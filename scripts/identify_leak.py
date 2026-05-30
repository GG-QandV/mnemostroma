#!/usr/bin/env python3
"""
identify_leak.py — identify which tester a leaked file came from.

Usage:
    python scripts/identify_leak.py <leaked_file_or_dir>

Example:
    python scripts/identify_leak.py ~/Downloads/leaked_sqlite.py
    python scripts/identify_leak.py ~/Downloads/leaked_mnemostroma/

Scans the file(s) for known watermark tokens and matches against registry.
"""

import csv
import re
import sys
from pathlib import Path

REGISTRY_FILE = Path(__file__).parent / ".watermarks_registry.csv"
WATERMARK_FIELDS = ["wm_a", "wm_b", "wm_c"]


def _extract_tokens(text: str) -> set[str]:
    """Extract candidate watermark tokens (alphanumeric, 12 chars)."""
    return set(re.findall(r'["\']([a-z0-9]{12})["\']', text))


def _load_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        sys.exit(f"Registry not found: {REGISTRY_FILE}")
    with open(REGISTRY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: identify_leak.py <file_or_dir>")

    target = Path(sys.argv[1])
    if not target.exists():
        sys.exit(f"Not found: {target}")

    # Collect all text from target
    all_text = ""
    file_count = 0
    if target.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(target, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".py"):
                    try:
                        all_text += zf.read(name).decode("utf-8", errors="ignore")
                        file_count += 1
                    except Exception:
                        pass
    else:
        files = [target] if target.is_file() else list(target.rglob("*.py"))
        file_count = len(files)
        for f in files:
            try:
                all_text += f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

    found_tokens = _extract_tokens(all_text)
    registry = _load_registry()

    print(f"\nScanned {file_count} file(s), found {len(found_tokens)} candidate token(s).")

    matches: list[tuple[int, dict]] = []
    for row in registry:
        row_tokens = {row[f] for f in WATERMARK_FIELDS if row.get(f)}
        hits = found_tokens & row_tokens
        if hits:
            matches.append((len(hits), row, hits))

    if not matches:
        print("\n[RESULT] No match found in registry.")
        return

    matches.sort(key=lambda x: -x[0])
    print("\n[RESULT] Matches (sorted by confidence):")
    for score, row, hits in matches:
        print(f"  tester_id : {row['tester_id']}")
        print(f"  issued_at : {row['issued_at']}")
        print(f"  confidence: {score}/{len(WATERMARK_FIELDS)} watermarks matched")
        print(f"  tokens    : {', '.join(hits)}")
        print()


if __name__ == "__main__":
    main()
