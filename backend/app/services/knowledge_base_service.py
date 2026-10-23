"""
知识库业务逻辑层

知识库是文档的容器，每个用户可以创建多个知识库。
核心流程：创建 → 列表 → 详情 → 更新 → 删除（含级联删除文档）
"""

from app.core.exceptions import AppException
from app.repositories.document_repo import DocumentRepository
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository
from app.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    UpdateKnowledgeBaseRequest,
)


class KnowledgeBaseService:
    """知识库业务"""

    def __init__(self, db):
        self.repo = KnowledgeBaseRepository(db)
        self.doc_repo = DocumentRepository(db)

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
        """删除知识库（级联删除所有文档）"""
        kb = await self.repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # ORM 级联删除（cascade="all, delete-orphan"）会自动删除关联文档
        await self.repo.delete(kb_id)
