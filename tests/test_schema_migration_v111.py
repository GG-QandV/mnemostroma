# SPDX-License-Identifier: FSL-1.1-MIT
import unittest
import asyncio
import aiosqlite
from pathlib import Path
from mnemostroma.storage.sqlite import check_session_schema

class TestSchemaMigrationV111(unittest.IsolatedAsyncioTestCase):
    async def test_session_type_migration(self):
        """Verifies that check_session_schema adds session_type column if missing."""
        # 1. Create a minimal legacy schema without session_type
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                brief TEXT
            )
            """)
            await db.commit()

            # Verify column is missing
            with self.assertRaises(aiosqlite.OperationalError):
                await db.execute("SELECT session_type FROM sessions")

            # 2. Run migration
            await check_session_schema(db)

            # 3. Verify column now exists
            cursor = await db.execute("SELECT session_type FROM sessions")
            self.assertIsNotNone(cursor)
            
            # Verify index exists
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_type'")
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "idx_sessions_type")

if __name__ == "__main__":
    unittest.main()
