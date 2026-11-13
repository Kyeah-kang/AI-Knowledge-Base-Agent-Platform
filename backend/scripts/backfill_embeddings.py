"""
补向量脚本 — 给 embedding 为 NULL 的历史切片补上向量（可重复执行）。

为什么会有这种切片：
  早期版本的 embedding 失败是静默的（P0-1 已修）：文档被标成 completed，
  但切片的 embedding 一直是 NULL，于是这些文档"存在却永远检索不到"。

用法：
    cd backend
    ..\\.venv\\Scripts\\python.exe scripts\\backfill_embeddings.py           # 只看不写
    ..\\.venv\\Scripts\\python.exe scripts\\backfill_embeddings.py --apply   # 真的补

特性：
  - 幂等：只处理 embedding IS NULL 的切片，重复执行不会重复花钱
  - 分批：每批 32 条，避免一次请求过大
  - 维度校验：复用 EmbeddingService 的校验，配置错了会直接报错而不是写入脏数据
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import PostgreSQLAsyncSessionLocal, pg_engine
from app.models.document import DocumentChunk
from app.rag.embeddings import EmbeddingService

BATCH_SIZE = 32


async def main(apply: bool) -> None:
    embedder = EmbeddingService()
    if not embedder.is_available:
        print("未配置 Embedding 服务（EMBEDDING_API_KEY 为空），无法补向量。")
        return

    async with PostgreSQLAsyncSessionLocal() as pg:
        rows = (
            (
                await pg.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.embedding.is_(None))
                    .order_by(DocumentChunk.id)
                )
            )
            .scalars()
            .all()
        )

        print(f"待补向量的切片：{len(rows)} 条（模型 {embedder.model}，{embedder.dimension} 维）")
        if not rows:
            print("没有需要补的切片。")
            return
        if not apply:
            docs = sorted({c.document_id for c in rows})
            print(f"涉及 {len(docs)} 个文档：{docs[:20]}{' ...' if len(docs) > 20 else ''}")
            print("\n（演练模式）加 --apply 才会真的调用 Embedding 并写库。")
            return

        done = 0
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            # 维度不匹配时 embed_batch 会抛 RuntimeError，不会写入脏数据
            vectors = await embedder.embed_batch([c.content for c in batch])
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"向量数量与切片数量不一致：{len(vectors)} vs {len(batch)}"
                )
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
            await pg.flush()
            done += len(batch)
            print(f"  已补 {done}/{len(rows)}")

        await pg.commit()
        print(f"\n完成：共补 {done} 条切片向量。")


if __name__ == "__main__":

    async def _run() -> None:
        try:
            await main(apply="--apply" in sys.argv)
        finally:
            await pg_engine.dispose()

    asyncio.run(_run())
