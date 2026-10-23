"""
VectorStore — pgvector 向量存储与检索

封装 DocumentChunkRepository 的向量操作，提供高层 API：
  - 存储 embedding 到指定 chunk
  - 批量存储 embeddings
  - 相似度搜索（按文档 ID 范围过滤）

用法：
    vector_store = VectorStore(pg_db)
    results = await vector_store.similarity_search(
        query_embedding=[...], top_k=5, kb_id=1
    )
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.document_repo import DocumentChunkRepository

logger = logging.getLogger(__name__)


class VectorStore:
    """
    向量存储 — pgvector 操作封装

    职责：
      1. 向量存储（批量/单个）
      2. 相似度搜索
      3. 结果格式化
    """

    def __init__(self, pg_db: AsyncSession):
        """
        参数：
            pg_db: PostgreSQL 异步会话
        """
        self.pg_db = pg_db
        self.chunk_repo = DocumentChunkRepository(pg_db)

    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        向量相似度搜索。

        参数：
            query_embedding: 查询向量
            top_k: 返回前 K 条结果
            document_ids: 可选，限定文档 ID 列表

        返回：
            [
                {
                    "chunk_id": 1,
                    "document_id": 1,
                    "content": "切片内容...",
                    "chunk_index": 0,
                    "similarity": 0.92,
                },
                ...
            ]
        """
        results = await self.chunk_repo.similarity_search(
            query_embedding=query_embedding,
            top_k=top_k,
            document_ids=document_ids,
        )

        return [
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "similarity": round(similarity, 4),
            }
            for chunk, similarity in results
        ]

    async def store_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        """存储单个切片的向量嵌入"""
        await self.chunk_repo.update_embedding(chunk_id, embedding)

    async def store_embeddings(
        self, chunk_ids: list[int], embeddings: list[list[float]]
    ) -> None:
        """批量存储向量嵌入"""
        await self.chunk_repo.update_embeddings_batch(chunk_ids, embeddings)
