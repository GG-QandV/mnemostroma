# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from mnemostroma.config import Config
from mnemostroma.storage.sqlite import init_db
from mnemostroma.memory.session_index import SessionBrief

async def main():
    print("--- Phase 0 Verification ---")
    
    # 1. Config Loading
    # config.json should be in the parent of tests/
    config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        print(f"Error: {config_path} not found")
        # Fallback to current dir
        config_path = Path.cwd() / "config.json"
        if not config_path.exists():
            print(f"Error: {config_path} not found")
            return
    
    print(f"Loading config from: {config_path}")
    config = Config.load(config_path)
    print(f"Config loaded: resources.ram_soft_limit_mb = {config.resources.ram_soft_limit_mb}")
    assert config.resources.ram_soft_limit_mb == 380
    print("✅ Config verification passed")

    # 2. Database Initialization
    test_db = Path(__file__).parent / "test_mnemostroma.db"
    if test_db.exists():
        os.remove(test_db)
    
    print(f"Initializing test database at: {test_db}")
    db = await init_db(test_db)
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
        tables = [row[0] for row in await cursor.fetchall()]
    
    expected_tables = ["sessions", "anchors", "precision_log", "content_blocks", "content_versions"]
    for table in expected_tables:
        assert table in tables
        print(f"Table '{table}' exists")
    
    await db.close()
    if test_db.exists():
        os.remove(test_db)
    print("✅ Database verification passed")

    # 3. Dataclass check
    sb = SessionBrief(
        session_id="s_001",
        brief="Test session",
        tags=["#test"],
        importance="important",
        score=0.8,
        resolution=1.0,
        created_at=123456789
    )
    print(f"SessionBrief created: {sb.session_id}, layer={sb.layer}")
    assert sb.layer == "RAM_HOT"
    print("✅ SessionBrief verification passed")
    
    print("\n--- All Phase 0 Verifications Passed! ---")

if __name__ == "__main__":
    asyncio.run(main())
