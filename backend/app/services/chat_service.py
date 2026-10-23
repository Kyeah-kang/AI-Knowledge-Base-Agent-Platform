"""
聊天业务逻辑 — 会话管理 + 消息发送

作用：决定"发一条消息要做哪些事"的大脑

核心流程（发送消息）：
  1. 保存用户消息到数据库
  2. 加载最近 N 条历史消息
  3. （RAG）如果指定了知识库，检索相关切片注入上下文
  4. 组装成 LLM API 的消息格式
  5. 调用 LLM（非流式或流式）
  6. 保存 AI 回复到数据库
  7. 返回回复内容
"""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.chat import ChatMessage
from app.rag.embeddings import EmbeddingService
from app.rag.vector_store import VectorStore
from app.rag.retriever import Retriever
from app.repositories.chat_repo import ChatMessageRepository, ChatSessionRepository
from app.repositories.document_repo import DocumentRepository
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    UpdateSessionRequest,
)
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class ChatService:
    """聊天业务服务类，封装所有聊天相关业务逻辑"""

    def __init__(self, db: AsyncSession, pg_db: AsyncSession | None = None):
        """
        构造方法：依赖注入
        :param db: MySQL 异步数据库会话
        :param pg_db: PostgreSQL 异步会话（可选，用于 RAG 检索）
        """
        # 实例化会话数据仓储，操作聊天会话表
        self.session_repo = ChatSessionRepository(db)
        # 实例化消息数据仓储，操作聊天消息表
        self.message_repo = ChatMessageRepository(db)
        # 实例化大模型调用服务
        self.llm = LLMService()

        # RAG 组件（可选：需要 pg_db 且 Embedding 服务可用）
        self.pg_db = pg_db
        self._rag_retriever = None
        self._kb_repo = None
        self._doc_repo = None
        if pg_db is not None:
            embedder = EmbeddingService()
            vector_store = VectorStore(pg_db)
            self._rag_retriever = Retriever(embedder, vector_store)
            self._kb_repo = KnowledgeBaseRepository(db)
            self._doc_repo = DocumentRepository(db)

    async def _retrieve_rag_context(
        self,
        query: str,
        knowledge_base_ids: list[int] | None,
        user_id: int,
    ) -> str:
        """
        从指定知识库中检索与问题相关的文档上下文。

        流程：
          1. 校验用户对每个 KB 的访问权限
          2. 获取这些 KB 下所有文档的 ID
          3. 用 Retriever 检索相关切片
          4. 返回格式化后的上下文

        参数：
            query: 用户问题
            knowledge_base_ids: 知识库 ID 列表
            user_id: 当前用户 ID

        返回：
            格式化后的上下文文本，如果不需要 RAG 则返回空字符串
        """
        if not knowledge_base_ids or not self._rag_retriever:
            return ""

        if not self._rag_retriever.embedder.is_available:
            logger.warning("RAG 检索跳过：Embedding 服务不可用")
            return ""

        # 校验每个知识库的归属
        all_doc_ids = []
        for kb_id in knowledge_base_ids:
            kb = await self._kb_repo.verify_owner(kb_id, user_id)
            if not kb:
                raise AppException(code=404, message=f"知识库不存在: {kb_id}")
            docs, _ = await self._doc_repo.get_by_knowledge_base(kb_id, 0, 9999)
            all_doc_ids.extend(doc.id for doc in docs)

        if not all_doc_ids:
            logger.info(f"RAG 检索跳过：知识库中没有文档（{knowledge_base_ids}）")
            return ""

        # 执行检索
        context = await self._rag_retriever.retrieve(
            query=query,
            top_k=settings.VECTOR_TOP_K,
            document_ids=all_doc_ids,
        )
        return context

    def _build_rag_system_prompt(self, context: str, original_prompt: str | None) -> str:
        """
        构建包含 RAG 上下文的系统提示词。

        如果检索到相关文档，将文档内容注入到 system prompt 末尾。
        """
        if not context:
            return original_prompt or "你是智能AI助手，请根据你的知识回答用户问题。"

        rag_instruction = (
            "\n\n"
            "请基于以下提供的文档内容回答用户问题。"
            "如果文档中有相关信息，优先使用文档内容回答；"
            "如果文档中没有相关信息，请说明文档中没有相关内容，然后基于你的知识回答。"
        )

        if original_prompt:
            return original_prompt + rag_instruction + "\n\n" + context
        else:
            return "你是智能AI助手。请基于以下提供的文档内容回答用户问题。\n\n" + context


    # 会话管理

    # 创建新会话
    async def create_session(
        self, user_id: int, request: CreateSessionRequest
    ) -> ChatSessionResponse:
        """
        创建新聊天会话
        :param user_id: 当前用户ID
        :param request: 创建会话的请求参数（标题、模型名）
        :return: 会话信息响应模型
        """
        # 调用仓储层，向数据库插入一条新会话数据
        session = await self.session_repo.create(
            user_id=user_id,
            title=request.title,
            model_name=request.model_name,
        )
        # 组装并返回标准响应数据，新会话默认消息数为0
        return ChatSessionResponse(
            id=session.id,
            title=session.title,
            model_name=session.model_name,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=0,
        )

    # 分页查询用户会话列表
    async def list_sessions(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[ChatSessionResponse], int]:
        """
        分页获取当前用户的所有会话列表
        :param user_id: 用户ID
        :param page: 页码，默认第1页
        :param page_size: 每页条数，默认20条
        :return: 会话列表、数据总条数
        """
        # 计算分页偏移量：跳过前面多少条数据
        skip = (page - 1) * page_size
        # 调用仓储层分页查询该用户会话，同时获取会话总数
        sessions, total = await self.session_repo.get_by_user_id(
            user_id, skip=skip, limit=page_size
        )

        # 给每个会话附加消息数量
        result = []
        # 遍历每一个会话，单独查询该会话下的消息总数
        for s in sessions:
            count = await self.message_repo.count_by_session(s.id)
            # 封装为统一响应模型
            result.append(
                ChatSessionResponse(
                    id=s.id,
                    title=s.title,
                    model_name=s.model_name,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    message_count=count,
                )
            )

        return result, total

    # 获取会话详情（含历史消息）
    async def get_session_detail(
        self, session_id: int, user_id: int
    ) -> ChatSessionDetailResponse:
        """
        获取会话详情（包含该会话下所有历史消息）
        :param session_id: 会话ID
        :param user_id: 当前操作用户ID
        :return: 会话详情+消息列表
        """
        # 校验会话归属：判断该会话是否属于当前用户（防越权访问）
        session = await self.session_repo.verify_owner(session_id, user_id)
        if not session:
            raise AppException(code=404, message="会话不存在")
        # 查询该会话下所有消息
        messages, _ = await self.message_repo.get_by_session(session_id)
        # ORM对象转为Pydantic响应模型并返回
        return ChatSessionDetailResponse(
            id=session.id,
            title=session.title,
            model_name=session.model_name,
            created_at=session.created_at,
            updated_at=session.updated_at,
            messages=[ChatMessageResponse.model_validate(m) for m in messages],
        )

    # 修改会话标题
    async def update_session(
        self, session_id: int, user_id: int, request: UpdateSessionRequest
    ) -> ChatSessionResponse:
        """
        修改会话标题
        :param session_id: 会话ID
        :param user_id: 当前用户ID
        :param request: 更新请求参数（新标题）
        :return: 更新后的会话信息
        """
        session = await self.session_repo.verify_owner(session_id, user_id)
        if not session:
            raise AppException(code=404, message="会话不存在")

        session = await self.session_repo.update(
            session_id, title=request.title
        )
        return ChatSessionResponse.model_validate(session)

    # 删除会话
    async def delete_session(self, session_id: int, user_id: int) -> None:
        """
        删除会话（连带删除该会话下所有消息）
        :param session_id: 会话ID
        :param user_id: 当前用户ID
        """
        session = await self.session_repo.verify_owner(session_id, user_id)
        if not session:
            raise AppException(code=404, message="会话不存在")
        # 调用仓储层删除会话（级联删除消息）
        await self.session_repo.delete(session_id)

    # 消息发送（非流式）
    async def send_message(
        self,
        session_id: int,
        user_id: int,
        content: str,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
    ) -> ChatMessageResponse:
        """
        发送消息并获取 AI 回复（非流式，一次性返回）。

        流程：
          1. 校验会话归属
          2. （RAG）检索相关文档上下文
          3. 保存用户消息
          4. 加载历史消息作为上下文
          5. 组装 messages（含 RAG context）并调用 LLM
          6. 保存 AI 回复
          7. 返回 AI 回复
        """
        # 1. 校验会话归属
        session = await self.session_repo.verify_owner(session_id, user_id)
        if not session:
            raise AppException(code=404, message="会话不存在")

        # 2. RAG 检索（如果指定了知识库）
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
        )
        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )
        if rag_context:
            logger.info(f"RAG: 找到相关上下文（会话 #{session_id}）")

        # 3. 保存用户消息
        user_msg = await self.message_repo.create(
            session_id=session_id,
            role="user",
            content=content,
        )

        # 4. 加载历史消息
        history = await self._get_context_messages(session_id)

        # 5. 组装并调用 LLM
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        reply_text = await self.llm.chat(messages)

        # 6. 保存 AI 回复
        assistant_msg = await self.message_repo.create(
            session_id=session_id,
            role="assistant",
            content=reply_text,
        )

        # 7. 返回 AI 回复
        return ChatMessageResponse.model_validate(assistant_msg)

    # 消息发送（流式 — SSE）
    async def send_message_stream(
        self,
        session_id: int,
        user_id: int,
        content: str,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        发送消息并流式获取 AI 回复（SSE 逐 token 推送）。

        SSE 推送格式：
          data: {"token": "你好", "done": false}
          data: {"token": "世界", "done": false}
          data: {"token": "", "done": true}
        """
        # 1. 校验会话归属
        session = await self.session_repo.verify_owner(session_id, user_id)
        if not session:
            raise AppException(code=404, message="会话不存在")

        # 2. RAG 检索（如果指定了知识库）
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
        )
        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )
        if rag_context:
            logger.info(f"RAG: 找到相关上下文（会话 #{session_id}）")
            yield f"event: rag\ndata: {{\"context_length\": {len(rag_context)}}}\n\n"

        # 3. 保存用户消息
        await self.message_repo.create(
            session_id=session_id,
            role="user",
            content=content,
        )

        # 4. 加载历史消息
        history = await self._get_context_messages(session_id)

        # 5. 组装并调用 LLM（流式）
        messages = self.llm.build_messages(content, history, effective_system_prompt)

        full_reply = ""
        try:
            async for token in self.llm.chat_stream(messages):
                full_reply += token
                yield f"data: {{\"token\": \"{self._escape_json(token)}\", \"done\": false}}\n\n"

            # 6. 流结束后保存完整回复
            await self.message_repo.create(
                session_id=session_id,
                role="assistant",
                content=full_reply,
            )

            # 7. 发送结束信号
            yield f"data: {{\"token\": \"\", \"done\": true}}\n\n"

        except Exception as e:
            # 流式过程中出错，仍然保存已经收到的部分回复
            if full_reply:
                await self.message_repo.create(
                    session_id=session_id,
                    role="assistant",
                    content=full_reply,
                )
            yield f"data: {{\"error\": \"{self._escape_json(str(e))}\", \"done\": true}}\n\n"

    # 辅助方法
    async def _get_context_messages(
        self, session_id: int, limit: int = 20
    ) -> list[dict]:
        """
        获取最近 N 条消息作为 LLM 上下文。

        返回格式（LLM API 要求的格式）：
            [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！"},
            ]
        """
        recent = await self.message_repo.get_recent_history(session_id, limit=limit)
        return [
            {"role": msg.role, "content": msg.content}
            for msg in recent
        ]

    @staticmethod
    def _escape_json(s: str) -> str:
        """转义 JSON 字符串中的特殊字符"""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
