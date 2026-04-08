"""Inject / undo Mnemostroma memory protocol block in agent config files."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from mnemostroma.setup.protocol import PROTOCOL_MARKER, get_block


@dataclass
class InjectResult:
    status: str          # "ok" | "already_injected" | "created"
    path: Path
    backup: Path | None = None

    def __str__(self) -> str:
        icons = {"ok": "✓", "already_injected": "~", "created": "+"}
        icon = icons.get(self.status, "?")
        msg = {
            "ok": f"Injected → {self.path}  (backup: {self.backup})",
            "already_injected": f"Already present — {self.path}",
            "created": f"Created → {self.path}  (backup: {self.backup})",
        }.get(self.status, self.status)
        return f"  {icon} {msg}"


@dataclass
class UndoResult:
    status: str          # "ok" | "no_block"
    path: Path

    def __str__(self) -> str:
        if self.status == "ok":
            return f"  ✓ Removed from {self.path}"
        return f"  ~ No protocol block found in {self.path}"


def inject(path: Path) -> InjectResult:
    """Inject memory protocol block into file at path.

    Idempotent: if block already present, returns already_injected.
    Creates file if it does not exist.
    Always backs up original before modifying.
    """
    path = path.expanduser().resolve()

    if path.exists():
        content = path.read_text(encoding="utf-8")
        if PROTOCOL_MARKER in content:
            return InjectResult(status="already_injected", path=path)

        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        new_content = content.rstrip("\n") + "\n\n" + get_block()
        path.write_text(new_content, encoding="utf-8")
        return InjectResult(status="ok", path=path, backup=backup)

    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        path.write_text(get_block(), encoding="utf-8")
        return InjectResult(status="created", path=path, backup=backup)


def undo(path: Path) -> UndoResult:
    """Remove memory protocol block from file.

    Removes everything between PROTOCOL_MARKER lines (inclusive).
    No-op if block not found.
    """
    path = path.expanduser().resolve()

    if not path.exists():
        return UndoResult(status="no_block", path=path)

    content = path.read_text(encoding="utf-8")
    if PROTOCOL_MARKER not in content:
        return UndoResult(status="no_block", path=path)

    marker_end = PROTOCOL_MARKER + "-end"
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    inside = False

    for line in lines:
        if line.strip() == PROTOCOL_MARKER:
            inside = True
            continue
        if line.strip() == marker_end:
            inside = False
            continue
        if not inside:
            result.append(line)

    path.write_text("".join(result).rstrip("\n") + "\n", encoding="utf-8")
    return UndoResult(status="ok", path=path)


def status(path: Path) -> bool:
    """Return True if file contains the protocol block."""
    path = path.expanduser().resolve()
    if not path.exists():
        return False
    return PROTOCOL_MARKER in path.read_text(encoding="utf-8")
