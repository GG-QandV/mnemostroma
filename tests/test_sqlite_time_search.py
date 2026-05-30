import pytest
import aiosqlite
from mnemostroma.storage.sqlite import SQLiteStorage, init_db
from unittest.mock import MagicMock
import json

@pytest.mark.asyncio
async def test_search_sessions_by_time():
    db = await init_db(":memory:")
    mock_config = MagicMock()
    storage = SQLiteStorage(db, mock_config)
    
    # Вставляем тестовые данные
    await db.execute(
        "INSERT INTO sessions (session_id, brief, created_at, tags, importance) VALUES "
        "('s1', 'b1', 100, '[]', 'background'),"
        "('s2', 'b2', 200, '[]', 'important'),"
        "('s3', 'b3', 300, '[]', 'critical')"
    )
    await db.commit()
    
    # Ищем в окне [150, 250)
    res = await storage.search_sessions_by_time(150, 250, limit=10)
    assert len(res) == 1
    assert res[0]["session_id"] == "s2"
    
    await db.close()
