import shutil
import pathlib
import os

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "mnemostroma" / "extension"
DST = pathlib.Path(os.path.expanduser("~/.mnemostroma/extension"))

shutil.rmtree(DST, ignore_errors=True)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("node_modules"))
print(f"Synced {SRC} → {DST}")
