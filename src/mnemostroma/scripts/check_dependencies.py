import os
import sys
import subprocess

def run_linter():
    print("Running import-linter for Architectural isolation...")
    # This assumes .importlinter is configured in pyproject.toml
    try:
        result = subprocess.run(["lint-imports"], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR: Architectural isolation violated!")
            print(result.stdout)
            print(result.stderr)
            sys.exit(1)
        print("OK: Dependency map reflects architecture.")
    except FileNotFoundError:
        print("WARNING: lint-imports not found. Ensure import-linter is installed.")

if __name__ == "__main__":
    run_linter()
