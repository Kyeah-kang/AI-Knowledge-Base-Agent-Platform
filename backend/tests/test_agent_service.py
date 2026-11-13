import asyncio
from types import SimpleNamespace

from app.agent.tools import get_tool_definitions
from app.services.agent_service import AgentService


class FakeLLM:
    def __init__(self):
        self.tools_seen = []
        self.messages_seen = []

    def build_messages(self, user_content, history=None, system_prompt=None):
        return [{"role": "user", "content": user_content}]

    async def chat_with_tools_stream(self, messages, tools=None, model=None):
        """P1-6 之后 Agent 走流式工具调用：产出 ("token", ...) / ("tool_calls", ...)"""
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        yield ("token", "ok")
        # 没有 tool_calls → 这一轮就是最终回答


async def _noop(*args, **kwargs):
    return None


async def _owner(*args, **kwargs):
    return object()


async def _create(*args, **kwargs):
    """message_repo.create 的返回值现在会被用到（取 id 用于排除当前消息）"""
    return SimpleNamespace(id=101, role="user", content=kwargs.get("content", ""))


async def _recent_history(*args, **kwargs):
    return []


def test_chat_stream_passes_tool_definitions_to_llm():
    async def run():
        service = object.__new__(AgentService)
        llm = FakeLLM()
        service.llm = llm
        service._ensure_tools_synced = _noop
        service.session_repo = SimpleNamespace(verify_owner=_owner, touch=_noop)
        # P0-2 后，历史由 services/message_context.load_history 读取
        service.message_repo = SimpleNamespace(
            create=_create, get_recent_history=_recent_history
        )
        service._retrieve_rag_context = _noop
        service._rag_retriever = None

        events = [
            event
            async for event in service.chat_stream("hello", user_id=1, session_id=1)
        ]

        assert events
        assert llm.tools_seen == [get_tool_definitions()]
        assert "ok" in events[0]

    asyncio.run(run())
