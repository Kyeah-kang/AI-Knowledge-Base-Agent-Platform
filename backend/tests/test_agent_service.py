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

    async def chat_with_tools(self, messages, tools):
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        return {"type": "content", "content": "ok"}


async def _noop(*args, **kwargs):
    return None


async def _owner(*args, **kwargs):
    return object()


def test_chat_stream_passes_tool_definitions_to_llm():
    async def run():
        service = object.__new__(AgentService)
        llm = FakeLLM()
        service.llm = llm
        service._ensure_tools_synced = _noop
        service.session_repo = SimpleNamespace(verify_owner=_owner)
        service.message_repo = SimpleNamespace(create=_noop)
        service._get_context_messages = _noop
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
