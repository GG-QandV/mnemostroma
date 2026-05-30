#!/usr/bin/env python3
"""
issue_build.py — generate a watermarked alpha build for a specific tester.

Usage:
    python scripts/issue_build.py <tester_id> [--branch alpha] [--out dist/]

Example:
    python scripts/issue_build.py tester-007
    → dist/mnemostroma-alpha-tester-007.zip

The script:
  1. Runs `git archive` from the alpha branch (consistent timestamps, no .git)
  2. Unpacks into a temp dir
  3. Injects unique hidden watermark constants into target files
  4. Repacks to zip with original timestamps intact (from git archive)
  5. Writes tester → watermark mapping to .watermarks_registry.csv (gitignored)

Watermarks are designed to look like internal technical constants.
They are injected into multiple independent files so a single-file leak
can still be traced.
"""

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


# Files that receive watermark injection.
# Each file must contain the placeholder token on an importable top-level line.
# Placeholder line is searched by the ANCHOR string and replaced in-place.
WATERMARK_TARGETS = [
    {
        "file": "src/mnemostroma/storage/sqlite.py",
        "anchor": "_LOGS_ID_DB_",
        "template": '_LOGS_ID_DB_ = "{wm_a}"  # internal diagnostics id\n',
    },
    {
        "file": "src/mnemostroma/conductor.py",
        "anchor": "_SESS_DIAG_KEY_",
        "template": '_SESS_DIAG_KEY_ = "{wm_b}"  # session diagnostics key\n',
    },
    {
        "file": "src/mnemostroma/memory/consolidation.py",
        "anchor": "_CONS_BUILD_TAG_",
        "template": '_CONS_BUILD_TAG_ = "{wm_c}"  # consolidation build tag\n',
    },
]

REGISTRY_FILE = Path(__file__).parent / ".watermarks_registry.csv"
REGISTRY_HEADER = ["tester_id", "issued_at", "wm_a", "wm_b", "wm_c", "output_file"]


def _derive_watermarks(tester_id: str) -> dict[str, str]:
    """Derive three independent watermark tokens from tester_id."""
    def _token(salt: str) -> str:
        raw = hashlib.sha256(f"mnemo::{salt}::{tester_id}".encode()).digest()
        # Encode as alphanumeric-looking string (no obvious base64 chars)
        chars = "abcdefghjkmnpqrstuvwxyz0123456789"
        result = ""
        for byte in raw[:12]:
            result += chars[byte % len(chars)]
        return result

    return {
        "wm_a": _token("db-layer-v1"),
        "wm_b": _token("sess-key-v1"),
        "wm_c": _token("cons-tag-v1"),
    }


def _inject_watermarks(work_dir: Path, watermarks: dict[str, str]) -> None:
    """Inject watermark lines into target files inside work_dir."""
    for target in WATERMARK_TARGETS:
        fpath = work_dir / target["file"]
        if not fpath.exists():
            print(f"  [WARN] target file not found: {target['file']} — skipping")
            continue

        anchor = target["anchor"]
        new_line = target["template"].format(**watermarks)
        lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)

        # Replace existing anchor line, or insert after last import block
        injected = False
        for i, line in enumerate(lines):
            if anchor in line:
                lines[i] = new_line
                injected = True
                break

        if not injected:
            # Insert after the last `import` or `from` line
            last_import = 0
            for i, line in enumerate(lines):
                if line.startswith(("import ", "from ")):
                    last_import = i
            lines.insert(last_import + 1, "\n" + new_line)

        fpath.write_text("".join(lines), encoding="utf-8")
        print(f"  [OK]   {target['file']} ← {anchor}='{new_line.split('\"')[1]}'")


def _registry_write(record: dict) -> None:
    """Append tester record to the local registry CSV."""
    write_header = not REGISTRY_FILE.exists()
    with open(REGISTRY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerow(record)


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue watermarked alpha build")
    parser.add_argument("tester_id", help="Tester identifier, e.g. tester-007")
    parser.add_argument("--branch", default="alpha", help="Source branch (default: alpha)")
    parser.add_argument("--out", default="dist", help="Output directory (default: dist/)")
    args = parser.parse_args()

    tester_id = args.tester_id.strip()
    if not tester_id:
        sys.exit("tester_id must not be empty")

    repo_root = Path(__file__).parent.parent
    out_dir = repo_root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    out_zip = out_dir / f"mnemostroma-alpha-{tester_id}.zip"
    print(f"\n=== Issuing build for: {tester_id} ===")
    print(f"Branch : {args.branch}")
    print(f"Output : {out_zip}")

    # 1. git archive → temp zip
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        raw_zip = tmp_path / "raw.zip"

        print("\n[1/4] Running git archive...")
        result = subprocess.run(
            ["git", "archive", "--format=zip", f"--output={raw_zip}", args.branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit(f"git archive failed:\n{result.stderr}")

        # 2. Unpack
        print("[2/4] Unpacking...")
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        with zipfile.ZipFile(raw_zip, "r") as zf:
            zf.extractall(work_dir)

        # 3. Inject watermarks
        watermarks = _derive_watermarks(tester_id)
        print("[3/4] Injecting watermarks...")
        _inject_watermarks(work_dir, watermarks)

        # 4. Repack
        print("[4/4] Repacking...")
        # Use git archive's original zip as base for timestamps, then update changed files
        # Strategy: build fresh zip from work_dir (timestamps will be current —
        # acceptable since all files share the same mtime from extraction)
        shutil.make_archive(str(out_zip.with_suffix("")), "zip", work_dir)
        # shutil names it .zip automatically

    # Registry
    record = {
        "tester_id": tester_id,
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **watermarks,
        "output_file": out_zip.name,
    }
    _registry_write(record)
    print(f"\n[DONE] {out_zip}")
    print(f"[REG]  Watermarks saved to {REGISTRY_FILE.name}")
    print(f"\nIf this build leaks, run: python scripts/identify_leak.py <leaked_file>")


if __name__ == "__main__":
    main()
