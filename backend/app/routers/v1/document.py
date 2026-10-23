"""
文档路由 — 上传 + 解析 + 切片 + CRUD

POST   /knowledge-bases/{kb_id}/documents    → 上传文档（multipart）
GET    /knowledge-bases/{kb_id}/documents    → 文档列表
GET    /documents/{doc_id}                   → 文档详情（含切片）
DELETE /documents/{doc_id}                   → 删除文档（含切片和文件）
"""

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_vector_db
from app.models.user import User
from app.routers.v1 import get_current_user
from app.schemas.common import PaginationResponse, Response
from app.schemas.document import DocumentDetailResponse, DocumentResponse, DocumentUploadResponse
from app.services.document_service import DocumentService

router = APIRouter(tags=["文档"])


def get_service(
    mysql_db: AsyncSession = Depends(get_db),
    pg_db: AsyncSession = Depends(get_vector_db),
) -> DocumentService:
    """依赖注入：创建 DocumentService 实例（需要两个数据库会话）"""
    return DocumentService(mysql_db, pg_db)


# 上传 + 列表 — 归属于知识库的子路由
# 用 /knowledge-bases/{kb_id}/documents

@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=Response[DocumentUploadResponse],
)
async def upload_document(
    kb_id: int,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_service),
):
    """
    上传文档到知识库。

    支持格式：pdf / docx / md / txt / html
    大小限制：50MB
    上传后自动完成：解析 → 切片 → 存储
    """
    result = await service.upload(
        kb_id=kb_id,
        user_id=current_user.id,
        file_obj=file,
    )
    return Response(data=result)


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=Response[PaginationResponse[DocumentResponse]],
)
async def list_documents(
    kb_id: int,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页条数"),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_service),
):
    """获取知识库下的文档列表"""
    items, total = await service.list_by_knowledge_base(
        kb_id, current_user.id, page=page, page_size=page_size
    )
    return Response(
        data=PaginationResponse(
            items=items, total=total, page=page, page_size=page_size
        )
    )


# 详情 + 删除 — 直接用文档 ID

@router.get(
    "/documents/{doc_id}",
    response_model=Response[DocumentDetailResponse],
)
async def get_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_service),
):
    """获取文档详情（含切片内容）"""
    result = await service.get_detail(doc_id, current_user.id)
    return Response(data=result)


@router.delete(
    "/documents/{doc_id}",
    response_model=Response[None],
)
async def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_service),
):
    """删除文档（从 MySQL / PostgreSQL / 磁盘同时删除）"""
    await service.delete(doc_id, current_user.id)
    return Response(data=None)
