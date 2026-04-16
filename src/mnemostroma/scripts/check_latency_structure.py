import ast
import sys
from pathlib import Path

BANNED_PATTERNS = [
    (r"await.*queue\.put\(", "BLOCKING: use put_nowait()"),
    (r"aiosqlite.*observer/steps/(?!persist)", "DIRECT IO in hot path"),
    (r"asyncio\.sleep.*pipeline", "SLEEP in critical path"),
    (r"TaskGroup.*TaskGroup", "NESTED TaskGroup: deadlock risk"),
]

def scan_file(path: Path):
    content = path.read_text()
    for pattern, msg in BANNED_PATTERNS:
        import re
        if re.search(pattern, content):
            print(f"ERROR: {path}: {msg}")
            return False
    return True

def main():
    print("Scanning for latency-deadly patterns...")
    has_errors = False
    src_dir = Path("src/mnemostroma")
    for py_file in src_dir.rglob("*.py"):
        if not scan_file(py_file):
            has_errors = True
    
    if has_errors:
        sys.exit(1)
    print("OK: Latency structures are compliant.")

if __name__ == "__main__":
    main()
