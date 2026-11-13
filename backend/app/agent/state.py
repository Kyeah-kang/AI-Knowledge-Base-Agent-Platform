"""
Agent 状态定义 — LangGraph 的 State 模型

Agent 的工作记忆，包含：
  - 对话消息（含工具调用和结果）
  - 当前待执行的工具调用
  - 当前用户和会话上下文

流程：
  call_llm → should_continue ─┬─ "continue" → execute_tool → call_llm（循环）
                               └─ "end"      → 返回最终回答
"""

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict

from app.core.config import settings


class AgentState(TypedDict):
    """
    Agent 的完整状态。

    每个字段说明：
      messages:    完整的消息列表，包括 system/user/assistant/tool 四种角色
      tool_calls:  LLM 决定要调用的工具列表（本轮）
      tool_results: 工具执行后的结果列表
      iteration:   当前是第几轮思考-行动循环（防止无限循环）
      max_iterations: 最大循环次数
      session_id:  当前聊天会话 ID（用于保存消息）
      user_id:     当前用户 ID（用于权限校验）
      knowledge_base_ids: 用户选中的知识库 ID 列表（仅用于展示/日志）
      document_ids: 已解析的检索范围（选中的知识库下的文档 ID）。
                    **工具检索只认它**：为空时不允许做全库检索（P0-3）。
      pg_db:       PostgreSQL 会话（RAG 检索用）
    """

    messages: Annotated[list[dict], operator.add]
    tool_calls: list[dict]
    tool_results: Annotated[list[dict], operator.add]
    iteration: int
    max_iterations: int
    session_id: int | None
    user_id: int | None
    knowledge_base_ids: list[int] | None
    document_ids: list[int] | None
    pg_db: Any | None  # AsyncSession for PostgreSQL


def get_default_state(**kwargs) -> AgentState:
    """
    创建默认的 Agent 初始状态。

    使用方式：
        state = get_default_state(
            messages=[{"role": "user", "content": "你好"}],
            session_id=1,
            user_id=1,
        )

    任意关键字参数会覆盖默认值。
    """
    defaults: dict[str, Any] = {
        "messages": [],
        "tool_calls": [],
        "tool_results": [],
        "iteration": 0,
        "max_iterations": settings.AGENT_MAX_ITERATIONS,  # 防止工具调用死循环
        "session_id": None,
        "user_id": None,
        "knowledge_base_ids": None,
        "document_ids": None,
        "pg_db": None,
    }
    defaults.update(kwargs)
    return defaults  # type: ignore[return-value]
