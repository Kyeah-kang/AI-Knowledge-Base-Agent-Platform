"""
文档数据访问层 — Document（MySQL）+ DocumentChunk（PostgreSQL）

Document 和 DocumentChunk 分别在两个数据库中，
所以这个文件提供了两套 Repository：
  - DocumentRepository → 操作 MySQL 的 documents 表
  - DocumentChunkRepository → 操作 PostgreSQL 的 document_chunks 表
"""

import logging
from typing import Any

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

# 操作 MySQL 的 documents 表
class DocumentRepository(BaseRepository[Document]):
    """文档 Repository（MySQL）"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Document)

    # 根据知识库 ID 查询这个知识库下的文档，并支持分页
    async def get_by_knowledge_base(
        self, kb_id: int, skip: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        """获取某个知识库下的所有文档，按创建时间倒序"""
        # 统计这个知识库下的文档总数
        count_query = select(func.count(self.model.id)).where(
            self.model.knowledge_base_id == kb_id
        )
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # 分页查询这个知识库下的文档列表，按创建时间倒序排列
        query = (
            select(self.model)
            .where(self.model.knowledge_base_id == kb_id)
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        items = list(result.scalars().all())

        return items, total

    # 根据文档 ID 查询文档详情（文档数量，包含切片列表）
    async def count_by_knowledge_base(self, kb_id: int) -> int:
        """统计某个知识库下的文档总数"""
        query = select(func.count(self.model.id)).where(
            self.model.knowledge_base_id == kb_id
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    # 更新文档处理状态（pending → processing → completed / failed），以及更新切片数量
    async def update_status(
        self, doc_id: int, status: str, chunk_count: int | None = None
    ) -> Document | None:
        """更新文档处理状态"""
        doc = await self.get(doc_id)
        if not doc:
            return None
        doc.status = status
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        await self.db.flush()          # 把修改写入数据库，但不提交事务（还可以继续修改）
        await self.db.refresh(doc)     # 刷新对象状态，从数据库重新加载数据（获取最新的 updated_at 时间）
        return doc

# 操作 PostgreSQL 的 document_chunks 表
class DocumentChunkRepository:
    """文档切片 Repository（PostgreSQL）

    不继承 BaseRepository，因为 DocumentChunk 继承的是 PostgreSQLBase，
    而 BaseRepository 的泛型约束为 MySQLBase。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> DocumentChunk:
        """创建一条切片记录"""
        obj = DocumentChunk(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    # 批量创建切片
    async def bulk_create(self, chunks: list[dict]) -> list[DocumentChunk]:
        """
        批量创建切片（一次性写入多个切片，减少数据库往返）。
        返回创建的 DocumentChunk 对象列表。
        """
        # 把每个字典变成 DocumentChunk 对象
        objs = [DocumentChunk(**data) for data in chunks]
        # 一次性加入数据库会话
        self.db.add_all(objs)
        await self.db.flush()

        # flush 后 refresh 每个对象，获取数据库生成的 id 和时间
        for obj in objs:
            await self.db.refresh(obj)
        return objs

    # 根据文档 ID 查询这个文档的所有切片，并按索引正序排列
    async def get_by_document(self, document_id: int) -> list[DocumentChunk]:
        """获取某个文档的所有切片（按索引正序）"""
        query = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # 根据文档 ID 删除这个文档的所有切片
    async def delete_by_document(self, document_id: int) -> None:
        """删除某个文档的所有切片"""
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self.db.flush()

    # 统计某个文档的切片数量
    async def count_by_document(self, document_id: int) -> int:
        """统计某个文档的切片数量"""
        query = select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == document_id
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    # ─── 向量相似度搜索（pgvector） ───

    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        document_ids: list[int] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """
        向量相似度搜索 — 使用余弦距离查找最相似的切片。

        参数：
            query_embedding: 查询文本的向量嵌入
            top_k: 返回前 K 条结果
            document_ids: 可选，限定搜索范围（指定文档 ID 列表）

        返回：
            [(chunk, similarity_score), ...] 按相似度降序排列
            similarity_score 范围 [0, 1]，越大越相似
        """
        try:
            # 使用 pgvector 的余弦距离算子（<=> 或 cosine_distance）
            # cosine_distance 返回范围 [0, 2]，1 - distance 转为 [0, 1] 相似度
            distance = DocumentChunk.embedding.cosine_distance(query_embedding)
            query = (
                select(DocumentChunk, (1 - distance).label("similarity"))
                .where(DocumentChunk.embedding.isnot(None))
                .order_by(distance)
                .limit(top_k)
            )

            if document_ids:
                query = query.where(DocumentChunk.document_id.in_(document_ids))

            result = await self.db.execute(query)
            rows = result.all()
            return [(row[0], float(row[1])) for row in rows]

        except Exception as e:
            logger.warning(f"向量相似度搜索失败（pgvector 可能未就绪）: {e}")
            return []

    async def update_embedding(
        self, chunk_id: int, embedding: list[float]
    ) -> None:
        """更新单个切片的向量嵌入"""
        chunk = await self.db.get(DocumentChunk, chunk_id)
        if chunk:
            chunk.embedding = embedding  # type: ignore[assignment]
            await self.db.flush()

    async def update_embeddings_batch(
        self, chunk_ids: list[int], embeddings: list[list[float]]
    ) -> None:
        """批量更新切片向量嵌入"""
        for chunk_id, emb in zip(chunk_ids, embeddings):
            chunk = await self.db.get(DocumentChunk, chunk_id)
            if chunk:
                chunk.embedding = emb  # type: ignore[assignment]
        await self.db.flush()

    async def get_chunks_by_document_ids(
        self, document_ids: list[int], limit: int = 100
    ) -> list[DocumentChunk]:
        """批量获取多个文档的切片"""
        query = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id.in_(document_ids))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
