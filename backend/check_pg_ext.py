"""检查 pgvector 扩展"""
import asyncio
import asyncpg
import os

async def check():
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password=os.environ.get("POSTGRES_PASSWORD", "your_pg_password"),
        database="ai_kb_vector",
    )
    row = await conn.fetchrow(
        "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"
    )
    if row:
        print(f"pgvector 扩展已安装，版本: {row['extversion']}")
    else:
        print("pgvector 扩展未安装，尝试创建...")
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("pgvector 扩展已成功创建")
        except Exception as e:
            print(f"创建失败: {e}")
            print("提示: 需要在 PostgreSQL 服务器上安装 pgvector 扩展")
    await conn.close()

asyncio.run(check())
