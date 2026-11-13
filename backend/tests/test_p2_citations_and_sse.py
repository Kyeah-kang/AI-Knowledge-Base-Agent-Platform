"""
P2-10 回归测试 —— 引用卡片的数据来源。

覆盖：
  - `_build_citations`：文档名映射、snippet 截断到 160、缺失文件名时降级
  - `_retrieve_rag_context`：返回 (上下文, 引用)，没选库时是 ("", [])
  - SSE `event: rag` 里真的带上了 citations（前端靠它渲染卡片）
"""

import json
from types import SimpleNamespace

import pytest

from app.services.chat_service import ChatService


def _chunk(doc_id: int, text: str, similarity: float = 0.82, index: int = 0) -> dict:
    return {
        "document_id": doc_id,
        "chunk_index": index,
        "content": text,
        "similarity": similarity,
    }


class FakeDocRepo:
    def __init__(self, names: dict[int, str]):
        self.names = names
        self.asked: list[list[int]] = []

    async def get_filenames(self, document_ids):
        self.asked.append(list(document_ids))
        return {d: self.names[d] for d in document_ids if d in self.names}

    async def get_by_knowledge_base(self, kb_id, skip=0, limit=20):
        return [SimpleNamespace(id=doc_id) for doc_id in self.names], len(self.names)


class FakeKbRepo:
    async def verify_owner(self, kb_id, user_id):
        return SimpleNamespace(id=kb_id)


class FakeRetriever:
    def __init__(self, chunks, context="上下文"):
        self.chunks = chunks
        self.context = context
        self.called_with: dict = {}

    async def retrieve_with_details(self, query, top_k=None, document_ids=None):
        self.called_with = {
            "query": query,
            "top_k": top_k,
            "document_ids": document_ids,
        }
        return {
            "has_results": bool(self.chunks),
            "context": self.context,
            "chunks": self.chunks,
            "chunk_count": len(self.chunks),
        }


def make_service(chunks=None, names=None, context="上下文") -> ChatService:
    svc = ChatService.__new__(ChatService)
    svc._rag_retriever = FakeRetriever(chunks or [], context=context)
    svc._kb_repo = FakeKbRepo()
    svc._doc_repo = FakeDocRepo(names or {1: "制度手册.md", 2: "报销流程.md"})
    return svc


# ─────────────────── _build_citations ───────────────────


@pytest.mark.asyncio
async def test_build_citations_maps_filename_and_truncates():
    svc = make_service()
    long_text = "甲" * 500

    citations = await svc._build_citations([_chunk(1, long_text, 0.91, index=2)])

    assert citations == [
        {
            "document_id": 1,
            "document_name": "制度手册.md",
            "chunk_index": 2,
            "similarity": 0.91,
            "snippet": "甲" * 160,
        }
    ]


@pytest.mark.asyncio
async def test_build_citations_falls_back_when_filename_missing():
    svc = make_service(names={1: "制度手册.md"})

    citations = await svc._build_citations([_chunk(99, "内容")])

    assert citations[0]["document_name"] == "文档 #99"


@pytest.mark.asyncio
async def test_build_citations_handles_empty():
    svc = make_service()

    assert await svc._build_citations([]) == []


@pytest.mark.asyncio
async def test_build_citations_queries_filenames_once():
    """top_k=3 也要只查一次库（避免 N+1）"""
    svc = make_service()
    chunks = [_chunk(1, "a"), _chunk(1, "b", index=1), _chunk(2, "c")]

    await svc._build_citations(chunks)

    assert svc._doc_repo.asked == [[1, 1, 2]]


# ─────────────────── _retrieve_rag_context ───────────────────


@pytest.mark.asyncio
async def test_retrieve_rag_context_returns_context_and_citations():
    svc = make_service(chunks=[_chunk(2, "报销时限 15 天", 0.88)], context="资料正文")

    context, citations = await svc._retrieve_rag_context("报销多久内提交", [3], 1)

    assert context == "资料正文"
    assert citations[0]["document_name"] == "报销流程.md"
    assert citations[0]["snippet"] == "报销时限 15 天"


@pytest.mark.asyncio
async def test_retrieve_rag_context_without_kb_returns_empty_pair():
    svc = make_service()

    assert await svc._retrieve_rag_context("你好", None, 1) == ("", [])


@pytest.mark.asyncio
async def test_retrieve_rag_context_raises_when_vector_store_missing():
    from app.core.exceptions import AppException

    svc = make_service()
    svc._rag_retriever = None

    with pytest.raises(AppException) as exc_info:
        await svc._retrieve_rag_context("问题", [1], 1)

    assert exc_info.value.http_status_code == 503


# ─────────────────── SSE rag 事件 ───────────────────


class RecordingLLM:
    def build_messages(self, user_content, history=None, system_prompt=None):
        return [{"role": "user", "content": user_content}]

    def resolve_model(self, requested):
        return "test-model"

    async def chat_stream(self, messages, model=None):
        yield "好"


def _make_stream_service(chunks):
    svc = make_service(chunks=chunks, names={7: "考勤制度.md"})
    svc.llm = RecordingLLM()

    async def _verify(session_id, user_id):
        return SimpleNamespace(id=session_id, model_name="test-model")

    async def _create(**kwargs):
        return SimpleNamespace(id=1)

    async def _touch(_session_id):
        return None

    async def _history(*args, **kwargs):
        return []

    svc.session_repo = SimpleNamespace(verify_owner=_verify, touch=_touch)
    svc.message_repo = SimpleNamespace(create=_create, get_recent_history=_history)
    return svc


@pytest.mark.asyncio
async def test_stream_rag_event_carries_citations():
    svc = _make_stream_service([_chunk(7, "年假 5 天", 0.9)])

    events = [
        event
        async for event in svc.send_message_stream(
            session_id=1,
            user_id=1,
            content="年假几天",
            knowledge_base_ids=[1],
        )
    ]
    text = "".join(events)

    assert "event: rag" in text
    # 后端把 event 行和 data 行拼成一个字符串一次 yield，这里按块解析
    rag_block = next(event for event in events if event.startswith("event: rag"))
    payload = json.loads(rag_block.split("data: ", 1)[1].strip())

    assert payload["context_length"] > 0
    assert payload["citations"][0]["document_name"] == "考勤制度.md"
    assert payload["citations"][0]["snippet"] == "年假 5 天"
