"""
聊天路由 — 会话管理 + 消息发送 + SSE 流式输出

GET    /api/v1/chat/models                           → 可用模型列表
POST   /api/v1/chat/sessions                          → 创建会话
GET    /api/v1/chat/sessions                          → 会话列表
GET    /api/v1/chat/sessions/{id}                     → 会话详情+历史消息
PUT    /api/v1/chat/sessions/{id}                     → 修改标题
DELETE /api/v1/chat/sessions/{id}                     → 删除会话

POST   /api/v1/chat/sessions/{id}/messages            → 发送消息（非流式）
POST   /api/v1/chat/sessions/{id}/messages/stream     → 发送消息（SSE 流式，消息走 body）
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

@router.get(
    "/models",
    summary="可用模型列表",
    response_model=Response[dict],
)
async def list_models(current_user: User = Depends(get_current_user)):
    """
    可用模型列表（P2-4）。

    前端用它渲染模型下拉框；`default` 是没指定模型时实际会用的那个。
    白名单来自 `LLM_ALLOWED_MODELS`，为空时只允许默认模型。
    """
    from app.core.config import settings
    from app.services.llm_service import resolve_model_name

    allowed = settings.LLM_ALLOWED_MODELS or [settings.LLM_MODEL_NAME]
    return Response(
        data={
            "models": allowed,
            "default": resolve_model_name(None),
            "fallbacks": settings.LLM_FALLBACK_MODELS,
        }
    )


@router.post(
    "/sessions",
    summary="创建会话",
    response_model=Response[ChatSessionResponse],
)
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """创建新会话"""
    result = await service.create_session(current_user.id, request)
    return Response(data=result)


@router.get(
    "/sessions",
    summary="会话列表（含消息数）",
    response_model=Response[PaginationResponse[ChatSessionResponse]],
)
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
    summary="会话详情",
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
    summary="修改会话标题",
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
    summary="删除会话",
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
    summary="发送消息（非流式）",
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
        model_name=request.model_name,
    )
    return Response(data=result)


# 消息发送（SSE 流式）

@router.post(
    "/sessions/{session_id}/messages/stream",
    summary="发送消息（SSE 流式）",
    response_class=StreamingResponse,
)
async def send_message_stream(
    session_id: int,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    发送消息并 SSE 流式获取 AI 回复（**POST + JSON body**）。

    为什么从 GET+query 改成 POST（P1-12）：
      原实现把 user_content 放在 URL 里，会进入 access log、代理日志、
      浏览器历史，且受 URL 长度限制。现在内容走请求体。

    使用方式：
      curl -N -X POST "http://localhost:8000/api/v1/chat/sessions/1/messages/stream" \
        -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
        -d '{"content":"你好","knowledge_base_ids":[1]}'

    返回 SSE 格式：
        data: {"token": "你", "done": false}
        data: {"token": "好", "done": false}
        data: {"token": "", "done": true}
    """

    async def event_generator():
        async for event in service.send_message_stream(
            session_id=session_id,
            user_id=current_user.id,
            content=request.content,
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
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲（生产环境用）
        },
    )
