"""检查 pgvector 扩展是否安装在 PostgreSQL 中"""
import asyncio
import asyncpg
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

async def check():
    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        database=os.environ.get("POSTGRES_DATABASE", "ai_kb_vector"),
    )
    row = await conn.fetchrow(
        "SELECT * FROM pg_extension WHERE extname = 'vector'"
    )
    if row:
        print(f"pgvector 扩展已安装，版本: {row['extversion']}")
    else:
        print("pgvector 扩展未安装，尝试创建...")
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("pgvector 扩展已创建成功")
        except Exception as e:
            print(f"创建 pgvector 扩展失败: {e}")
            print("请确保 PostgreSQL 已安装 pgvector: https://github.com/pgvector/pgvector")
    await conn.close()

asyncio.run(check())
