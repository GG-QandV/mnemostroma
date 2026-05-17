"""
check_windows_scripts.py -- Validate Windows installer scripts for PS 5.1 compatibility.

Checks for:
  - PowerShell 7+ only syntax (??, ?.)
  - Non-ASCII characters (em-dash, box-drawing, emoji, curly quotes)

Usage:
    python scripts/check_windows_scripts.py
"""

import re
import sys
from pathlib import Path

UNICODE_CHECKS = [
    ("PS7-only: ?? operator",   re.compile(r"\?\?")),
    ("PS7-only: ?. operator",   re.compile(r"\?\.")),
    ("Em-dash U+2014",          re.compile("[\u2014]")),
    ("En-dash U+2013",          re.compile("[\u2013]")),
    ("Box-drawing U+2500-257F", re.compile("[\u2500-\u257f]")),
    ("Emoji/symbol non-ASCII",  re.compile("[\u2600-\u27ff\U0001f000-\U0001ffff]")),
    ("Curly quotes",            re.compile("[\u201c\u201d\u2018\u2019]")),
]

FILES = [
    "scripts/install-windows.ps1",
    "scripts/uninstall-windows.ps1",
    "scripts/install-windows.bat",
    "scripts/uninstall-windows.bat",
]


def check_file(path: str) -> list[str]:
    """Return list of issue strings for the given file."""
    issues: list[str] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [f"{path}: CANNOT READ: {exc}"]

    for i, line in enumerate(lines, 1):
        for label, pattern in UNICODE_CHECKS:
            if pattern.search(line):
                issues.append(f"{path}:{i} [{label}]  {line.rstrip()[:70]}")
                break  # one report per line

    return issues


def main() -> int:
    all_issues: list[str] = []

    for f in FILES:
        print(f"\n{'='*55}")
        print(f"  {f}")
        print(f"{'='*55}")
        file_issues = check_file(f)
        if file_issues:
            for iss in file_issues:
                print(f"  {iss}")
            all_issues.extend(file_issues)
        else:
            print("  OK -- all ASCII clean, no PS7-only syntax")

    print()
    if all_issues:
        print(f"TOTAL ISSUES: {len(all_issues)}")
        for iss in all_issues:
            print(f"  {iss}")
        return 1
    else:
        print("ALL CLEAN -- ready for Windows PowerShell 5.1")
        return 0


if __name__ == "__main__":
    sys.exit(main())
