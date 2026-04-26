#!/usr/bin/env python3
"""Check that version in pyproject.toml matches README.md."""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]

# pyproject.toml
toml = (root / "pyproject.toml").read_text()
m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', toml, re.M)
toml_ver = m.group(1) if m else None

# README.md
readme = (root / "README.md").read_text()
m = re.search(r'v(\d+\.\d+\.\d+)', readme)
readme_ver = m.group(1) if m else None

if not toml_ver:
    print("FAIL version_check: version not found in pyproject.toml")
    sys.exit(1)
if not readme_ver:
    print("FAIL version_check: version not found in README.md")
    sys.exit(1)
if toml_ver != readme_ver:
    print(f"FAIL version_check: pyproject={toml_ver} README={readme_ver}")
    sys.exit(1)

print(f"PASS version_check: {toml_ver}")
sys.exit(0)
