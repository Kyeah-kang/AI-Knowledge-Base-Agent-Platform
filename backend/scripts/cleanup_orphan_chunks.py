"""
孤儿切片清扫脚本 — 删除"文档已不存在"的向量切片。

为什么需要：
  MySQL 的 documents 在 MySQL，document_chunks 在 PostgreSQL，跨库没有外键。
  只要有一条删除路径漏了（历史版本删知识库就不清 PG），
  PG 里就会留下永远检索得到、却已经没人认领的切片 —— 既不安全也浪费存储。

用法（可重复执行，幂等）：
    cd backend
    ..\\.venv\\Scripts\\python.exe scripts\\cleanup_orphan_chunks.py           # 只看不删
    ..\\.venv\\Scripts\\python.exe scripts\\cleanup_orphan_chunks.py --apply   # 真删
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import (
    MySQLAsyncSessionLocal,
    PostgreSQLAsyncSessionLocal,
    mysql_engine,
    pg_engine,
)
from app.models.document import Document, DocumentChunk


async def main(apply: bool) -> None:
    async with MySQLAsyncSessionLocal() as mysql:
        result = await mysql.execute(select(Document.id))
        alive_ids = {row[0] for row in result.all()}

    async with PostgreSQLAsyncSessionLocal() as pg:
        result = await pg.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .group_by(DocumentChunk.document_id)
        )
        stats = result.all()

    orphans = [(doc_id, cnt) for doc_id, cnt in stats if doc_id not in alive_ids]
    total_chunks = sum(cnt for _, cnt in orphans)

    print(f"MySQL 中存活文档数：{len(alive_ids)}")
    print(f"PG 中涉及 {len(stats)} 个 document_id，其中孤儿 {len(orphans)} 个")
    if not orphans:
        print("没有孤儿切片，无需清理。")
        return

    for doc_id, cnt in orphans:
        print(f"  - document_id={doc_id}: {cnt} 条切片")

    if not apply:
        print(f"\n（演练模式）共 {total_chunks} 条孤儿切片待删除。加 --apply 才会真的删。")
        return

    async with PostgreSQLAsyncSessionLocal() as pg:
        deleted = await pg.execute(
            DocumentChunk.__table__.delete().where(
                DocumentChunk.document_id.in_([d for d, _ in orphans])
            )
        )
        await pg.commit()
        print(f"\n已删除 {deleted.rowcount or 0} 条孤儿切片。")


if __name__ == "__main__":
    async def _run() -> None:
        try:
            await main(apply="--apply" in sys.argv)
        finally:
            # 显式释放连接池，避免解释器退出时 aiomysql 报 "Event loop is closed"
            await mysql_engine.dispose()
            await pg_engine.dispose()

    asyncio.run(_run())
