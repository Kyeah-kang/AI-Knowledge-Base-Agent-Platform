"""
B3 回归测试 — 上下文预算（P1-5）、真流式（P1-6）、工具可执行性（P1-7）

三个契约：
  1. 历史消息按 **token 预算** 裁剪，而不是只按固定条数；至少保留最后一条
  2. Agent 的回答是**逐 token** 推给前端的，工具调用参数能从一个流里拼装出来
  3. 没有 executor 的动态工具不会被交给 LLM

不依赖数据库 / 网络。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.agent import tools as tools_mod
from app.agent.tools import execute_tool, get_tool_definitions, register_dynamic_tools
from app.core import metrics
from app.services.agent_service import AgentService
from app.services.llm_service import LLMService
from app.services.message_context import load_history

# ─────────────────── P1-5：token 预算 ───────────────────


class FakeMessageRepo:
    def __init__(self, contents: list[str]):
        self.rows = [
            SimpleNamespace(
                id=i + 1,
                role="user" if i % 2 == 0 else "assistant",
                content=text,
                created_at=datetime(2026, 1, 1, 12, i % 60),
            )
            for i, text in enumerate(contents)
        ]

    async def get_recent_history(self, session_id, limit=20, exclude_id=None):
        return [m for m in self.rows if m.id != exclude_id][-limit:]


@pytest.mark.asyncio
async def test_history_trimmed_by_token_budget():
    # 每条 100 个汉字 ≈ 101 token
    repo = FakeMessageRepo(["中" * 100 for _ in range(6)])

    history = await load_history(repo, 1, token_budget=250)

    assert len(history) == 2, f"250 token 预算应只留下 2 条，实际 {len(history)}"
    # 留下的是**最新**的两条（id 5、6）
    assert history[-1]["content"] == "中" * 100
    assert [m["role"] for m in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_history_under_budget_keeps_everything():
    repo = FakeMessageRepo(["短消息"] * 3)

    history = await load_history(repo, 1, token_budget=10000)

    assert len(history) == 3


@pytest.mark.asyncio
async def test_history_keeps_at_least_one_message_when_over_budget():
    repo = FakeMessageRepo(["中" * 5000])

    history = await load_history(repo, 1, token_budget=10)

    assert len(history) == 1, "即使单条就超预算，也要保留一条，否则对话退化成单轮"


@pytest.mark.asyncio
async def test_history_trim_records_metric():
    metrics.reset()
    repo = FakeMessageRepo(["中" * 200 for _ in range(5)])

    await load_history(repo, 1, token_budget=100)

    counters = metrics.snapshot()["counters"]
    assert counters.get("context_trim_total{reason=token_budget}") == 1


def test_count_tokens_weights_cjk_higher_than_ascii():
    """旧实现 len//4 会把中文低估到 25%，预算等于形同虚设"""
    cjk = LLMService.count_tokens("中" * 100)
    ascii_ = LLMService.count_tokens("a" * 100)
    assert cjk > ascii_ * 3
    assert cjk == 101


# ─────────────────── P1-6：真流式 ───────────────────


def _delta(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()


def _llm_with_stream(chunks) -> LLMService:
    svc = LLMService()

    async def fake_create(**kwargs):
        return FakeStream(chunks)

    svc.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    return svc


@pytest.mark.asyncio
async def test_stream_yields_tokens_incrementally():
    svc = _llm_with_stream([_delta("你"), _delta("好"), _delta("！")])

    events = [
        (kind, payload)
        async for kind, payload in svc.chat_with_tools_stream(
            [{"role": "user", "content": "hi"}], get_tool_definitions()
        )
    ]

    assert [p for k, p in events if k == "token"] == ["你", "好", "！"]
    assert all(k == "token" for k, _ in events)


@pytest.mark.asyncio
async def test_stream_assembles_fragmented_tool_calls():
    """流式下 function.arguments 是分片到达的，必须按 index 拼装"""
    chunks = [
        _delta(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call_a",
                    function=SimpleNamespace(name="calculator", arguments='{"express'),
                )
            ]
        ),
        _delta(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(name=None, arguments='ion":"1+1"}'),
                )
            ]
        ),
        _delta(
            tool_calls=[
                SimpleNamespace(
                    index=1,
                    id="call_b",
                    function=SimpleNamespace(name="web_search", arguments="{}"),
                )
            ]
        ),
    ]
    svc = _llm_with_stream(chunks)

    events = [
        (kind, payload)
        async for kind, payload in svc.chat_with_tools_stream(
            [{"role": "user", "content": "hi"}], get_tool_definitions()
        )
    ]

    tool_events = [p for k, p in events if k == "tool_calls"]
    assert len(tool_events) == 1
    calls = tool_events[0]
    assert [c["id"] for c in calls] == ["call_a", "call_b"]
    assert calls[0]["function"]["arguments"] == '{"expression":"1+1"}'
    assert calls[1]["function"]["name"] == "web_search"


class StreamingFakeLLM:
    """AgentService 用的假 LLM：吐 3 个 token，不调用工具"""

    def __init__(self):
        self.created: list[str] = []

    def build_messages(self, user_content, history=None, system_prompt=None):
        return [{"role": "user", "content": user_content}]

    async def chat_with_tools_stream(self, messages, tools=None, model=None):
        for piece in ("真", "流", "式"):
            yield ("token", piece)


async def _owner(*args, **kwargs):
    return SimpleNamespace(id=1)


async def _noop(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_agent_stream_emits_incremental_token_events():
    saved: list[str] = []

    async def create(session_id, role, content):
        if role == "assistant":
            saved.append(content)
        return SimpleNamespace(id=1, role=role, content=content)

    svc = AgentService.__new__(AgentService)
    svc.llm = StreamingFakeLLM()
    svc._ensure_tools_synced = _noop
    svc.session_repo = SimpleNamespace(verify_owner=_owner, touch=_noop)
    svc.message_repo = SimpleNamespace(
        create=create, get_recent_history=lambda *a, **k: _empty()
    )
    svc._retrieve_rag_context = _noop
    svc._rag_retriever = None
    svc.pg_db = None
    svc.kb_repo = None
    svc.doc_repo = None

    async def _empty():
        return []

    events = [e async for e in svc.chat_stream("hi", user_id=1, session_id=1)]

    token_events = [e for e in events if "event: token" in e]
    assert len(token_events) == 3, f"应该是逐 token 推送，实际 {len(token_events)} 条"
    assert any("event: done" in e for e in events)
    # 落库的是完整拼接后的回答
    assert saved == ["真流式"]


# ─────────────────── P1-7：工具可执行性 ───────────────────


def test_dynamic_tool_without_executor_is_not_exposed():
    register_dynamic_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "http_ping",
                    "description": "只有 schema，没有 executor",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    try:
        names = [d["function"]["name"] for d in get_tool_definitions()]
    finally:
        register_dynamic_tools([])

    assert names == ["web_search", "calculator", "knowledge_retrieval"]
    assert "http_ping" not in names


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_tool():
    result = await execute_tool({"function": {"name": "http_ping", "arguments": "{}"}})

    assert "未知工具" in result


def test_tool_executor_registry_covers_system_tools():
    """系统工具必须都有实现，否则会被 P1-7 的过滤逻辑悄悄摘掉"""
    system_names = {t["function"]["name"] for t in tools_mod._SYSTEM_TOOLS}
    assert system_names == set(tools_mod._TOOL_EXECUTORS)
