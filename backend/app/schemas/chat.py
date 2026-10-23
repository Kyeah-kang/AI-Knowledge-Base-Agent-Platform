"""
聊天相关 Pydantic Schema — 请求/响应数据校验

作用：定义前端和后端之间“聊天数据长什么样”的契约
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.config import settings


# 请求 Schema（前端→后端：校验入参）
class CreateSessionRequest(BaseModel):
    """创建会话的请求参数校验模型"""
    title: str = Field(default="新对话", max_length=100, description="会话标题")
    model_name: str = Field(
        default=settings.LLM_MODEL_NAME,
        max_length=50,
        description="使用的模型名",
    )


class UpdateSessionRequest(BaseModel):
    """更新会话的请求参数校验模型"""
    title: str = Field(..., max_length=100, description="新的会话标题")


class SendMessageRequest(BaseModel):
    """发送消息的请求参数校验模型"""
    content: str = Field(..., min_length=1, description="消息内容")
    system_prompt: Optional[str] = Field(
        None, max_length=2000, description="系统提示词（可选）"
    )
    knowledge_base_ids: Optional[list[int]] = Field(
        None, description="知识库 ID 列表（可选），指定后 RAG 会从这些知识库中检索相关内容注入上下文"
    )


# 响应 Schema（后端→前端：规范返回数据格式）
class ChatMessageResponse(BaseModel):
    """单条消息的响应数据模型"""
    id: int
    session_id: int
    role: str                     # user / assistant / system
    content: str
    extra_meta: Optional[dict] = None
    created_at: datetime

    # 核心配置：支持从 ORM 模型（如 SQLAlchemy 实例）直接转换为该 Pydantic 模型
    # 无需手动映射字段，后端查询数据库后可直接返回，简化代码
    class Config:
        from_attributes = True


class ChatSessionResponse(BaseModel):
    """会话列表的响应数据模型（仅返回会话基本信息，不含消息）"""
    id: int
    title: str
    model_name: str
    created_at: datetime
    updated_at: datetime
    # 消息总数（方便前端显示 "共N条"）
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatSessionDetailResponse(BaseModel):
    """会话详情的响应数据模型（含该会话下的所有消息）"""
    id: int
    title: str
    model_name: str
    created_at: datetime
    updated_at: datetime
    # 核心：嵌套模型，返回该会话下的所有消息列表，每条消息符合 ChatMessageResponse 格式
    messages: list[ChatMessageResponse] = []

    class Config:
        from_attributes = True
