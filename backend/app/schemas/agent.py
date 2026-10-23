"""
Agent 系统 Pydantic Schema — 请求/响应模型

包含：
  - AgentChatRequest / AgentChatResponse: Agent 聊天的请求/响应
  - ToolCallResponse: 工具调用记录
  - AgentToolResponse: 工具注册表中的工具信息
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentToolBase(BaseModel):
    """工具注册表基础字段"""
    name: str = Field(..., description="工具标识名")
    display_name: str = Field(..., description="展示名称")
    description: str = Field(..., description="工具描述")
    params_schema: dict = Field(default_factory=dict, description="参数 JSON Schema")


class AgentToolCreate(AgentToolBase):
    """创建工具请求"""
    pass


class AgentToolUpdate(BaseModel):
    """更新工具请求（所有字段可选）"""
    display_name: str | None = None
    description: str | None = None
    params_schema: dict | None = None
    enabled: bool | None = None


class AgentToolResponse(AgentToolBase):
    """工具响应模型"""
    id: int
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ToolCallInfo(BaseModel):
    """工具调用记录（返回给客户端）"""
    name: str = Field(..., description="工具名称")
    arguments: str = Field(..., description="调用参数（JSON 字符串）")
    result: str = Field(..., description="执行结果")
    tool_call_id: str = Field("", description="工具调用 ID")


class AgentChatRequest(BaseModel):
    """Agent 聊天请求"""
    content: str = Field(..., min_length=1, description="用户消息内容")
    session_id: int | None = Field(None, description="会话 ID（复用历史上下文）")
    system_prompt: str | None = Field(None, description="系统提示词（可选）")
    knowledge_base_ids: list[int] | None = Field(
        None, description="知识库 ID 列表（可选，用于 RAG 检索）"
    )


class AgentChatResponse(BaseModel):
    """Agent 聊天响应"""
    reply: str = Field(..., description="Agent 回复内容")
    tool_calls: list[ToolCallInfo] = Field(
        default_factory=list, description="工具调用记录"
    )
    iterations: int = Field(0, description="LLM 调用次数")


class AgentStreamEvent(BaseModel):
    """Agent 流式事件（SSE）"""
    event: str = Field(..., description="事件类型：token / tool_call / rag / error / done")
    data: Any = Field(None, description="事件数据")
