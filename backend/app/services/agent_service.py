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
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import run_agent, summarize_without_tools
from app.agent.tools import get_tool_definitions, register_dynamic_tools
from app.core import metrics
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
from app.services.llm_service import LLMService, resolve_model_name
from app.services.message_context import load_history

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
        model_name: str | None = None,
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

        # 5. 先把知识库展开成文档范围（P0-3）：同一份范围同时用于
        #    "注入 system prompt 的上下文" 和 "工具能不能检索、能检索什么"
        document_ids = await self._resolve_document_ids(knowledge_base_ids, user_id)

        # 6. 构建 system prompt（含 RAG 上下文）
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
            document_ids=document_ids,
        )
        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )

        # 7. 运行 Agent 循环
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        logger.info(f"Agent chat 开始（会话 #{session_id}，历史 {len(history)} 条）")

        agent_result = await run_agent(
            messages=messages,
            pg_db=self.pg_db,
            knowledge_base_ids=knowledge_base_ids,
            document_ids=document_ids,
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
            f"{iterations} 轮迭代，{len(tool_call_infos)} 次工具调用）"
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
        model_name: str | None = None,
    ) -> AsyncGenerator[str]:
        """
        SSE 流式 Agent 对话（对外入口）。

        与 chat_service 同理：StreamingResponse 已经开始输出后再抛异常不会变成
        HTTP 错误，只会断流。这里统一把异常翻译成 `event: error` + `event: done`。
        """
        try:
            async for event in self._stream_events(
                content=content,
                user_id=user_id,
                session_id=session_id,
                system_prompt=system_prompt,
                knowledge_base_ids=knowledge_base_ids,
                model_name=model_name,
            ):
                yield event
            metrics.incr("agent_stream_total", status="ok")
        except AppException as exc:
            metrics.incr("agent_stream_total", status="error")
            logger.warning("Agent 流式对话失败：%s", exc.message)
            yield self._sse_error(exc.message, exc.code)
            yield self._sse_done()
        except Exception:
            metrics.incr("agent_stream_total", status="error")
            logger.exception("Agent 流式对话出现未预期异常")
            yield self._sse_error("服务暂时不可用，请稍后重试", 500)
            yield self._sse_done()

    async def _stream_events(
        self,
        content: str,
        user_id: int,
        session_id: int | None = None,
        system_prompt: str | None = None,
        knowledge_base_ids: list[int] | None = None,
        model_name: str | None = None,
    ) -> AsyncGenerator[str]:
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
                yield "event: error\ndata: {\"message\": \"会话不存在\"}\n\n"
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

        # 5. 先把知识库展开成文档范围（P0-3）
        document_ids = await self._resolve_document_ids(knowledge_base_ids, user_id)

        # 6. RAG 检索（注入 system prompt）
        rag_context = await self._retrieve_rag_context(
            query=content,
            knowledge_base_ids=knowledge_base_ids,
            user_id=user_id,
            document_ids=document_ids,
        )
        if rag_context:
            yield f"event: rag\ndata: {{\"context_length\": {len(rag_context)}}}\n\n"

        effective_system_prompt = self._build_rag_system_prompt(
            rag_context, system_prompt
        )

        # 7. 运行 Agent 循环（P1-6：真流式）
        messages = self.llm.build_messages(content, history, effective_system_prompt)
        logger.info(f"Agent stream 开始（会话 #{session_id}）")

        current_messages = list(messages)
        tool_calls_count = 0
        iterations = 0
        max_iterations = settings.AGENT_MAX_ITERATIONS
        full_reply = ""

        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            pending_tool_calls: list[dict] = []
            turn_text_parts: list[str] = []

            # 一次流式调用同时拿到"回答片段"和"工具调用"：
            # 模型想回答 → token 边生成边推给前端（真流式）；
            # 模型想调工具 → 流结束后收齐参数再去执行。
            async for kind, payload in self.llm.chat_with_tools_stream(
                current_messages,
                get_tool_definitions(),
                model=model_name,
            ):
                if kind == "token":
                    turn_text_parts.append(payload)
                    full_reply += payload
                    yield (
                        f"event: token\n"
                        f"data: {json.dumps({'token': payload}, ensure_ascii=False)}\n\n"
                    )
                elif kind == "tool_calls":
                    pending_tool_calls = payload

            if not pending_tool_calls:
                # 没有工具调用 = 这一轮就是最终回答，直接结束
                break

            # 推送 assistant 的 tool_calls 消息（content 可能为空）
            assistant_msg: dict = {
                "role": "assistant",
                "content": "".join(turn_text_parts) or None,
            }
            openai_tool_calls: list[dict] = []
            for tc in pending_tool_calls:
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

            # 执行每个工具（P0-3：检索范围严格限定在选中的知识库内）
            context: dict[str, Any] = {}
            if self._rag_retriever and document_ids:
                context["retriever"] = self._rag_retriever
                context["document_ids"] = document_ids
            elif self._rag_retriever:
                logger.info("Agent 本次没有文档范围（未选知识库），知识库检索工具不可用")

            for tc in pending_tool_calls:
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

        # 6.5 达到上限仍未拿到正文 → 强制一次不带工具的总结（P0-4）
        #     原来的实现在这里只推一条 error 事件，用户看到的是"没有回答"。
        if not full_reply:
            metrics.incr("agent_max_iterations_total")
            logger.warning(
                "Agent 达到最大迭代次数（%s），触发兜底总结", max_iterations
            )
            full_reply = await summarize_without_tools(current_messages, max_iterations)
            yield (
                f"event: token\n"
                f"data: {json.dumps({'token': full_reply}, ensure_ascii=False)}\n\n"
            )

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
            f"data: {json.dumps({'iterations': iterations, 'tool_calls_count': tool_calls_count, 'model': resolve_model_name(model_name)}, ensure_ascii=False)}\n\n"
        )

        logger.info(
            f"Agent stream 完成（会话 #{session_id}，"
            f"{iterations} 轮迭代，{tool_calls_count} 次工具调用）"
        )

    # ─── 辅助方法 ───

    async def _resolve_document_ids(
        self, knowledge_base_ids: list[int] | None, user_id: int
    ) -> list[int]:
        """
        把"选中的知识库"展开成"允许检索的文档 ID 列表"（P0-3）。

        为什么必须显式展开：
          Agent 的 `knowledge_retrieval` 工具最终调用的是向量检索，
          而向量检索只认 `document_ids`。历史上 kb_ids 传进了 context 却没人用，
          结果"只选 A 库"仍然会命中 B 库的内容 —— 多租户下就是数据泄露。

        异常：
            知识库不属于当前用户 → AppException(404)。
            这里不再"跳过不属于的库"：静默跳过会让检索范围悄悄变大。
        """
        if not knowledge_base_ids or self.doc_repo is None:
            return []

        document_ids: list[int] = []
        for kb_id in knowledge_base_ids:
            kb = await self.kb_repo.verify_owner(kb_id, user_id)
            if not kb:
                raise AppException(
                    code=404, message=f"知识库不存在: {kb_id}", http_status_code=404
                )
            docs, _ = await self.doc_repo.get_by_knowledge_base(kb_id, 0, 10000)
            document_ids.extend(doc.id for doc in docs)

        return document_ids

    async def _retrieve_rag_context(
        self,
        query: str,
        knowledge_base_ids: list[int] | None,
        user_id: int,
        document_ids: list[int] | None = None,
    ) -> str:
        """
        从指定知识库中检索相关文档上下文（用于注入 system prompt）。

        参数：
            document_ids: 已解析好的检索范围。传了就复用，避免重复查库；
                          不传则按 knowledge_base_ids 现场解析。

        逻辑与 chat_service 中的 _retrieve_rag_context 一致。
        """
        if not knowledge_base_ids:
            return ""

        # 选了知识库但向量链路没起来：显式报错，不降级成"没找到"
        if self._rag_retriever is None:
            metrics.incr("rag_retrieval_total", status="unavailable")
            raise AppException(
                code=503,
                message="知识库检索不可用：向量库未连接",
                http_status_code=503,
            )

        all_doc_ids = (
            list(document_ids)
            if document_ids is not None
            else await self._resolve_document_ids(knowledge_base_ids, user_id)
        )

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

    @staticmethod
    def _sse_error(message: str, code: int = 500) -> str:
        """构造标准 SSE 错误事件"""
        payload = json.dumps({"message": message, "code": code}, ensure_ascii=False)
        return f"event: error\ndata: {payload}\n\n"

    @staticmethod
    def _sse_done() -> str:
        """构造 Agent 结束事件（失败时也要发，前端据此收尾）"""
        payload = json.dumps({"iterations": 0, "tool_calls_count": 0}, ensure_ascii=False)
        return f"event: done\ndata: {payload}\n\n"
