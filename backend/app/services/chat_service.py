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

import json
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import AppException
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
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
from app.services.llm_service import LLMService, resolve_model_name
from app.services.message_context import load_history

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
    ) -> tuple[str, list[dict]]:
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
            (上下文文本, 引用列表)。未指定知识库、或知识库内没有文档时返回 ("", [])。
            引用列表用于前端渲染"引用卡片"（P2-10）：
                [{"document_id", "document_name", "chunk_index", "similarity", "snippet"}]

        异常：
            RetrievalError / AppException: 选了知识库但检索链路不可用时抛出。
            **不允许**把"检索坏了"降级成"没找到"——否则模型会拿通用知识作答，
            而用户以为答案来自知识库。
        """
        # 没有选择知识库 = 普通聊天，本轮不使用 RAG，不视为失败
        if not knowledge_base_ids:
            return "", []

        # 选了知识库但向量链路没起来：这是配置/基础设施故障，必须显式报错
        if self._rag_retriever is None:
            metrics.incr("rag_retrieval_total", status="unavailable")
            logger.error("RAG 检索不可用：向量库会话缺失，但请求指定了知识库")
            raise AppException(
                code=503,
                message="知识库检索不可用：向量库未连接",
                http_status_code=503,
            )

        # 仓储与检索器是配套注入的；这里显式校验，别让 None 走到属性访问才崩
        if self._kb_repo is None or self._doc_repo is None:  # pragma: no cover
            metrics.incr("rag_retrieval_total", status="unavailable")
            raise AppException(
                code=503,
                message="知识库检索不可用：仓储未初始化",
                http_status_code=503,
            )

        # 校验每个知识库的归属
        all_doc_ids: list[int] = []
        for kb_id in knowledge_base_ids:
            kb = await self._kb_repo.verify_owner(kb_id, user_id)
            if not kb:
                raise AppException(
                    code=404, message=f"知识库不存在: {kb_id}", http_status_code=404
                )
            docs, _ = await self._doc_repo.get_by_knowledge_base(kb_id, 0, 9999)
            all_doc_ids.extend(doc.id for doc in docs)

        if not all_doc_ids:
            # 知识库是空的：这不是故障，是"确实没有可检索的内容"
            metrics.incr("rag_retrieval_total", status="no_documents")
            logger.info(f"RAG 检索跳过：知识库中没有文档（{knowledge_base_ids}）")
            return "", []

        # 执行检索（失败会抛 RetrievalError，由调用方转成错误事件）
        # 用 retrieve_with_details 而不是 retrieve：既要上下文，也要 chunk 元数据
        detail = await self._rag_retriever.retrieve_with_details(
            query=query,
            top_k=settings.VECTOR_TOP_K,
            document_ids=all_doc_ids,
        )
        chunks = detail.get("chunks") or []
        citations = await self._build_citations(chunks)
        return detail.get("context", ""), citations

    async def _build_citations(self, chunks: list[dict]) -> list[dict]:
        """
        把检索到的切片整理成前端能直接渲染的引用卡片。

        snippet 截断到 160 字：卡片是"让人确认答案出处"，不是再读一遍原文。
        """
        if not chunks:
            return []
        if self._doc_repo is None:  # pragma: no cover - 构造函数里必注入
            return []
        document_ids: list[int] = [
            int(c["document_id"]) for c in chunks if c.get("document_id")
        ]
        names = await self._doc_repo.get_filenames(document_ids)
        citations = []
        for chunk in chunks:
            doc_id = int(chunk.get("document_id") or 0)
            citations.append(
                {
                    "document_id": doc_id,
                    "document_name": names.get(doc_id, f"文档 #{doc_id}"),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "similarity": chunk.get("similarity", 0),
                    "snippet": (chunk.get("content") or "")[:160],
                }
            )
        return citations

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

        # 一次查出本页所有会话的消息数（P1-4：原来在循环里逐个 count，是典型 N+1）
        counts = await self.message_repo.count_by_sessions([s.id for s in sessions])

        result = [
            ChatSessionResponse(
                id=s.id,
                title=s.title,
                model_name=s.model_name,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=counts.get(s.id, 0),
            )
            for s in sessions
        ]

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
        # P1-4：原来固定 limit=100 会**静默**截断长会话，前端以为消息丢了。
        # 现在把上限提到配置值，并把真实总数一起返回（message_total），
        # 被截断时至少是可观测的。
        max_messages = settings.SESSION_DETAIL_MAX_MESSAGES
        messages, message_total = await self.message_repo.get_by_session(
            session_id, 0, max_messages
        )
        if message_total > max_messages:
            logger.warning(
                "会话 #%s 共 %s 条消息，超过详情上限 %s，已截断（前端应改用分页）",
                session_id,
                message_total,
                max_messages,
            )

        # ORM对象转为Pydantic响应模型并返回
        return ChatSessionDetailResponse(
            id=session.id,
            title=session.title,
            model_name=session.model_name,
            created_at=session.created_at,
            updated_at=session.updated_at,
            messages=[ChatMessageResponse.model_validate(m) for m in messages],
            message_total=message_total,
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
        model_name: str | None = None,
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
        rag_context, citations = await self._retrieve_rag_context(
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
        # 会话列表按 updated_at 排序；不更新它，刚聊过的会话永远排不到最前（P1-4）
        await self.session_repo.touch(session_id)

        # 4. 加载历史消息（排除刚保存的当前消息，否则它会进 prompt 两次）
        history = await load_history(
            self.message_repo, session_id, current_message_id=user_msg.id
        )

        # 5. 组装并调用 LLM
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        # P2-4：请求 > 会话 > 配置默认（LLMService 内部再校验白名单）
        reply_text = await self.llm.chat(
            messages, model=model_name or session.model_name
        )

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
        model_name: str | None = None,
    ) -> AsyncGenerator[str]:
        """
        SSE 流式问答（对外入口）。

        为什么多包一层：
          StreamingResponse 一旦开始输出就可能已经写回了 200 响应头，
          生成器内部抛异常不会变成 HTTP 错误，而是**直接断流**——前端只看到连接关闭，
          既没有回答也没有错误提示。所以这里统一把异常翻译成 `event: error`，
          保证"失败"一定以事件形式送达客户端。
        """
        try:
            async for event in self._stream_events(
                session_id=session_id,
                user_id=user_id,
                content=content,
                system_prompt=system_prompt,
                knowledge_base_ids=knowledge_base_ids,
                model_name=model_name,
            ):
                yield event
            metrics.incr("chat_stream_total", status="ok")
        except AppException as exc:
            # 业务异常（如检索不可用、会话不存在）——消息可以直接给用户看
            metrics.incr("chat_stream_total", status="error")
            logger.warning("流式问答失败（会话 #%s）：%s", session_id, exc.message)
            yield self._sse_error(exc.message, exc.code)
            yield self._sse_done()
        except Exception:
            metrics.incr("chat_stream_total", status="error")
            logger.exception("流式问答出现未预期异常（会话 #%s）", session_id)
            yield self._sse_error("服务暂时不可用，请稍后重试", 500)
            yield self._sse_done()

    async def _stream_events(
        self,
        session_id: int,
        user_id: int,
        content: str,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
        model_name: str | None = None,
    ) -> AsyncGenerator[str]:
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
        rag_context, citations = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
        )
        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )
        if rag_context:
            logger.info(f"RAG: 找到相关上下文（会话 #{session_id}）")
            yield (
                "event: rag\n"
                f"data: {json.dumps({'context_length': len(rag_context), 'citations': citations}, ensure_ascii=False)}\n\n"
            )

        # 3. 保存用户消息
        user_msg = await self.message_repo.create(
            session_id=session_id,
            role="user",
            content=content,
        )
        # 会话列表按 updated_at 排序；不更新它，刚聊过的会话永远排不到最前（P1-4）
        await self.session_repo.touch(session_id)

        # 4. 加载历史消息（排除刚保存的当前消息，否则它会进 prompt 两次）
        history = await load_history(
            self.message_repo, session_id, current_message_id=user_msg.id
        )

        # 5. 组装并调用 LLM（流式）
        messages = self.llm.build_messages(content, history, effective_system_prompt)

        full_reply = ""
        # P2-4：请求 > 会话 > 配置默认；resolve 后就是真正会用的模型名
        effective_model = resolve_model_name(model_name or session.model_name)
        try:
            async for token in self.llm.chat_stream(
                messages, model=effective_model
            ):
                full_reply += token
                yield f"data: {{\"token\": \"{self._escape_json(token)}\", \"done\": false}}\n\n"

            # 6. 流结束后保存完整回复
            await self.message_repo.create(
                session_id=session_id,
                role="assistant",
                content=full_reply,
            )

            # 7. 发送结束信号（带上实际模型，便于前端展示与排障）
            yield (
                f'data: {{"token": "", "done": true, "model": "{effective_model}"}}\n\n'
            )

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
    @staticmethod
    def _escape_json(s: str) -> str:
        """转义 JSON 字符串中的特殊字符"""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

    @staticmethod
    def _sse_error(message: str, code: int = 500) -> str:
        """构造标准 SSE 错误事件（前端 useSSE 的 case "error" 会处理它）"""
        payload = json.dumps({"message": message, "code": code}, ensure_ascii=False)
        return f"event: error\ndata: {payload}\n\n"

    @staticmethod
    def _sse_done() -> str:
        """构造结束事件（与普通 token 流共用同一格式，前端据此收尾）"""
        return 'data: {"token": "", "done": true}\n\n'
