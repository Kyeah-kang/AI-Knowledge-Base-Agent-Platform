"""
聊天路由 — 会话管理 + 消息发送 + SSE 流式输出

POST   /api/v1/chat/sessions                          → 创建会话
GET    /api/v1/chat/sessions                          → 会话列表
GET    /api/v1/chat/sessions/{id}                     → 会话详情+历史消息
PUT    /api/v1/chat/sessions/{id}                     → 修改标题
DELETE /api/v1/chat/sessions/{id}                     → 删除会话

POST   /api/v1/chat/sessions/{id}/messages            → 发送消息（非流式）
GET    /api/v1/chat/sessions/{id}/messages/stream     → 发送消息（SSE 流式）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.deps import get_db, get_vector_db
from app.models.user import User
from app.routers.v1 import get_current_user
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    SendMessageRequest,
    UpdateSessionRequest,
)
from app.schemas.common import PaginationResponse, Response
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["聊天"])


def get_chat_service(
    db: AsyncSession = Depends(get_db),
    pg_db: AsyncSession = Depends(get_vector_db),
) -> ChatService:
    """依赖注入：创建 ChatService 实例（含可选的 RAG 支持）"""
    return ChatService(db, pg_db)


# 会话管理

@router.post("/sessions", response_model=Response[ChatSessionResponse])
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """创建新会话"""
    result = await service.create_session(current_user.id, request)
    return Response(data=result)


@router.get("/sessions", response_model=Response[PaginationResponse[ChatSessionResponse]])
async def list_sessions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页条数"),
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """获取当前用户的会话列表"""
    items, total = await service.list_sessions(
        current_user.id, page=page, page_size=page_size
    )
    return Response(
        data=PaginationResponse(
            items=items, total=total, page=page, page_size=page_size
        )
    )


@router.get(
    "/sessions/{session_id}",
    response_model=Response[ChatSessionDetailResponse],
)
async def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """获取会话详情（含历史消息）"""
    result = await service.get_session_detail(session_id, current_user.id)
    return Response(data=result)


@router.put(
    "/sessions/{session_id}",
    response_model=Response[ChatSessionResponse],
)
async def update_session(
    session_id: int,
    request: UpdateSessionRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """修改会话标题"""
    result = await service.update_session(session_id, current_user.id, request)
    return Response(data=result)


@router.delete(
    "/sessions/{session_id}",
    response_model=Response[None],
)
async def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """删除会话（级联删除所有消息）"""
    await service.delete_session(session_id, current_user.id)
    return Response(data=None)


# 消息发送（非流式）

@router.post(
    "/sessions/{session_id}/messages",
    response_model=Response[ChatMessageResponse],
)
async def send_message(
    session_id: int,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """发送消息（非流式，等待完整回复后返回）"""
    result = await service.send_message(
        session_id=session_id,
        user_id=current_user.id,
        content=request.content,
        system_prompt=request.system_prompt,
        knowledge_base_ids=request.knowledge_base_ids,
    )
    return Response(data=result)


# 消息发送（SSE 流式）

@router.get(
    "/sessions/{session_id}/messages/stream",
    response_class=StreamingResponse,
)
async def send_message_stream(
    session_id: int,
    content: str = Query(..., min_length=1, description="消息内容"),
    system_prompt: str = Query(None, description="系统提示词（可选）"),
    kb_ids: str = Query(None, description="知识库 ID 列表，逗号分隔，如 '1,2,3'（可选）"),
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    发送消息并 SSE 流式获取 AI 回复。

    使用方式：
      curl -N "http://localhost:8000/api/v1/chat/sessions/1/messages/stream?content=你好"
      curl -N "http://localhost:8000/api/v1/chat/sessions/1/messages/stream?content=你好&kb_ids=1,2"

    返回 SSE 格式：
        data: {"token": "你", "done": false}
        data: {"token": "好", "done": false}
        data: {"token": "", "done": true}
    """
    # 解析 kb_ids 字符串为列表
    knowledge_base_ids = None
    if kb_ids:
        try:
            knowledge_base_ids = [int(x.strip()) for x in kb_ids.split(",") if x.strip()]
        except ValueError:
            pass

    async def event_generator():
        async for event in service.send_message_stream(
            session_id=session_id,
            user_id=current_user.id,
            content=content,
            system_prompt=system_prompt,
            knowledge_base_ids=knowledge_base_ids,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲（生产环境用）
        },
    )
