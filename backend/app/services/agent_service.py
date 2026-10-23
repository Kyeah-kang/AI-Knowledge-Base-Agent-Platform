"""
Agent 业务逻辑层 — 工具调用 + RAG 融合 + Agent 循环

核心职责：
  1. 管理工具注册表（从数据库加载启用的工具）
  2. 编排 Agent 循环（思考-行动-观察）
  3. Agent 与 RAG 融合（知识库检索作为工具）
  4. 维护会话历史（复用已有聊天会话）
  5. 支持非流式和流式两种输出模式

与现有系统的关系：
  - 复用 ChatSession / ChatMessage 存储对话记录
  - 复用 RAG 组件（Retriever）进行知识库检索
  - 复用 LLMService 调用大模型
  - Agent 聊天可以作为"增强版聊天"在已有会话中使用
"""

import json
import logging
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import run_agent
from app.agent.tools import get_tool_definitions, register_dynamic_tools
from app.core.config import settings
from app.core.exceptions import AppException
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.repositories.agent_repo import AgentToolRepository
from app.repositories.chat_repo import ChatMessageRepository, ChatSessionRepository
from app.repositories.document_repo import DocumentRepository
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository
from app.schemas.agent import (
    AgentChatResponse,
    AgentToolResponse,
    ToolCallInfo,
)
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class AgentService:
    """
    Agent 业务服务

    整合 LLM 调用、工具执行、RAG 检索、会话管理。
    """

    def __init__(self, db: AsyncSession, pg_db: AsyncSession | None = None):
        """
        参数：
            db: MySQL 异步会话（业务数据）
            pg_db: PostgreSQL 异步会话（向量数据，可选）
        """
        self.db = db
        self.pg_db = pg_db

        # 数据访问层
        self.session_repo = ChatSessionRepository(db)
        self.message_repo = ChatMessageRepository(db)
        self.tool_repo = AgentToolRepository(db)
        self.kb_repo = KnowledgeBaseRepository(db)
        self.doc_repo = DocumentRepository(db) if pg_db else None

        # LLM 服务
        self.llm = LLMService()

        # RAG 组件（仅当 pg_db 可用时）
        self._rag_retriever: Retriever | None = None
        if pg_db is not None:
            embedder = EmbeddingService()
            vector_store = VectorStore(pg_db)
            self._rag_retriever = Retriever(embedder, vector_store)

        # 初始化：从数据库加载已启用的工具
        self._sync_tools = False

    async def _ensure_tools_synced(self) -> None:
        """
        确保数据库中的工具定义已同步到 agent/tools.py 的动态注册表。

        只在首次调用时同步一次。
        """
        if self._sync_tools:
            return
        try:
            definitions = await self.tool_repo.get_enabled_definitions()
            if definitions:
                register_dynamic_tools(definitions)
                logger.info(f"已同步 {len(definitions)} 个数据库工具到 Agent 注册表")
            self._sync_tools = True
        except Exception as e:
            logger.warning(f"同步工具注册表失败（仅使用默认系统工具）: {e}")
            self._sync_tools = True

    # ─── 工具管理 ───

    async def list_tools(self, enabled_only: bool = True) -> list[AgentToolResponse]:
        """获取工具列表"""
        if enabled_only:
            tools = await self.tool_repo.get_enabled_tools()
        else:
            tools = await self.tool_repo.get_all_tools()
        return [AgentToolResponse.model_validate(t) for t in tools]

    async def toggle_tool(self, tool_id: int) -> AgentToolResponse:
        """切换工具启用/禁用状态"""
        tool = await self.tool_repo.toggle_enabled(tool_id)
        if not tool:
            raise AppException(code=404, message="工具不存在")
        # 重置同步标记，下次 Agent 调用时重新加载
        self._sync_tools = False
        return AgentToolResponse.model_validate(tool)

    async def create_tool(self, tool_data) -> AgentToolResponse:
        """创建新工具"""
        tool = await self.tool_repo.create_tool(
            name=tool_data.name,
            display_name=tool_data.display_name,
            description=tool_data.description,
            params_schema=tool_data.params_schema,
        )
        self._sync_tools = False
        return AgentToolResponse.model_validate(tool)

    # ─── Agent 聊天（非流式） ───

    async def chat(
        self,
        content: str,
        user_id: int,
        session_id: int | None = None,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
    ) -> AgentChatResponse:
        """
        Agent 聊天入口（非流式）。

        流程：
          1. 创建/复用会话
          2. 保存用户消息
          3. 加载历史消息
          4. 构建 system prompt（含 RAG 上下文）
          5. 运行 Agent 循环（思考-行动-观察）
          6. 保存 AI 回复
          7. 返回结果
        """
        # 1. 确保工具同步
        await self._ensure_tools_synced()

        # 2. 会话管理
        if session_id:
            session = await self.session_repo.verify_owner(session_id, user_id)
            if not session:
                raise AppException(code=404, message="会话不存在")
        else:
            session = await self.session_repo.create(
                user_id=user_id,
                title=content[:50],
                model_name=settings.LLM_MODEL_NAME,
            )
            session_id = session.id

        # 3. 保存用户消息
        await self.message_repo.create(
            session_id=session_id,
            role="user",
            content=content,
        )

        # 4. 加载历史消息
        history = await self._get_context_messages(session_id)

        # 5. 构建 system prompt（含 RAG 上下文）
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
        )
        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )

        # 6. 运行 Agent 循环
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        logger.info(f"Agent chat 开始（会话 #{session_id}，历史 {len(history)} 条）")

        agent_result = await run_agent(
            messages=messages,
            pg_db=self.pg_db,
            knowledge_base_ids=knowledge_base_ids,
            session_id=session_id,
            user_id=user_id,
        )

        result_text = agent_result.get("result", "")
        tool_calls_list = agent_result.get("intermediate_steps", [])
        iterations = agent_result.get("iterations", 0)

        # 7. 保存 AI 回复
        await self.message_repo.create(
            session_id=session_id,
            role="assistant",
            content=result_text,
        )

        # 8. 提取工具调用记录
        tool_call_infos = []
        for step in tool_calls_list:
            if step.get("type") == "tool_call":
                tool_call_infos.append(
                    ToolCallInfo(
                        name=step.get("function", ""),
                        arguments=step.get("arguments", ""),
                        result="",  # 非流式不返回具体结果
                        tool_call_id="",
                    )
                )

        logger.info(
            f"Agent chat 完成（会话 #{session_id}，"
            f"{iterations} 轮迭代，{len(tool_calls_infos)} 次工具调用）"
        )

        return AgentChatResponse(
            reply=result_text,
            tool_calls=tool_call_infos,
            iterations=iterations,
        )

    # ─── Agent 聊天（流式） ───

    async def chat_stream(
        self,
        content: str,
        user_id: int,
        session_id: int | None = None,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Agent 聊天入口（流式 SSE）。

        SSE 事件格式：
          event: tool_call
          data: {"name": "web_search", "arguments": "..."}

          event: token
          data: {"token": "正"}

          event: done
          data: {"iterations": 3, "tool_calls_count": 2}

        流程：
          阶段 1（非流式）：工具调用阶段 — 执行完所有工具调用
          阶段 2（流式）：最终 LLM 回答逐 token 推送
        """
        # 1. 确保工具同步
        await self._ensure_tools_synced()

        # 2. 会话管理
        if session_id:
            session = await self.session_repo.verify_owner(session_id, user_id)
            if not session:
                yield f"event: error\ndata: {{\"message\": \"会话不存在\"}}\n\n"
                return
        else:
            session = await self.session_repo.create(
                user_id=user_id,
                title=content[:50],
                model_name=settings.LLM_MODEL_NAME,
            )
            session_id = session.id
            yield f"event: session\ndata: {{\"session_id\": {session_id}}}\n\n"

        # 3. 保存用户消息
        await self.message_repo.create(
            session_id=session_id,
            role="user",
            content=content,
        )

        # 4. 加载历史消息
        history = await self._get_context_messages(session_id)

        # 5. RAG 检索
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
        )
        if rag_context:
            yield f"event: rag\ndata: {{\"context_length\": {len(rag_context)}}}\n\n"

        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )

        # 6. 运行 Agent 的工具调用阶段（非流式，整轮执行）
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        logger.info(f"Agent stream 开始（会话 #{session_id}）")

        # 手动循环：工具调用阶段逐个推送事件
        current_messages = list(messages)
        tool_calls_count = 0
        iterations = 0
        max_iterations = 10
        full_reply = ""

        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            response = await self.llm.chat_with_tools(
                current_messages, get_tool_definitions()
            )

            if response.get("type") == "tool_calls":
                tool_calls = response["tool_calls"]

                # 推送 assistant 的 tool_calls 消息到消息列表
                assistant_msg: dict = {"role": "assistant", "content": None}
                openai_tool_calls = []
                for tc in tool_calls:
                    openai_tool_calls.append(
                        {
                            "id": tc.get("id", f"call_{iteration}_{len(openai_tool_calls)}"),
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                    )
                    # 推送工具调用事件给客户端
                    yield (
                        f"event: tool_call\n"
                        f"data: {json.dumps({'name': tc['function']['name'], 'arguments': tc['function']['arguments']}, ensure_ascii=False)}\n\n"
                    )
                assistant_msg["tool_calls"] = openai_tool_calls
                current_messages.append(assistant_msg)

                # 执行每个工具
                context = {}
                if self._rag_retriever and knowledge_base_ids:
                    context["retriever"] = self._rag_retriever
                    context["kb_ids"] = knowledge_base_ids

                for tc in tool_calls:
                    from app.agent.tools import execute_tool as exec_tool

                    tool_call_id = tc.get("id", f"call_{id(tc)}")
                    result_text = await exec_tool(tc, context)

                    current_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_text,
                        }
                    )
                    tool_calls_count += 1

                    # 推送工具结果事件
                    yield (
                        f"event: tool_result\n"
                        f"data: {json.dumps({'name': tc['function']['name'], 'result': result_text[:200]}, ensure_ascii=False)}\n\n"
                    )

            elif response.get("type") == "content":
                # LLM 直接回答了 — 流式推送最终回答
                reply_text = response.get("content", "")
                # 直接返回完整内容（或者可以逐字推送，但工具调用阶段已结束）
                yield f"event: token\ndata: {json.dumps({'token': reply_text}, ensure_ascii=False)}\n\n"
                full_reply = reply_text
                break

            if iteration >= max_iterations:
                yield f"event: error\ndata: {{\"message\": \"Agent 达到最大迭代次数\"}}\n\n"
                break

        # 7. 保存 AI 回复
        if full_reply:
            await self.message_repo.create(
                session_id=session_id,
                role="assistant",
                content=full_reply,
            )

        # 8. 发送结束信号
        yield (
            f"event: done\n"
            f"data: {json.dumps({'iterations': iterations, 'tool_calls_count': tool_calls_count}, ensure_ascii=False)}\n\n"
        )

        logger.info(
            f"Agent stream 完成（会话 #{session_id}，"
            f"{iterations} 轮迭代，{tool_calls_count} 次工具调用）"
        )

    # ─── 辅助方法 ───

    async def _retrieve_rag_context(
        self,
        query: str,
        knowledge_base_ids: list[int] | None,
        user_id: int,
    ) -> str:
        """
        从指定知识库中检索相关文档上下文。

        逻辑与 chat_service 中的 _retrieve_rag_context 一致。
        """
        if not knowledge_base_ids or not self._rag_retriever:
            return ""

        if not self._rag_retriever.embedder.is_available:
            return ""

        all_doc_ids = []
        for kb_id in knowledge_base_ids:
            kb = await self.kb_repo.verify_owner(kb_id, user_id)
            if not kb:
                continue
            if self.doc_repo:
                docs, _ = await self.doc_repo.get_by_knowledge_base(kb_id, 0, 9999)
                all_doc_ids.extend(doc.id for doc in docs)

        if not all_doc_ids:
            return ""

        context = await self._rag_retriever.retrieve(
            query=query,
            top_k=settings.VECTOR_TOP_K,
            document_ids=all_doc_ids,
        )
        return context

    def _build_rag_system_prompt(self, context: str, original_prompt: str | None) -> str:
        """
        构建包含 RAG 上下文的系统提示词（与 chat_service 一致）。
        """
        if not context:
            return original_prompt or "你是智能AI助手，可以调用工具来帮助用户解决问题。"

        rag_instruction = (
            "\n\n"
            "请基于以下提供的文档内容回答用户问题。"
            "如果文档中有相关信息，优先使用文档内容回答；"
            "如果文档中没有相关信息，请说明文档中没有相关内容，然后基于你的知识回答。"
        )

        if original_prompt:
            return original_prompt + rag_instruction + "\n\n" + context
        else:
            return "你是智能AI助手，可以调用工具来帮助用户解决问题。\n\n" + context

    async def _get_context_messages(
        self, session_id: int, limit: int = 20
    ) -> list[dict]:
        """获取最近 N 条历史消息作为 LLM 上下文"""
        recent = await self.message_repo.get_recent_history(session_id, limit=limit)
        return [
            {"role": msg.role, "content": msg.content}
            for msg in recent
        ]
