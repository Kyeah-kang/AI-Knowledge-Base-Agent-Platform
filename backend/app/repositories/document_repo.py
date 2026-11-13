"""
文档数据访问层 — Document（MySQL）+ DocumentChunk（PostgreSQL）

Document 和 DocumentChunk 分别在两个数据库中，
所以这个文件提供了两套 Repository：
  - DocumentRepository → 操作 MySQL 的 documents 表
  - DocumentChunkRepository → 操作 PostgreSQL 的 document_chunks 表
"""

import logging

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import settings
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

    async def get_filenames(self, document_ids: list[int]) -> dict[int, str]:
        """
        批量取"文档 ID → 文件名"，用于给检索结果加引用来源（P2-10）。

        一次查询搞定：逐条 get() 在 top_k=5 时就是 5 次 SQL。
        """
        if not document_ids:
            return {}
        result = await self.db.execute(
            select(Document.id, Document.filename).where(
                Document.id.in_(document_ids)
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def count_by_owner(self, owner_id: int) -> int:
        """
        某个用户名下所有知识库的文档总数（跨库，P2-9）。

        用 join 而不是逐库求和：后者在库多时是 N+1。
        """
        from app.models.knowledge_base import KnowledgeBase

        result = await self.db.execute(
            select(func.count(Document.id))
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(KnowledgeBase.owner_id == owner_id)
        )
        return result.scalar_one()

    async def count_failed_by_owner(self, owner_id: int) -> int:
        """处理失败的文档数（Dashboard 用它提示"有 N 条失败需要处理"）"""
        from app.models.knowledge_base import KnowledgeBase

        result = await self.db.execute(
            select(func.count(Document.id))
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(
                KnowledgeBase.owner_id == owner_id, Document.status == "failed"
            )
        )
        return result.scalar_one()

    async def get_by_hash(
        self, knowledge_base_id: int, file_hash: str
    ) -> Document | None:
        """
        查同一知识库里是否已有相同内容的文档（内容去重，P0-8）。

        只和"处理成功或正在处理"的文档比对：失败过的文档允许重新上传。
        """
        result = await self.db.execute(
            select(Document)
            .where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.file_hash == file_hash,
                Document.status != "failed",
            )
            .order_by(Document.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # 更新文档处理状态（pending → processing → completed / failed），以及更新切片数量
    async def update_status(
        self,
        doc_id: int,
        status: str,
        chunk_count: int | None = None,
        error_message: str | None = None,
        clear_error: bool = False,
    ) -> Document | None:
        """
        更新文档处理状态。

        参数：
            error_message: 失败原因（只在该参数**显式传入**时覆盖）
            clear_error: 成功时传 True，把上一次的失败原因清空
        """
        doc = await self.get(doc_id)
        if not doc:
            return None
        doc.status = status
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        if error_message is not None:
            doc.error_message = error_message
        if clear_error:
            doc.error_message = None
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

    async def delete_by_document_ids(self, document_ids: list[int]) -> int:
        """
        批量删除多个文档的切片（删除知识库时用，避免逐文档一次 SQL）。

        返回：受影响行数（用于日志与校验）。
        """
        if not document_ids:
            return 0

        result = await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
        )
        await self.db.flush()
        return int(getattr(result, "rowcount", 0) or 0)

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

        异常：
            直接向上抛出。**不再吞异常** —— 检索失败与"没有相关内容"是两件不同的事：
            吞掉之后上层会拿着空上下文让模型自由发挥，对外却显示"没找到相关内容"，
            故障因此永远不可见。
        """
        # 空范围必须等价于"什么都查不到"，而不是"查全库"。
        # 约定：None = 不限制范围；[] = 调用方明确限定了 0 个文档（多租户下的安全约束）。
        if document_ids is not None and not document_ids:
            return []

        # HNSW 的召回由 `hnsw.ef_search` 控制；不设就用数据库默认值（40）。
        # SET LOCAL 只在当前事务内生效，不会污染连接池里的其它请求。
        # 注意：这里必须是字面量（SET 语句不支持绑定参数），值来自配置且已 int() 校验。
        ef_search = int(settings.HNSW_EF_SEARCH)
        await self.db.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))

        # 使用 pgvector 的余弦距离算子（<=> 或 cosine_distance）
        # cosine_distance 返回范围 [0, 2]，1 - distance 转为 [0, 1] 相似度
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        query = (
            select(DocumentChunk, (1 - distance).label("similarity"))
            .where(DocumentChunk.embedding.isnot(None))
            .order_by(distance)
            .limit(top_k)
        )

        if document_ids is not None:
            query = query.where(DocumentChunk.document_id.in_(document_ids))

        try:
            result = await self.db.execute(query)
        except Exception as e:
            metrics.incr("vector_search_total", status="error")
            logger.error("向量相似度搜索失败: %s", e)
            raise

        metrics.incr("vector_search_total", status="ok")
        rows = result.all()
        return [(row[0], float(row[1])) for row in rows]

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
        for chunk_id, emb in zip(chunk_ids, embeddings, strict=True):
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
