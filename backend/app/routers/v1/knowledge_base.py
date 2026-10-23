"""
知识库路由 — 会话管理

POST   /knowledge-bases                  → 创建知识库
GET    /knowledge-bases                  → 知识库列表
GET    /knowledge-bases/{id}             → 知识库详情
PUT    /knowledge-bases/{id}             → 更新知识库
DELETE /knowledge-bases/{id}             → 删除知识库（级联删文档）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.user import User
from app.routers.v1 import get_current_user
from app.schemas.common import PaginationResponse, Response
from app.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    UpdateKnowledgeBaseRequest,
)
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


def get_service(db: AsyncSession = Depends(get_db)) -> KnowledgeBaseService:
    """依赖注入：创建 KnowledgeBaseService 实例"""
    return KnowledgeBaseService(db)


@router.post("", response_model=Response[KnowledgeBaseResponse])
async def create_knowledge_base(
    request: CreateKnowledgeBaseRequest,
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_service),
):
    """创建知识库"""
    result = await service.create(current_user.id, request)
    return Response(data=result)


@router.get("", response_model=Response[PaginationResponse[KnowledgeBaseResponse]])
async def list_knowledge_bases(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页条数"),
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_service),
):
    """获取当前用户的知识库列表"""
    items, total = await service.list_by_user(
        current_user.id, page=page, page_size=page_size
    )
    return Response(
        data=PaginationResponse(
            items=items, total=total, page=page, page_size=page_size
        )
    )


@router.get(
    "/{kb_id}",
    response_model=Response[KnowledgeBaseResponse],
)
async def get_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_service),
):
    """获取知识库详情"""
    result = await service.get_detail(kb_id, current_user.id)
    return Response(data=result)


@router.put(
    "/{kb_id}",
    response_model=Response[KnowledgeBaseResponse],
)
async def update_knowledge_base(
    kb_id: int,
    request: UpdateKnowledgeBaseRequest,
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_service),
):
    """修改知识库信息"""
    result = await service.update(kb_id, current_user.id, request)
    return Response(data=result)


@router.delete(
    "/{kb_id}",
    response_model=Response[None],
)
async def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_service),
):
    """删除知识库（级联删除所有文档和切片）"""
    await service.delete(kb_id, current_user.id)
    return Response(data=None)
