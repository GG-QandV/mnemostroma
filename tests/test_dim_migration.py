# SPDX-License-Identifier: FSL-1.1-MIT
import unittest
import asyncio
import numpy as np
import aiosqlite
from pathlib import Path
from mnemostroma.storage.sqlite import DatabaseManager, init_db
from mnemostroma.config import Config

class TestDimMigration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Use in-memory DB for tests
        self.db = await init_db(":memory:")
        self.config = Config.load(Path(__file__).parent.parent / "config.json")
        self.db_manager = DatabaseManager(self.db, self.config)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_dim_migration_wipes_on_mismatch(self):
        """Wipes sessions if stored dimension (768) != expected (384)."""
        # 1. Insert 768-dim embedding (old model)
        vec_768 = np.random.rand(768).astype(np.float16)
        await self.db.execute(
            "INSERT INTO sessions (session_id, embedding, brief) VALUES (?, ?, ?)",
            ("old_session", vec_768.tobytes(), "Old Brief")
        )
        await self.db.execute(
            "INSERT INTO content_blocks (content_id, session_id) VALUES (?, ?)",
            ("old_content", "old_session")
        )
        await self.db.commit()

        # Verify data exists
        row = await self.db.execute_fetchall("SELECT COUNT(*) FROM sessions")
        self.assertEqual(row[0][0], 1)

        # 2. Run migration check with expected_dim=384
        await self.db_manager.check_embedding_dim(384)

        # 3. Assert tables are wiped
        row = await self.db.execute_fetchall("SELECT COUNT(*) FROM sessions")
        self.assertEqual(row[0][0], 0, "Sessions table should be wiped")
        
        row = await self.db.execute_fetchall("SELECT COUNT(*) FROM content_blocks")
        self.assertEqual(row[0][0], 0, "Content blocks should be wiped")

    async def test_dim_migration_preserves_on_match(self):
        """Does NOT wipe if dimensions match."""
        # 1. Insert 384-dim embedding
        vec_384 = np.random.rand(384).astype(np.float16)
        await self.db.execute(
            "INSERT INTO sessions (session_id, embedding, brief) VALUES (?, ?, ?)",
            ("new_session", vec_384.tobytes(), "New Brief")
        )
        await self.db.commit()

        # 2. Run migration check with expected_dim=384
        await self.db_manager.check_embedding_dim(384)

        # 3. Assert data is preserved
        row = await self.db.execute_fetchall("SELECT COUNT(*) FROM sessions")
        self.assertEqual(row[0][0], 1, "Data should be preserved when dimensions match")

if __name__ == "__main__":
    unittest.main()
