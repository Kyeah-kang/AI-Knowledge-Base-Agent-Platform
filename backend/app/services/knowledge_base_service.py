"""
知识库业务逻辑层

知识库是文档的容器，每个用户可以创建多个知识库。
核心流程：创建 → 列表 → 详情 → 更新 → 删除（含级联删除文档）
"""

import logging

from app.core.exceptions import AppException
from app.repositories.document_repo import (
    DocumentChunkRepository,
    DocumentRepository,
)
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository
from app.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    UpdateKnowledgeBaseRequest,
)

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """知识库业务"""

    def __init__(self, db, pg_db=None):
        """
        参数：
            db: MySQL 异步会话（知识库/文档元信息）
            pg_db: PostgreSQL 异步会话（切片）。删除知识库时必须提供，
                   否则 PG 会留下孤儿切片（P1-3）
        """
        self.repo = KnowledgeBaseRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.chunk_repo = DocumentChunkRepository(pg_db) if pg_db is not None else None

    async def create(
        self, user_id: int, request: CreateKnowledgeBaseRequest
    ) -> KnowledgeBaseResponse:
        """创建知识库"""
        kb = await self.repo.create(
            name=request.name,
            description=request.description,
            category=request.category,
            owner_id=user_id,
        )
        return KnowledgeBaseResponse.model_validate(kb)

    async def list_by_user(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[KnowledgeBaseResponse], int]:
        """获取用户的知识库列表（含文档数量）"""
        skip = (page - 1) * page_size
        items, total = await self.repo.get_by_owner_id(user_id, skip=skip, limit=page_size)

        # 为每个知识库填充文档数量
        result = []
        for kb in items:
            doc_count = await self.doc_repo.count_by_knowledge_base(kb.id)
            kb_resp = KnowledgeBaseResponse.model_validate(kb)
            kb_resp.doc_count = doc_count
            result.append(kb_resp)

        return result, total

    async def get_detail(self, kb_id: int, user_id: int) -> KnowledgeBaseResponse:
        """获取知识库详情"""
        kb = await self.repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        doc_count = await self.doc_repo.count_by_knowledge_base(kb.id)
        resp = KnowledgeBaseResponse.model_validate(kb)
        resp.doc_count = doc_count
        return resp

    async def update(
        self, kb_id: int, user_id: int, request: UpdateKnowledgeBaseRequest
    ) -> KnowledgeBaseResponse:
        """更新知识库"""
        kb = await self.repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        kb = await self.repo.update(
            kb_id,
            name=request.name,
            description=request.description,
            category=request.category,
        )
        return KnowledgeBaseResponse.model_validate(kb)

    async def delete(self, kb_id: int, user_id: int) -> None:
        """
        删除知识库（级联删除文档 + 向量切片）。

        顺序很重要（P1-3）：
          1. 先查出该库下所有 document_id
          2. 删除 PostgreSQL 里的切片 —— 跨库没有外键，MySQL 的级联删不掉它们
          3. 最后删 MySQL 的知识库（ORM cascade 会带走 documents）

        为什么必须先清 PG：反过来做的话，MySQL 删完就再也查不到 document_id，
        PG 里的切片会变成无人认领的孤儿，检索仍可能命中"已删除的文档"。
        """
        kb = await self.repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # 1. 收集该库下的文档 ID（一次取完，避免逐文档查询）
        docs, _ = await self.doc_repo.get_by_knowledge_base(kb_id, 0, 100000)
        document_ids = [doc.id for doc in docs]

        # 2. 清 PG 切片
        if document_ids:
            if self.chunk_repo is None:
                # 没有 PG 会话时删库只会留下孤儿切片；宁可失败，也不制造脏数据
                logger.error(
                    "拒绝删除知识库 #%s：PostgreSQL 会话不可用，删除会留下 %s 个文档的孤儿切片",
                    kb_id,
                    len(document_ids),
                )
                raise AppException(
                    code=503,
                    message="向量库不可用，暂时无法安全删除知识库（请稍后重试）",
                    http_status_code=503,
                )
            deleted = await self.chunk_repo.delete_by_document_ids(document_ids)
            logger.info(
                "删除知识库 #%s：清理 %s 个文档的 %s 条切片",
                kb_id,
                len(document_ids),
                deleted,
            )

        # 3. 删 MySQL（ORM cascade 带走 documents）
        await self.repo.delete(kb_id)
