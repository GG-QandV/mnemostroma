#!/usr/bin/env python3
"""
Single source of truth for version.
Reads version from pyproject.toml, updates all docs automatically.
Rotates previous_version in [tool.mnemostroma] after update.

Usage: python scripts/update_version.py
Exit 0 = success. Exit 1 = error, do not commit.

STRIP-SAFE: no log_event, no LOGSIDDB, no SESSDIAGKEY, no CONSBUILDTAG.
"""
import re
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent

# --- Read version from pyproject.toml ---
pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

m = re.search(r'(?m)^version = "(.+)"', pyproject_text)
if not m:
    print("ERROR: version not found in pyproject.toml", file=sys.stderr)
    sys.exit(1)
VERSION = m.group(1)

m2 = re.search(r'previous_version = "(.+)"', pyproject_text)
PREV_VERSION = m2.group(1) if m2 else None

DATE = date.today().isoformat()
print(f"Version : {VERSION}")
print(f"Previous: {PREV_VERSION or '(none)'}")
print(f"Date    : {DATE}\n")

# REPLACEMENTS: только файлы с "current version" маркерами — см. VERSION_FILES_AUDIT.md
REPLACEMENTS = [
    (
        "README.md",
        r'!\[Version\]\(https://img\.shields\.io/badge/version-v[\d\.]+(?:--beta)?-orange\)',
        f'![Version](https://img.shields.io/badge/version-v{VERSION}--beta-orange)',
        1,
    ),
    (
        "README.md",
        r'\*\*Current:\*\* v[\d\.]+(?:\s+Beta\s+\(Active\s+Development\))? \| \d{4}-\d{2}-\d{2}',
        f'**Current:** v{VERSION} Beta (Active Development) | {DATE}',
        1,
    ),
    (
        "README.md",
        r'v[\d\.]+(?:\s+Beta\s+\(Active\s+Development\))?\s+(?:is stable|Beta\s+\(Active\s+Development\))\.',
        f'v{VERSION} Beta (Active Development).',
        2,
    ),
    (
        "README.md",
        r'\*offline · ~650MB RAM \(baseline\) · ~20ms · 531 tests · v[\d\.]+(?:\s+Beta)?\*',
        f'*offline · ~650MB RAM (baseline) · ~20ms · 531 tests · v{VERSION} Beta*',
        1,
    ),
    (
        "UPGRADE.md",
        r'## Upgrading to v[\d\.]+(?:\s+Beta)? \(Current\)',
        f'## Upgrading to v{VERSION} Beta (Current)',
        1,
    ),
]

# PY_REPLACEMENTS: __version__ source file
PY_REPLACEMENTS = [
    (
        "src/mnemostroma/version.py",
        r'__version__ = "[0-9.]+"',
        f'__version__ = "{VERSION}"',
    ),
]

# SCAN_EXCLUDE: архивные версии в excluded файлах — корректны, не stale
SCAN_EXCLUDE = {
    "CHANGELOG.md",
    "GIT_RULES_v4.1.md",
    "architecture_overview.md",
    "deployment_guide.md",
    "mnemostroma_description_technical.md",
    "security_specification.md",
    "update_version.py",
}

SCAN_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "archive of documents",
    "release",
    "instructions",
}

errors = []
warnings = []

for filename, pattern, replacement, expected in REPLACEMENTS:
    filepath = ROOT / filename
    if not filepath.exists():
        errors.append(f"ERROR: {filename} not found"); continue
    original = filepath.read_text(encoding="utf-8")
    count = len(re.findall(pattern, original))
    updated = re.sub(pattern, replacement, original)
    if count == 0:
        errors.append(f"ERROR: no match in {filename} — {pattern[:60]}")
    elif count != expected:
        warnings.append(f"WARNING: {filename} — expected {expected}, got {count}")
        filepath.write_text(updated, encoding="utf-8")
        print(f"  ~ {filename}: {count} replacement(s) (expected {expected})")
    else:
        filepath.write_text(updated, encoding="utf-8")
        print(f"  ✓ {filename}: {count} replacement(s)")

for rel_path, pattern, replacement in PY_REPLACEMENTS:
    filepath = ROOT / rel_path
    if not filepath.exists():
        errors.append(f"ERROR: {rel_path} not found — check path from Step 3"); continue
    original = filepath.read_text(encoding="utf-8")
    count = len(re.findall(pattern, original))
    if count == 0:
        errors.append(f"ERROR: __version__ pattern not found in {rel_path}")
    else:
        filepath.write_text(re.sub(pattern, replacement, original), encoding="utf-8")
        print(f"  ✓ {rel_path}: {count} version replacement(s)")

# Stale scan: только previous_version. Старые v1.8.x / v1.9.x — вне scope.
if PREV_VERSION:
    print(f"\nScanning for forgotten references to v{PREV_VERSION}...")
    found_stale = []
    for md_file in ROOT.rglob("*.md"):
        if md_file.name in SCAN_EXCLUDE: continue
        if any(p in md_file.parts for p in SCAN_EXCLUDE_DIRS): continue
        try: content = md_file.read_text(encoding="utf-8", errors="ignore")
        except: continue
        if re.search(rf"\bv?{re.escape(PREV_VERSION)}\b", content):
            found_stale.append(str(md_file.relative_to(ROOT)))
    if found_stale:
        for f in found_stale:
            warnings.append(f"WARNING: {f} — still mentions v{PREV_VERSION}")
    else:
        print("  ✓ No stale version references found")
else:
    warnings.append("WARNING: previous_version not set — stale scan skipped")

# NEW .md files check
known_md = {
    "README.md", "UPGRADE.md", "CHANGELOG.md",
    "architecture_overview.md", "deployment_guide.md",
    "mnemostroma_description_technical.md", "security_specification.md",
}
new_md = [f.name for f in ROOT.glob("*.md") if f.name not in known_md and f.name not in SCAN_EXCLUDE]
if new_md:
    warnings.append(f"NOTICE: new root .md files — verify if version update needed: {new_md}")

# Rotate previous_version
new_pyproject = re.sub(
    r'previous_version = "[^"]+"',
    f'previous_version = "{VERSION}"',
    pyproject_text,
)
if new_pyproject == pyproject_text and PREV_VERSION != VERSION:
    warnings.append("WARNING: could not rotate previous_version")
else:
    (ROOT / "pyproject.toml").write_text(new_pyproject, encoding="utf-8")
    print(f"  ✓ pyproject.toml: previous_version rotated to {VERSION}")

print()
for w in warnings: print(w)
if errors:
    for e in errors: print(e, file=sys.stderr)
    print("\nABORTED: fix errors above before committing.", file=sys.stderr)
    sys.exit(1)
print("\nDone. Review: git diff README.md UPGRADE.md pyproject.toml")