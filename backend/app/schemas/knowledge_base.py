"""
知识库 Pydantic Schema — 请求/响应校验

与阶段5的 chat.py 结构一致，遵循相同的 Response[T] 包装格式。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# 校验前端传来的创建数据库数据
class CreateKnowledgeBaseRequest(BaseModel):
    """创建知识库请求"""
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    description: Optional[str] = Field(None, description="知识库描述")
    category: Optional[str] = Field(None, max_length=50, description="分类")


class UpdateKnowledgeBaseRequest(BaseModel):
    """更新知识库请求（全部可选，只传要改的字段）"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)


class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    owner_id: int
    doc_count: int = 0                  # 文档数量（由 service 填充）
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}     # 允许 Pydantic 直接从 SQLAlchemy ORM 对象转换成响应对象
