"""
Agent 路由 — 工具调用 + Agent 聊天

POST   /api/v1/agent/chat                      → Agent 聊天（非流式，含工具调用）
GET    /api/v1/agent/chat/stream               → Agent 聊天（SSE 流式）
GET    /api/v1/agent/tools                     → 获取所有可用工具列表
POST   /api/v1/agent/tools                     → 创建新工具（管理员）
PUT    /api/v1/agent/tools/{id}/toggle         → 切换工具启用/禁用（管理员）

与普通聊天的区别：
  普通聊天（/chat）→ 直接调用 LLM，支持 RAG，不支持工具调用
  Agent 聊天（/agent）→ 调用 LLM + 工具执行循环，支持 RAG + 工具调用
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.deps import get_db, get_vector_db
from app.models.user import User
from app.routers.v1 import get_current_admin, get_current_user
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentToolCreate,
    AgentToolResponse,
)
from app.schemas.common import Response
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["Agent 智能代理"])


def get_agent_service(
    db: AsyncSession = Depends(get_db),
    pg_db: AsyncSession = Depends(get_vector_db),
) -> AgentService:
    """依赖注入：创建 AgentService 实例"""
    return AgentService(db, pg_db)


# ─── Agent 聊天（非流式） ───


@router.post(
    "/chat",
    summary="Agent 对话（非流式）",
    response_model=Response[AgentChatResponse],
)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """
    Agent 聊天 — 支持工具调用 + RAG 知识库检索。

    与普通聊天的区别：
      - Agent 会自动判断是否需要调用工具（联网搜索、计算器、知识库检索）
      - 支持多轮工具调用后再生成最终回答
      - 会返回工具调用记录

    请求体示例：
        {
            "content": "搜索今天的新闻，然后总结给我",
            "session_id": null,       // 不传则自动创建新会话
            "knowledge_base_ids": [1]  // 可选，指定知识库
        }
    """
    result = await service.chat(
        content=request.content,
        user_id=current_user.id,
        session_id=request.session_id,
        system_prompt=request.system_prompt,
        knowledge_base_ids=request.knowledge_base_ids,
        model_name=request.model_name,
    )
    return Response(data=result)


# ─── Agent 聊天（SSE 流式） ───


@router.post(
    "/chat/stream",
    summary="Agent 对话（SSE 流式，含工具调用事件）",
)
async def agent_chat_stream(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """
    Agent 流式对话（**POST + JSON body**，P1-12）。

    与 chat 同理：消息内容不再放进 URL，避免进入访问日志与代理日志。

    请求体：
        {"content": "算一下 1024*768", "session_id": 1, "knowledge_base_ids": [2]}

    SSE 事件：
        event: session / rag / tool_call / tool_result / token / done / error
    """

    async def event_generator():
        async for event in service.chat_stream(
            content=request.content,
            user_id=current_user.id,
            session_id=request.session_id,
            system_prompt=request.system_prompt,
            knowledge_base_ids=request.knowledge_base_ids,
            model_name=request.model_name,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/tools",
    summary="工具列表",
    response_model=Response[list[AgentToolResponse]],
)
async def list_tools(
    enabled_only: bool = Query(True, description="是否只返回已启用的工具"),
    current_user: User = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    """获取 Agent 工具列表"""
    tools = await service.list_tools(enabled_only=enabled_only)
    return Response(data=tools)


@router.post(
    "/tools",
    summary="新增工具（无 executor 时仅展示，不交给 LLM）",
    response_model=Response[AgentToolResponse],
)
async def create_tool(
    tool_data: AgentToolCreate,
    current_user: User = Depends(get_current_admin),
    service: AgentService = Depends(get_agent_service),
):
    """创建新工具（管理员权限）"""
    tool = await service.create_tool(tool_data)
    return Response(data=tool)


@router.put(
    "/tools/{tool_id}/toggle",
    summary="启用/禁用工具",
    response_model=Response[AgentToolResponse],
)
async def toggle_tool(
    tool_id: int,
    current_user: User = Depends(get_current_admin),
    service: AgentService = Depends(get_agent_service),
):
    """切换工具启用/禁用状态（管理员权限）"""
    tool = await service.toggle_tool(tool_id)
    return Response(data=tool)
