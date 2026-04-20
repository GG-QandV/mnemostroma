"""Test Python 3.13+ compatibility — no empty blocks."""
import sys
import subprocess
from pathlib import Path


def test_no_empty_blocks():
    """Ensure all .py files compile without IndentError on Python 3.13+."""
    src_dir = Path(__file__).parent.parent / "src" / "mnemostroma"
    errors = []

    for py_file in src_dir.rglob("*.py"):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(py_file)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            errors.append(f"{py_file}: {result.stderr}")

    if errors:
        raise SyntaxError(f"IndentError/SyntaxError found:\n" + "\n".join(errors))


if __name__ == "__main__":
    test_no_empty_blocks()
