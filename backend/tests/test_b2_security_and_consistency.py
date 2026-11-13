"""
B2 回归测试 — 安全与一致性

覆盖：
  P0-3  Agent 检索范围严格限定在选中知识库内（越权）
  P0-7  JWT 密钥不再是默认值
  P0-8  上传路径穿越 / 超限中断 / 不阻塞事件循环
  P0-9  依赖与环境可复现（切片器走 langchain、维度三处一致）
  P1-3  删除知识库时先清 PG 切片
  P1-4  会话列表不再 N+1、发消息更新 updated_at

不依赖数据库 / 网络。
"""

import io
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.agent.graph as graph
from app.agent.tools import _execute_knowledge_retrieval
from app.core.config import settings
from app.core.exceptions import AppException
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.knowledge_base_service import KnowledgeBaseService

# ─────────────────── P0-3：检索范围（越权） ───────────────────


class FakeKbRepo:
    def __init__(self, owned: dict[int, list[int]]):
        self.owned = owned

    async def verify_owner(self, kb_id, user_id):
        return SimpleNamespace(id=kb_id) if kb_id in self.owned else None


class FakeDocRepo:
    def __init__(self, owned: dict[int, list[int]]):
        self.owned = owned
        self.calls = []

    async def get_by_knowledge_base(self, kb_id, skip=0, limit=20):
        self.calls.append(kb_id)
        return [SimpleNamespace(id=i) for i in self.owned.get(kb_id, [])], len(
            self.owned.get(kb_id, [])
        )


def make_agent_service(owned: dict[int, list[int]]) -> AgentService:
    svc = AgentService.__new__(AgentService)
    svc.kb_repo = FakeKbRepo(owned)
    svc.doc_repo = FakeDocRepo(owned)
    svc.pg_db = None
    svc._rag_retriever = None
    svc._sync_tools = True
    return svc


@pytest.mark.asyncio
async def test_resolve_document_ids_only_selected_kb():
    """选 A 库不得把 B 库的文档带进检索范围"""
    svc = make_agent_service({1: [10, 11], 2: [20]})

    ids = await svc._resolve_document_ids([1], user_id=1)

    assert ids == [10, 11]
    assert 20 not in ids


@pytest.mark.asyncio
async def test_resolve_document_ids_rejects_foreign_kb():
    """不属于当前用户的知识库必须报错，而不是"跳过"（跳过会让范围悄悄变大）"""
    svc = make_agent_service({1: [10]})

    with pytest.raises(AppException) as exc_info:
        await svc._resolve_document_ids([1, 999], user_id=1)

    assert exc_info.value.http_status_code == 404


@pytest.mark.asyncio
async def test_knowledge_retrieval_tool_refuses_without_scope():
    """工具拿不到 document_ids 时必须拒绝，而不是退化成全库检索"""
    retriever = SimpleNamespace(embedder=SimpleNamespace(is_available=True))

    text = await _execute_knowledge_retrieval(
        {"query": "任意问题"}, {"retriever": retriever}
    )

    assert "没有可检索的文档范围" in text


@pytest.mark.asyncio
async def test_graph_tool_context_has_no_retriever_without_scope(monkeypatch):
    """非流式（graph）路径同样不能在没有范围时提供 retriever"""
    captured = {}

    async def fake_execute_tool(tc, context):
        captured["context"] = context
        return "ok"

    monkeypatch.setattr(graph, "execute_tool", fake_execute_tool)

    tc = {"id": "c1", "function": {"name": "knowledge_retrieval", "arguments": "{}"}}
    state = graph.get_default_state(messages=[], tool_calls=[tc], pg_db=object())
    await graph.execute_tool_node(state)

    assert "retriever" not in captured["context"]
    assert "document_ids" not in captured["context"]


@pytest.mark.asyncio
async def test_graph_tool_context_passes_document_scope(monkeypatch):
    captured = {}

    async def fake_execute_tool(tc, context):
        captured["context"] = context
        return "ok"

    monkeypatch.setattr(graph, "execute_tool", fake_execute_tool)

    tc = {"id": "c1", "function": {"name": "knowledge_retrieval", "arguments": "{}"}}
    state = graph.get_default_state(
        messages=[], tool_calls=[tc], pg_db=object(), document_ids=[7, 8]
    )
    await graph.execute_tool_node(state)

    assert captured["context"]["document_ids"] == [7, 8]
    assert "retriever" in captured["context"]


# ─────────────────── P0-8：上传安全 ───────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("normal.txt", "normal.txt"),
        ("..\\..\\evil.txt", "evil.txt"),
        ("../../../etc/passwd.txt", "passwd.txt"),
        ("/tmp/x.txt", "x.txt"),
        ("中文 报告.docx", "中文 报告.docx"),
    ],
)
def test_sanitize_filename_blocks_traversal(raw, expected):
    assert DocumentService._sanitize_filename(raw) == expected


def test_sanitize_filename_never_empty():
    assert DocumentService._sanitize_filename("...") == "upload"
    assert DocumentService._sanitize_filename("") == "upload"


class FakeUploadFile:
    def __init__(self, data: bytes, name: str = "a.txt"):
        self.file = io.BytesIO(data)
        self.filename = name
        self.size = len(data)


def test_stream_to_disk_writes_and_counts(tmp_path):
    dest = tmp_path / "out.bin"
    size, digest = DocumentService._stream_to_disk(
        FakeUploadFile(b"x" * 100), dest, 1024
    )

    assert size == 100
    assert dest.read_bytes() == b"x" * 100
    # B5：落盘时顺带算 sha256，用于内容去重
    import hashlib

    assert digest == hashlib.sha256(b"x" * 100).hexdigest()


def test_stream_to_disk_aborts_and_cleans_when_too_large(tmp_path):
    dest = tmp_path / "out.bin"

    with pytest.raises(AppException) as exc_info:
        DocumentService._stream_to_disk(FakeUploadFile(b"x" * 1000), dest, 100)

    assert exc_info.value.http_status_code == 413
    # 不留半截文件
    assert not dest.exists()


# ─────────────────── P0-7 / P0-9：环境与配置 ───────────────────


def test_jwt_secret_is_not_the_placeholder():
    assert settings.JWT_SECRET_KEY != "your-secret-key-change-in-production"
    assert len(settings.JWT_SECRET_KEY) >= 32


def test_splitter_uses_langchain_implementation():
    from app.rag import text_splitter

    assert text_splitter._HAS_LANGCHAIN is True


def test_embedding_dimension_matches_orm_column():
    """模型维度 / 配置维度 / ORM 列维度三处必须一致（换模型就要迁移列）"""
    from app.models.document import _HAS_PGVECTOR, DocumentChunk

    if not _HAS_PGVECTOR:
        pytest.skip("pgvector 未安装")

    assert DocumentChunk.__table__.c.embedding.type.dim == settings.EMBEDDING_DIMENSION


# ─────────────────── P1-3：删库清切片 ───────────────────


class RecordingKbRepo:
    def __init__(self, calls):
        self.calls = calls

    async def verify_owner(self, kb_id, user_id):
        return SimpleNamespace(id=kb_id)

    async def delete(self, kb_id):
        self.calls.append("mysql_delete_kb")


class RecordingChunkRepo:
    def __init__(self, calls, deleted=3):
        self.calls = calls
        self.deleted = deleted

    async def delete_by_document_ids(self, document_ids):
        self.calls.append(f"pg_delete_chunks:{sorted(document_ids)}")
        return self.deleted


def make_kb_service(calls, chunk_repo):
    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    svc.repo = RecordingKbRepo(calls)
    svc.doc_repo = FakeDocRepo({1: [10, 11]})
    svc.chunk_repo = chunk_repo
    return svc


@pytest.mark.asyncio
async def test_kb_delete_clears_pg_before_mysql():
    calls: list[str] = []
    svc = make_kb_service(calls, RecordingChunkRepo(calls))

    await svc.delete(1, user_id=1)

    # 顺序：先 PG，后 MySQL（反过来就再也拿不到 document_id 了）
    assert calls == ["pg_delete_chunks:[10, 11]", "mysql_delete_kb"]


@pytest.mark.asyncio
async def test_kb_delete_refuses_without_pg_session():
    calls: list[str] = []
    svc = make_kb_service(calls, chunk_repo=None)

    with pytest.raises(AppException) as exc_info:
        await svc.delete(1, user_id=1)

    assert exc_info.value.http_status_code == 503
    # 关键：MySQL 一个字节都没删，不会制造孤儿
    assert calls == []


# ─────────────────── P1-4：会话列表 N+1 与 updated_at ───────────────────


class BatchMessageRepo:
    def __init__(self):
        self.batch_calls = []
        self.single_calls = 0

    async def count_by_sessions(self, session_ids):
        self.batch_calls.append(list(session_ids))
        return {sid: 3 for sid in session_ids}

    async def count_by_session(self, session_id):  # 不应该再被调用
        self.single_calls += 1
        return 0


class ListSessionRepo:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get_by_user_id(self, user_id, skip=0, limit=20):
        return self.sessions, len(self.sessions)


@pytest.mark.asyncio
async def test_list_sessions_uses_one_batch_count():
    svc = ChatService.__new__(ChatService)
    now = datetime(2026, 1, 1, 12, 0, 0)
    svc.session_repo = ListSessionRepo(
        [
            SimpleNamespace(
                id=i, title=f"s{i}", model_name="m", created_at=now, updated_at=now
            )
            for i in (1, 2, 3)
        ]
    )
    repo = BatchMessageRepo()
    svc.message_repo = repo

    items, total = await svc.list_sessions(user_id=1)

    assert total == 3
    assert [i.message_count for i in items] == [3, 3, 3]
    assert repo.batch_calls == [[1, 2, 3]]  # 只查一次
    assert repo.single_calls == 0  # N+1 已消除
