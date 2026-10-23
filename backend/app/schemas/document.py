"""
文档 Pydantic Schema — 请求/响应校验

Document（MySQL）和 DocumentChunk（PostgreSQL）是跨数据库的，
所以响应中需要同时包含文档元信息和切片列表。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# 对应 MySQL 里的文档元信息
class DocumentResponse(BaseModel):
    """文档响应（元信息）"""
    id: int
    knowledge_base_id: int
    filename: str
    file_type: str                        # pdf / docx / md / txt
    file_size: int                        # 字节
    status: str                           # pending → processing → completed / failed
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# 对应 PostgreSQL 里的文档切片信息
class DocumentChunkResponse(BaseModel):
    """文档切片响应"""
    id: int
    document_id: int
    chunk_index: int
    content: str                          # 切片文本内容
    extra_meta: Optional[dict] = None     # 额外元数据
    created_at: datetime

    model_config = {"from_attributes": True}

# 文档详情响应，包含文档元信息和切片列表
class DocumentDetailResponse(DocumentResponse):
    """文档详情（含切片列表）"""
    chunks: list[DocumentChunkResponse] = []


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    document: DocumentResponse
    chunk_count: int                      # 实际生成的切片数
    message: str
