"""
B1 回归测试 — P0-2 / P0-4 / P0-6 / P1-8

四个契约：
  1. 当前问题只进 prompt 一次（chat 与 agent 都必须）
  2. Agent 达到迭代上限时仍给出非空回答
  3. 业务异常的 HTTP 状态码与业务码一致
  4. Agent 降级循环是"追加消息"而不是"替换消息历史"

不依赖数据库 / 网络 / 真实 LLM。
运行：`cd backend && ..\\.venv\\Scripts\\python.exe -m pytest tests/test_b1_agent_and_context.py -q`
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

import app.agent.graph as graph
from app.core.exceptions import AppException
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.services.message_context import load_history

# ─────────────────────── 通用 Fake ───────────────────────


async def _owner(*args, **kwargs):
    return SimpleNamespace(id=1, model_name="test-model")


async def _noop(*args, **kwargs):
    return None


class FakeMessageRepo:
    """
    模拟真实的消息仓储：`create` 之后，后续 `get_recent_history` 会包含刚创建的这条。
    这正是 P0-2 的成因，不能把它简化掉，否则测不出问题。
    """

    def __init__(self, initial=None):
        self.rows = list(initial or [])
        self._next_id = max([m.id for m in self.rows], default=0) + 1
        self.last_exclude_id = "unset"

    async def create(self, session_id, role, content):
        msg = SimpleNamespace(
            id=self._next_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        self._next_id += 1
        self.rows.append(msg)
        return msg

    async def get_recent_history(self, session_id, limit=20, exclude_id=None):
        self.last_exclude_id = exclude_id
        rows = [m for m in self.rows if exclude_id is None or m.id != exclude_id]
        return rows[-limit:]


class RecordingLLM:
    def __init__(self):
        self.messages = None

    def build_messages(self, user_content, history=None, system_prompt=None):
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(history or [])
        msgs.append({"role": "user", "content": user_content})
        return msgs

    async def chat(self, messages, use_cache=True, model=None):
        self.messages = messages
        return "好的"

    async def chat_stream(self, messages, model=None):
        self.messages = messages
        yield "好"
        yield "的"


def _history_rows():
    return [
        SimpleNamespace(id=1, session_id=1, role="user", content="之前的提问"),
        SimpleNamespace(id=2, session_id=1, role="assistant", content="之前的回答"),
    ]


def make_chat_service(message_repo, llm) -> ChatService:
    svc = object.__new__(ChatService)
    svc.session_repo = SimpleNamespace(verify_owner=_owner, touch=_noop)
    svc.message_repo = message_repo
    svc.llm = llm
    svc._rag_retriever = None
    svc._kb_repo = None
    svc._doc_repo = None
    svc.pg_db = None
    return svc


def make_agent_service(message_repo, llm) -> AgentService:
    svc = object.__new__(AgentService)
    svc.llm = llm
    svc.session_repo = SimpleNamespace(verify_owner=_owner, touch=_noop)
    svc.message_repo = message_repo
    svc._rag_retriever = None
    svc.kb_repo = None
    svc.doc_repo = None
    svc.pg_db = None
    svc._sync_tools = True  # 跳过工具同步
    return svc


# ─────────────────── P0-2：当前问题只注入一次 ───────────────────


@pytest.mark.asyncio
async def test_load_history_excludes_current_message():
    repo = FakeMessageRepo(_history_rows())
    # 模拟"当前消息"= 用户刚发的第 3 条
    current = await repo.create(session_id=1, role="user", content="当前问题")

    history = await load_history(repo, 1, current_message_id=current.id)

    assert [m["content"] for m in history] == ["之前的提问", "之前的回答"]
    assert repo.last_exclude_id == current.id


@pytest.mark.asyncio
async def test_chat_send_message_injects_current_question_once():
    repo = FakeMessageRepo(_history_rows())
    llm = RecordingLLM()
    svc = make_chat_service(repo, llm)

    await svc.send_message(session_id=1, user_id=1, content="同一个问题")

    contents = [m["content"] for m in llm.messages]
    assert contents.count("同一个问题") == 1, contents
    # 历史没有被一起丢掉
    assert "之前的提问" in contents and "之前的回答" in contents
    # 当前问题在最后一条
    assert llm.messages[-1] == {"role": "user", "content": "同一个问题"}


@pytest.mark.asyncio
async def test_chat_stream_injects_current_question_once():
    repo = FakeMessageRepo(_history_rows())
    llm = RecordingLLM()
    svc = make_chat_service(repo, llm)

    events = [
        e
        async for e in svc.send_message_stream(
            session_id=1, user_id=1, content="同一个问题"
        )
    ]

    contents = [m["content"] for m in llm.messages]
    assert contents.count("同一个问题") == 1, contents
    assert any('"done": true' in e for e in events)


@pytest.mark.asyncio
async def test_agent_chat_injects_current_question_once(monkeypatch):
    captured = {}

    async def fake_run_agent(messages, **kwargs):
        captured["messages"] = messages
        return {
            "result": "ok",
            "tool_calls_count": 0,
            "iterations": 1,
            "intermediate_steps": [],
        }

    monkeypatch.setattr("app.services.agent_service.run_agent", fake_run_agent)

    repo = FakeMessageRepo(_history_rows())
    llm = RecordingLLM()
    svc = make_agent_service(repo, llm)

    await svc.chat("同一个问题", user_id=1, session_id=1)

    contents = [m["content"] for m in captured["messages"]]
    assert contents.count("同一个问题") == 1, contents
    assert "之前的提问" in contents


# ────────────── P1-8：降级循环必须"追加"而不是"替换"消息 ──────────────


def test_merge_state_appends_messages_and_overwrites_scalars():
    state = {"messages": [{"role": "system", "content": "s"}], "iteration": 0}

    graph._merge_state(
        state,
        {"messages": [{"role": "assistant", "content": None}], "iteration": 1},
    )
    graph._merge_state(
        state, {"messages": [{"role": "tool", "content": "r"}], "tool_calls": []}
    )

    assert [m["role"] for m in state["messages"]] == ["system", "assistant", "tool"]
    assert state["iteration"] == 1
    assert state["tool_calls"] == []


@pytest.mark.asyncio
async def test_manual_loop_keeps_full_tool_history(monkeypatch):
    seen_roles = []

    async def fake_call_llm(state):
        seen_roles.append([m["role"] for m in state["messages"]])
        if len(seen_roles) <= 2:
            tc = [
                {
                    "id": f"c{len(seen_roles)}",
                    "function": {"name": "calculator", "arguments": "{}"},
                }
            ]
            return {
                "messages": [{"role": "assistant", "content": None, "tool_calls": tc}],
                "tool_calls": tc,
                "iteration": len(seen_roles),
            }
        return {
            "messages": [{"role": "assistant", "content": "最终答案"}],
            "tool_calls": [],
            "iteration": len(seen_roles),
        }

    async def fake_exec_tool(state):
        return {
            "messages": [{"role": "tool", "tool_call_id": "c1", "content": "结果"}],
            "tool_calls": [],
            "tool_results": [{"tool_call_id": "c1", "result": "结果"}],
        }

    monkeypatch.setattr(graph, "call_llm_node", fake_call_llm)
    monkeypatch.setattr(graph, "execute_tool_node", fake_exec_tool)

    state = graph.get_default_state(
        messages=[{"role": "user", "content": "q"}], max_iterations=3
    )
    result = await graph._run_manual_loop(state)

    assert result["result"] == "最终答案"
    # 第二轮调用时历史应是完整链条；旧实现用 dict.update() 会把历史替换成 ["tool"]
    assert seen_roles[1] == ["user", "assistant", "tool"], seen_roles
    assert seen_roles[2] == ["user", "assistant", "tool", "assistant", "tool"], seen_roles


@pytest.mark.asyncio
async def test_langgraph_exception_degrades_to_manual_loop(monkeypatch):
    class BoomGraph:
        async def ainvoke(self, state):
            raise RuntimeError("graph broken")

    async def fake_manual(state):
        return {
            "result": "降级回答",
            "tool_calls_count": 0,
            "iterations": 1,
            "intermediate_steps": [],
        }

    monkeypatch.setattr(graph, "_run_manual_loop", fake_manual)

    result = await graph._run_langgraph(
        BoomGraph(), graph.get_default_state(messages=[{"role": "user", "content": "q"}])
    )
    assert result["result"] == "降级回答"


# ────────────── P0-4：达到迭代上限仍要有非空回答 ──────────────


@pytest.mark.asyncio
async def test_manual_loop_falls_back_when_iterations_exhausted(monkeypatch):
    async def always_tool_calls(state):
        tc = [
            {"id": "c", "function": {"name": "calculator", "arguments": "{}"}}
        ]
        return {
            "messages": [{"role": "assistant", "content": None, "tool_calls": tc}],
            "tool_calls": tc,
            "iteration": state.get("iteration", 0) + 1,
        }

    async def fake_exec_tool(state):
        return {
            "messages": [{"role": "tool", "tool_call_id": "c", "content": "1"}],
            "tool_calls": [],
            "tool_results": [],
        }

    async def fake_summarize(messages, max_iterations):
        return f"兜底总结（{max_iterations} 轮）"

    monkeypatch.setattr(graph, "call_llm_node", always_tool_calls)
    monkeypatch.setattr(graph, "execute_tool_node", fake_exec_tool)
    monkeypatch.setattr(graph, "summarize_without_tools", fake_summarize)

    state = graph.get_default_state(
        messages=[{"role": "user", "content": "q"}], max_iterations=2
    )
    result = await graph._run_manual_loop(state)

    assert result["result"] == "兜底总结（2 轮）"


@pytest.mark.asyncio
async def test_summarize_returns_readable_fallback_when_llm_fails(monkeypatch):
    class BoomLLM:
        def __init__(self, *args, **kwargs):
            pass

        async def chat(self, messages, use_cache=True, model=None):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(graph, "LLMService", BoomLLM)

    text = await graph.summarize_without_tools(
        [{"role": "user", "content": "q"}], max_iterations=4
    )

    assert text.strip(), "兜底文案不能为空"
    assert "4" in text
    assert "工具" in text


def test_close_pending_tool_calls_appends_placeholder_tool_messages():
    """
    达到上限时最后一轮可能停在 assistant(tool_calls) 而没有 tool 回复；
    上游会 400（insufficient tool messages），导致兜底总结永远走模板。
    """
    messages = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "calculator", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "calculator", "arguments": "{}"}},
            ],
        },
    ]

    patched = graph._close_pending_tool_calls(messages)

    assert [m["role"] for m in patched] == ["user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in patched[2:]] == ["c1", "c2"]
    # 不改动原列表
    assert len(messages) == 2


def test_close_pending_tool_calls_is_noop_when_balanced():
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "1"},
        {"role": "assistant", "content": "答案"},
    ]
    assert graph._close_pending_tool_calls(messages) == messages


# ────────────── P0-6：业务异常的 HTTP 状态码语义 ──────────────


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422, 429, 500, 502, 503])
def test_app_exception_uses_code_as_http_status(code):
    assert AppException(code=code).http_status_code == code


def test_app_exception_non_http_code_falls_back_to_400():
    # 纯业务码（不是合法 HTTP 状态码）仍然退回 400
    assert AppException(code=1001).http_status_code == 400


def test_app_exception_explicit_http_status_wins():
    exc = AppException(code=401, http_status_code=400)
    assert exc.http_status_code == 400


def test_app_exception_str_keeps_message():
    """基线 bug：没有调用父类构造，str(exc) 是空字符串，日志与用户文案都变成空白"""
    exc = AppException(code=400, message="用户名或密码错误")
    assert str(exc) == "用户名或密码错误"


# ────────── 工具注册表去重（Agent 400 的根因） ──────────


def test_tool_definitions_dedupe_system_and_dynamic():
    """
    seed_data.py 会把 3 个内建工具写进数据库，注册成动态工具后与系统工具同名。
    重复的 tool name 会让上游返回 400 Tool names must be unique，Agent 全挂。
    """
    from app.agent import tools as tools_mod

    duplicated = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "dup",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ["web_search", "calculator", "knowledge_retrieval", "extra_tool"]
    ]

    tools_mod.register_dynamic_tools(duplicated)
    try:
        names = [d["function"]["name"] for d in tools_mod.get_tool_definitions()]
    finally:
        tools_mod.register_dynamic_tools([])  # 恢复全局注册表

    assert len(names) == len(set(names)), f"tool name 重复: {names}"
    assert "web_search" in names
    # P1-7 之后：没有 executor 的动态工具不暴露给 LLM，即使名字不冲突
    assert "extra_tool" not in names
