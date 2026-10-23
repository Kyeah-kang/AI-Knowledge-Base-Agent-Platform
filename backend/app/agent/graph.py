"""
LangGraph Agent 图 — 思考-行动-观察循环

图的节点和流程：

  call_llm（调用 LLM，传入消息 + 工具定义）
      │
      ▼
  should_continue（判断 LLM 返回的是工具调用还是直接回答）
      │
      ├── "continue" → execute_tool（执行工具，将结果追加到消息列表）
      │                      │
      │                      ▼
      │                 call_llm（带着工具结果再次调用 LLM）
      │
      └── "end" → 返回最终回答


调用方式：
    result = await run_agent(
        messages=[...],
        tools=[...],
        retriever=retriever,
        pg_db=pg_db,
    )
    # result = {"result": str, "tool_calls": int, "iterations": int}
"""

import json
import logging

from app.agent.state import AgentState, get_default_state
from app.agent.tools import execute_tool, get_tool_definitions
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


# ─── 图节点：调用 LLM ───


async def call_llm_node(state: AgentState) -> dict:
    """
    调用 LLM，传入当前消息列表和工具定义。

    LLM 可能返回：
      1. 直接回答（content）→ 流程结束
      2. 工具调用（tool_calls）→ 继续执行工具
    """
    llm = LLMService()
    messages = state["messages"]
    tools = get_tool_definitions()

    # 转成 OpenAI/DeepSeek 的工具调用格式
    openai_tools = [t for t in tools if t.get("type") == "function"]

    iteration = state.get("iteration", 0) + 1
    logger.info(f"Agent 第 {iteration} 轮调用 LLM（消息数: {len(messages)}）")

    # 调用 LLM（带工具定义）
    response = await llm.chat_with_tools(messages, openai_tools)

    # ── 情况 1：LLM 返回了工具调用 ──
    if response.get("type") == "tool_calls":
        tool_calls = response["tool_calls"]

        # 把 assistant 消息（含 tool_calls）加入消息列表
        assistant_msg: dict = {"role": "assistant", "content": None}
        # 组装 OpenAI 格式的 tool_calls
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
        assistant_msg["tool_calls"] = openai_tool_calls

        # 记录每个工具调用的信息到日志
        for tc in tool_calls:
            func = tc.get("function", {})
            logger.info(
                f"  → LLM 决定调用工具: {func.get('name', '?')}"
                f"({func.get('arguments', '{}')})"
            )

        return {
            "messages": [assistant_msg],
            "tool_calls": tool_calls,
            "iteration": iteration,
        }

    # ── 情况 2：LLM 直接回答了 ──
    content = response.get("content", "")
    assistant_msg = {"role": "assistant", "content": content}
    logger.info(f"Agent 第 {iteration} 轮结束，LLM 直接回答（长度: {len(content)}）")

    return {
        "messages": [assistant_msg],
        "tool_calls": [],
        "iteration": iteration,
    }


# ─── 图节点：执行工具 ───


async def execute_tool_node(state: AgentState) -> dict:
    """
    执行当前待办的工具调用，将结果追加到消息列表。

    每个工具调用结果以 "tool" 角色消息加入 messages。
    """
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return {"tool_calls": [], "tool_results": []}

    # 构建 context（传递 RAG 所需信息）
    context = {}
    if state.get("pg_db") is not None:
        from app.rag.embeddings import EmbeddingService
        from app.rag.vector_store import VectorStore
        from app.rag.retriever import Retriever

        embedder = EmbeddingService()
        vector_store = VectorStore(state["pg_db"])
        retriever = Retriever(embedder, vector_store)
        context["retriever"] = retriever

    if state.get("knowledge_base_ids"):
        context["kb_ids"] = state["knowledge_base_ids"]

    # 逐一执行工具
    tool_messages = []
    results = []
    for tc in tool_calls:
        tool_call_id = tc.get("id", f"call_{id(tc)}")
        result_text = await execute_tool(tc, context)
        results.append({"tool_call_id": tool_call_id, "result": result_text})

        # 以 "tool" 角色消息加入对话
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_text,
            }
        )
        logger.info(
            f"  ✓ 工具执行完成: {tc.get('function', {}).get('name', '?')}"
            f" → {result_text[:80]}..."
        )

    return {
        "messages": tool_messages,
        "tool_calls": [],  # 清空待办
        "tool_results": results,
    }


# ─── 条件边：判断是否继续 ───


def should_continue(state: AgentState) -> str:
    """
    判断 Agent 是否继续工具循环。

    返回：
        "continue" → 还有工具要执行
        "end"      → 没有工具调用了，返回最终回答
    """
    tool_calls = state.get("tool_calls", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 10)

    if tool_calls and iteration < max_iterations:
        return "continue"

    if iteration >= max_iterations:
        logger.warning(f"Agent 达到最大迭代次数（{max_iterations}），强制结束")
        # 添加一条提示消息
        return "end"

    return "end"


# ─── 构建并编译图 ───

_agent_app = None


def create_agent_graph():
    """
    构建并编译 LangGraph StateGraph。

    图结构：
        call_llm ──┬── should_continue == "continue" ──→ execute_tool ──→ call_llm
                   │
                   └── should_continue == "end" ──→ END
    """
    try:
        from langgraph.graph import END, StateGraph

        workflow = StateGraph(AgentState)

        # 注册节点
        workflow.add_node("call_llm", call_llm_node)
        workflow.add_node("execute_tool", execute_tool_node)

        # 入口：从 call_llm 开始
        workflow.set_entry_point("call_llm")

        # 条件边：从 call_llm 决定下一步
        workflow.add_conditional_edges(
            "call_llm",
            should_continue,
            {
                "continue": "execute_tool",
                "end": END,
            },
        )

        # 执行完工具后回到 call_llm
        workflow.add_edge("execute_tool", "call_llm")

        return workflow.compile()

    except ImportError as e:
        logger.warning(f"LangGraph 不可用（{e}），使用内置循环模式")
        return None
    except Exception as e:
        logger.warning(f"LangGraph 图构建失败（{e}），使用内置循环模式")
        return None


# ─── 高层 API：运行 Agent ───


async def run_agent(
    messages: list[dict],
    retriever=None,
    pg_db=None,
    knowledge_base_ids: list[int] | None = None,
    session_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """
    运行 Agent 循环，返回最终结果。

    优先使用 LangGraph 编译图；如果 LangGraph 不可用，使用内置循环。

    参数：
        messages: 初始消息列表（已包含 system prompt + 历史消息 + 用户消息）
        retriever: Retriever 实例（知识库检索用）
        pg_db: PostgreSQL 会话
        knowledge_base_ids: 可用知识库 ID 列表
        session_id: 当前会话 ID
        user_id: 当前用户 ID

    返回：
        {
            "result": str,            # 最终回答文本
            "tool_calls_count": int,  # 工具调用次数
            "iterations": int,        # LLM 调用次数
            "intermediate_steps": list,  # 中间步骤记录
        }
    """
    # 构建初始状态
    initial_state = get_default_state(
        messages=messages,
        tool_calls=[],
        tool_results=[],
        iteration=0,
        max_iterations=10,
        session_id=session_id,
        user_id=user_id,
        knowledge_base_ids=knowledge_base_ids,
        pg_db=pg_db,
    )

    try:
        graph = create_agent_graph()
        if graph is not None:
            return await _run_langgraph(graph, initial_state)
        else:
            return await _run_manual_loop(initial_state)
    except Exception as e:
        logger.exception("Agent 执行出错")
        return {
            "result": f"Agent 执行出错：{str(e)}",
            "tool_calls_count": 0,
            "iterations": 0,
            "intermediate_steps": [],
        }


async def _run_langgraph(graph, state: AgentState) -> dict:
    """
    使用 LangGraph 编译图运行 Agent。

    LangGraph 内部已经实现了 call_llm → execute_tool → call_llm 的循环，
    我们只需要调用 graph.ainvoke() 并解析最终状态。
    """
    try:
        final_state = await graph.ainvoke(state)
        return _extract_result(final_state)
    except Exception as e:
        logger.exception("LangGraph 执行失败，降级到内置循环")
        return await _run_manual_loop(state)


async def _run_manual_loop(state: AgentState) -> dict:
    """
    内置 Agent 循环（不依赖 LangGraph）。

    手动实现思考-行动-观察循环：
      while True:
          response = call_llm(messages, tools)
          if no tool_calls → break
          for each tool_call → execute_tool → append result
    """
    current_state = dict(state)
    max_iterations = current_state.get("max_iterations", 10)

    for iteration in range(1, max_iterations + 1):
        # 调用 LLM
        result = await call_llm_node(current_state)
        current_state.update(result)

        # 检查是否需要继续
        decision = should_continue(current_state)
        if decision == "end":
            break

        # 执行工具
        tool_result = await execute_tool_node(current_state)
        current_state.update(tool_result)

    return _extract_result(current_state)


def _extract_result(state: AgentState) -> dict:
    """
    从最终状态中提取返回结果。

    遍历所有 assistant 消息，提取最后的回答。
    """
    messages = state.get("messages", [])
    tool_results = state.get("tool_results", [])
    iteration = state.get("iteration", 0)

    # 收集所有 assistant 消息作为中间步骤
    intermediate_steps = []
    for msg in messages:
        if msg.get("role") == "assistant":
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    intermediate_steps.append(
                        {
                            "type": "tool_call",
                            "function": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                        }
                    )
            elif msg.get("content"):
                intermediate_steps.append(
                    {
                        "type": "answer",
                        "content": msg["content"],
                    }
                )

    # 找最后一个 assistant 的内容作为最终回答
    final_answer = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            final_answer = msg["content"]
            break

    return {
        "result": final_answer,
        "tool_calls_count": len(tool_results),
        "iterations": iteration,
        "intermediate_steps": intermediate_steps,
    }
