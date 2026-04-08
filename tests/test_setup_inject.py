import pytest
from pathlib import Path
from mnemostroma.setup.inject import inject, undo, status
from mnemostroma.setup.protocol import PROTOCOL_MARKER, PROTOCOL_BLOCK

@pytest.mark.asyncio
async def test_inject_new_file(tmp_path: Path):
    target = tmp_path / "config.md"
    res = inject(target)
    
    assert res.status == "created"
    assert target.exists()
    assert PROTOCOL_MARKER in target.read_text()
    assert status(target) is True

@pytest.mark.asyncio
async def test_inject_existing_file(tmp_path: Path):
    target = tmp_path / "existing.md"
    original_content = "Existing content\n"
    target.write_text(original_content)
    
    res = inject(target)
    
    assert res.status == "ok"
    assert PROTOCOL_MARKER in target.read_text()
    assert original_content in target.read_text()
    assert status(target) is True

@pytest.mark.asyncio
async def test_inject_idempotent(tmp_path: Path):
    target = tmp_path / "idempotent.md"
    inject(target)
    content_after_first = target.read_text()
    
    res = inject(target)
    
    assert res.status == "already_injected"
    assert target.read_text() == content_after_first

@pytest.mark.asyncio
async def test_undo_removes_block(tmp_path: Path):
    target = tmp_path / "undo.md"
    original_prefix = "Start\n"
    original_suffix = "\nEnd"
    target.write_text(original_prefix + original_suffix)
    
    inject(target)
    assert status(target) is True
    
    res = undo(target)
    assert res.status == "ok"
    assert status(target) is False
    
    content = target.read_text()
    assert "Start" in content
    assert "End" in content
    assert PROTOCOL_MARKER not in content

@pytest.mark.asyncio
async def test_undo_no_block(tmp_path: Path):
    target = tmp_path / "no_block.md"
    content = "Just some text"
    target.write_text(content)
    
    res = undo(target)
    assert res.status == "no_block"
    # Content shouldn't change significantly (maybe rstrip/newline normalization)
    assert content.strip() in target.read_text().strip()

@pytest.mark.asyncio
async def test_backup_created(tmp_path: Path):
    target = tmp_path / "tobackedup.md"
    target.write_text("Old data")
    
    res = inject(target)
    assert res.status == "ok"
    assert res.backup is not None
    assert res.backup.exists()
    assert res.backup.read_text() == "Old data"
    assert res.backup.name == "tobackedup.md.bak"

@pytest.mark.asyncio
async def test_content_preserved(tmp_path: Path):
    target = tmp_path / "preserved.md"
    prefix = "BEGIN\n"
    suffix = "\nFINISH"
    target.write_text(prefix + suffix)
    
    inject(target)
    undo(target)
    
    final_content = target.read_text()
    assert "BEGIN" in final_content
    assert "FINISH" in final_content
    # Depending on implementation of undo, whitespaces might change slightly
    # inject.py: path.write_text("".join(result).rstrip("\n") + "\n", encoding="utf-8")
    assert final_content.strip() == (prefix + suffix).strip()

def test_print_protocol():
    # Regular synchronous test
    assert PROTOCOL_MARKER in PROTOCOL_BLOCK
    assert PROTOCOL_MARKER + "-end" in PROTOCOL_BLOCK
