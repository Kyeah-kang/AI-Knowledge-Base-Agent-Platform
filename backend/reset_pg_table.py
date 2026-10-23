"""Drop and recreate document_chunks table"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from app.database.base import PostgreSQLBase
from app.database.session import pg_engine

async def main():
    async with pg_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("DROP TABLE IF EXISTS document_chunks CASCADE"))
        await conn.run_sync(PostgreSQLBase.metadata.create_all)
        print("document_chunks 表已重建（带 pgvector Vector 类型）")

asyncio.run(main())
