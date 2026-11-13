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

import logging

from app.agent.state import AgentState, get_default_state
from app.agent.tools import execute_tool, get_tool_definitions
from app.core.config import settings
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# ─── 达到迭代上限时的兜底（P0-4） ───

# 强制收尾的指令：明确告诉模型"别再调工具，用已有信息回答"
_FINAL_SUMMARY_INSTRUCTION = (
    "现在不要再调用任何工具。请仅基于上面已经获得的工具结果，"
    "直接给出最终回答；如果信息确实不足，请说明还缺什么信息。"
)

# 连总结调用都失败时的兜底文案（必须非空，否则用户看到的就是空回复）
_NO_ANSWER_TEMPLATE = (
    "我已经连续调用了 {n} 轮工具，但没能整理出最终结论。"
    "建议把问题拆成更小的一步，或补充更具体的条件后重试。"
)


async def summarize_without_tools(messages: list[dict], max_iterations: int) -> str:
    """
    达到迭代上限时，强制一次**不带工具**的总结调用。

    为什么需要：
      超限时最后一条 assistant 消息是 `content=None` 的 tool_calls，
      `_extract_result` 取不到正文 → 用户收到空回复。
      这里让模型用"已经拿到的工具结果"给出结论；连这步都失败则返回兜底文案，
      保证调用方拿到的永远是非空字符串。

    异常：
        不抛异常。总结失败属于"可降级"，但降级必须给出可读文案。
    """
    try:
        llm = LLMService()
        final_messages = _close_pending_tool_calls(list(messages)) + [
            {"role": "user", "content": _FINAL_SUMMARY_INSTRUCTION}
        ]
        text = (await llm.chat(final_messages, use_cache=False) or "").strip()
        if text:
            logger.info("Agent 达到迭代上限，已通过一次额外总结调用给出回答")
            return text
    except Exception as e:
        logger.warning("Agent 总结调用失败，使用兜底文案: %s", e)

    return _NO_ANSWER_TEMPLATE.format(n=max_iterations)


def _close_pending_tool_calls(messages: list[dict]) -> list[dict]:
    """
    补齐"悬空的 tool_calls"。

    场景：达到迭代上限时，最后一轮 LLM 刚返回 tool_calls，但循环已经结束、
    工具还没来得及执行。此时消息序列是「... assistant(tool_calls)」而没有对应的
    tool 回复，上游会直接 400：
      An assistant message with 'tool_calls' must be followed by tool messages
      responding to each 'tool_call_id'
    兜底总结因此永远失败、只能退回模板文案。这里补一条说明性的 tool 消息即可。
    """
    if not messages:
        return list(messages)

    last = messages[-1]
    if last.get("role") != "assistant" or not last.get("tool_calls"):
        return list(messages)

    pending = [tc.get("id") for tc in last["tool_calls"] if tc.get("id")]
    if not pending:
        return list(messages)

    patched = list(messages)
    for call_id in pending:
        patched.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "（该工具调用未执行：已达到最大工具轮数）",
            }
        )
    return patched


def _merge_state(state: dict, delta: dict | None) -> None:
    """
    把节点返回值合并进状态。

    关键点：`messages` 是**追加**语义（节点返回的只是"新增的那几条"）。
    `AgentState` 上声明了 `operator.add` reducer，但那只在 LangGraph 图内生效；
    早先这里直接用 `dict.update()`，等于用新消息**替换**整个历史，
    于是 tool 消息丢了前置的 assistant tool_calls，上游 LLM 直接 400（P1-8）。
    """
    for key, value in (delta or {}).items():
        if key == "messages":
            state["messages"] = list(state.get("messages") or []) + list(value or [])
        else:
            state[key] = value


async def _ensure_final_answer(state: dict, max_iterations: int) -> dict:
    """
    保证返回值里一定有非空回答：为空则补一次总结调用（P0-4）。
    """
    result = _extract_result(state)
    if result["result"]:
        return result

    logger.warning(
        "Agent 未产出回答（已用 %s 轮迭代），触发兜底总结", max_iterations
    )
    text = await summarize_without_tools(state.get("messages") or [], max_iterations)
    state["messages"] = list(state.get("messages") or []) + [
        {"role": "assistant", "content": text}
    ]
    return _extract_result(state)


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
    # P0-3：检索范围必须来自"已解析的 document_ids"。
    # 拿不到范围时宁可不提供 retriever（工具会回答"不可用"），
    # 也绝不能让它去全库检索 —— 那等于跨用户数据泄露。
    context: dict = {}
    document_ids = state.get("document_ids") or []
    if state.get("pg_db") is not None and document_ids:
        from app.rag.embeddings import EmbeddingService
        from app.rag.retriever import Retriever
        from app.rag.vector_store import VectorStore

        embedder = EmbeddingService()
        vector_store = VectorStore(state["pg_db"])
        retriever = Retriever(embedder, vector_store)
        context["retriever"] = retriever
        context["document_ids"] = document_ids
    elif state.get("pg_db") is not None:
        logger.info("Agent 没有文档范围（未选知识库），知识库检索工具不可用")

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
    max_iterations = state.get("max_iterations", settings.AGENT_MAX_ITERATIONS)

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
    document_ids: list[int] | None = None,
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
        knowledge_base_ids: 用户选中的知识库 ID（仅记录用途）
        document_ids: **已解析的检索范围**。为空时工具不允许检索（P0-3）
        session_id: 当前会话 ID
        user_id: 当前用户 ID

    返回：
        {
            "result": str,            # 最终回答文本（保证非空）
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
        max_iterations=settings.AGENT_MAX_ITERATIONS,
        session_id=session_id,
        user_id=user_id,
        knowledge_base_ids=knowledge_base_ids,
        document_ids=document_ids,
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

    说明：异常时**仍然降级**到内置循环，但降级路径本身已修好（P1-8），
    且最终一定产出非空回答（P0-4）。
    """
    max_iterations = state.get("max_iterations", settings.AGENT_MAX_ITERATIONS)
    try:
        final_state = await graph.ainvoke(state)
    except Exception:
        logger.exception("LangGraph 执行失败，降级到内置循环")
        return await _run_manual_loop(state)

    return await _ensure_final_answer(dict(final_state), max_iterations)


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
    max_iterations = current_state.get("max_iterations", settings.AGENT_MAX_ITERATIONS)

    for _ in range(1, max_iterations + 1):
        # 调用 LLM
        result = await call_llm_node(current_state)
        _merge_state(current_state, result)

        # 检查是否需要继续
        decision = should_continue(current_state)
        if decision == "end":
            break

        # 执行工具
        tool_result = await execute_tool_node(current_state)
        _merge_state(current_state, tool_result)

    return await _ensure_final_answer(current_state, max_iterations)


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
