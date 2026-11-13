"""
P0-1 回归测试 — 失败必须可见，不能静默变成"成功"或"没找到"。

这三个契约是本次修复的全部意义：
  1. 向量生成失败 → 文档 `failed`（而不是 `completed`），响应里带原因
  2. 检索链路坏了 → 抛 RetrievalError / AppException（而不是返回空上下文）
  3. 流式问答遇到失败 → 一定发出 `event: error`（而不是断流）

不依赖数据库 / 网络 / 真实 API：session、parser、embedder、vector_store 全部 Fake。
运行：`cd backend && ..\\.venv\\Scripts\\python.exe -m pytest tests/test_p0_1_failure_visibility.py -q`
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import metrics
from app.core.exceptions import AppException, RetrievalError
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever
from app.repositories.document_repo import DocumentChunkRepository
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService

# ─────────────────────────── 通用 Fake ───────────────────────────


class FakeEmbeddingAPI:
    """假的 OpenAI embeddings 接口"""

    def __init__(self, vector: list[float] | None = None, error: Exception | None = None):
        self.vector = vector
        self.error = error

    async def create(self, model: str, input):  # noqa: A002 - 与 SDK 签名保持一致
        if self.error:
            raise self.error
        if isinstance(input, str):
            return SimpleNamespace(data=[SimpleNamespace(embedding=self.vector)])
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=self.vector) for _ in input]
        )


def make_embedding_service(vector=None, dimension: int = 1024, error=None) -> EmbeddingService:
    """绕开构造函数（不读配置、不建 client），直接注入假 API"""
    svc = EmbeddingService.__new__(EmbeddingService)
    svc.model = "fake-embedding-model"
    svc.dimension = dimension
    svc._available = True
    svc.client = SimpleNamespace(embeddings=FakeEmbeddingAPI(vector, error))
    return svc


class FakeEmbedder:
    def __init__(self, available: bool = True, vector=None, error: Exception | None = None):
        self._available = available
        self._vector = vector if vector is not None else [0.1] * 1024
        self._error = error

    @property
    def is_available(self) -> bool:
        return self._available

    async def embed(self, text: str):
        if self._error:
            raise self._error
        return self._vector


class FakeVectorStore:
    def __init__(self, results=None, error: Exception | None = None):
        self._results = results or []
        self._error = error

    async def similarity_search(self, query_embedding, top_k=5, document_ids=None):
        if self._error:
            raise self._error
        return self._results


# ─────────────────── 1. Embedding 维度守卫（写库前拦截）───────────────────


@pytest.mark.asyncio
async def test_embed_rejects_dimension_mismatch():
    """模型返回 8 维，配置是 1024 维 → 必须在写库前报错，而不是让数据库拒绝"""
    svc = make_embedding_service(vector=[0.1] * 8, dimension=1024)
    with pytest.raises(RuntimeError, match="维度不匹配"):
        await svc.embed("你好")


@pytest.mark.asyncio
async def test_embed_batch_rejects_dimension_mismatch():
    svc = make_embedding_service(vector=[0.1] * 8, dimension=1024)
    with pytest.raises(RuntimeError, match="维度不匹配"):
        await svc.embed_batch(["a", "b"])


@pytest.mark.asyncio
async def test_embed_accepts_matching_dimension():
    svc = make_embedding_service(vector=[0.1] * 1024, dimension=1024)
    assert len(await svc.embed("你好")) == 1024


# ─────────────── 2. Retriever：失败要抛，空结果不算失败 ───────────────


@pytest.mark.asyncio
async def test_retriever_raises_when_embedding_unavailable():
    retriever = Retriever(FakeEmbedder(available=False), FakeVectorStore())
    with pytest.raises(RetrievalError) as exc_info:
        await retriever.retrieve("什么是 RAG")
    assert exc_info.value.http_status_code == 503
    assert "未配置 Embedding" in exc_info.value.message


@pytest.mark.asyncio
async def test_retriever_raises_when_vector_search_fails():
    """检索报错不能被当成"没有相关内容"返回空字符串"""
    retriever = Retriever(
        FakeEmbedder(), FakeVectorStore(error=RuntimeError("connection refused"))
    )
    with pytest.raises(RetrievalError) as exc_info:
        await retriever.retrieve("什么是 RAG")
    assert "向量检索出错" in exc_info.value.message
    assert "connection refused" in (exc_info.value.detail or "")


@pytest.mark.asyncio
async def test_retriever_raises_when_embedding_call_fails():
    retriever = Retriever(
        FakeEmbedder(error=RuntimeError("401 Unauthorized")), FakeVectorStore()
    )
    with pytest.raises(RetrievalError, match="查询向量生成失败"):
        await retriever.retrieve("什么是 RAG")


@pytest.mark.asyncio
async def test_retriever_returns_empty_when_no_result():
    """真的没检索到 → 空字符串，且计入 empty 指标（不是异常）"""
    metrics.reset()
    retriever = Retriever(FakeEmbedder(), FakeVectorStore(results=[]))
    assert await retriever.retrieve("无关问题") == ""
    counters = metrics.snapshot()["counters"]
    assert counters.get("rag_retrieval_total{status=empty}") == 1


# ─────────────── 3. Repository：不吞异常 + 空范围不下推 ───────────────


class BoomSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("pg is down")


class RecordingSession:
    def __init__(self):
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("空范围不应该真的去查数据库")


@pytest.mark.asyncio
async def test_similarity_search_propagates_error():
    repo = DocumentChunkRepository(BoomSession())
    with pytest.raises(RuntimeError, match="pg is down"):
        await repo.similarity_search([0.1] * 1024)


@pytest.mark.asyncio
async def test_similarity_search_empty_scope_returns_nothing():
    """document_ids=[] 必须等价于"查不到"，而不是"查全库"（越权风险）"""
    session = RecordingSession()
    repo = DocumentChunkRepository(session)
    assert await repo.similarity_search([0.1] * 1024, document_ids=[]) == []
    assert session.calls == 0


# ─────────────── 4. 上传：失败落 failed，不返回 completed ───────────────


class FakeDocRepo:
    def __init__(self):
        self.doc = SimpleNamespace(
            id=1,
            knowledge_base_id=1,
            filename="notes.txt",
            file_type="txt",
            file_size=10,
            status="pending",
            chunk_count=0,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )

    async def create(self, **kwargs):
        self.doc.status = kwargs.get("status", "pending")
        return self.doc

    async def update_status(
        self,
        doc_id,
        status,
        chunk_count=None,
        error_message=None,
        clear_error=False,
    ):
        self.doc.status = status
        if chunk_count is not None:
            self.doc.chunk_count = chunk_count
        if error_message is not None:
            self.doc.error_message = error_message
        if clear_error:
            self.doc.error_message = None
        return self.doc

    async def get_by_hash(self, knowledge_base_id, file_hash):
        """内容去重（B5）：默认认为没有重复"""
        return None


class FakeKbRepo:
    async def verify_owner(self, kb_id, user_id):
        return SimpleNamespace(id=kb_id)


class FakeChunkRepo:
    def __init__(self):
        self.rows: list = []

    async def bulk_create(self, chunks):
        self.rows = [
            SimpleNamespace(id=i + 1, content=c["content"], document_id=c["document_id"])
            for i, c in enumerate(chunks)
        ]
        return self.rows

    async def get_by_document(self, document_id):
        return self.rows


class FakeParser:
    # P0-8 后 parser.parse 是同步方法（阻塞 IO 由调用方放进线程池）
    def parse(self, path, file_type):
        return "一段足够长的正文内容，用于切片。"


class FakeSplitter:
    def split_text(self, text):
        return [
            {"content": "切片一", "index": 0, "metadata": {}},
            {"content": "切片二", "index": 1, "metadata": {}},
        ]


class FailingEmbedder:
    is_available = True

    async def embed_batch(self, texts):
        raise RuntimeError("401 Unauthorized")


class OkEmbedder:
    is_available = True

    async def embed_batch(self, texts):
        return [[0.1] * 1024 for _ in texts]


class RecordingVectorStore:
    def __init__(self, error: Exception | None = None):
        self.stored: list = []
        self.error = error

    async def store_embeddings(self, chunk_ids, embeddings):
        if self.error:
            raise self.error
        self.stored.append((chunk_ids, embeddings))


class FakeUpload:
    filename = "notes.txt"

    async def read(self):
        return b"hello world"


class FakeSession:
    """假会话：只实现上传路径会用到的三个方法"""

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def flush(self):
        return None


def make_document_service(**overrides) -> DocumentService:
    svc = DocumentService.__new__(DocumentService)
    svc.mysql_db = FakeSession()
    svc.pg_db = FakeSession()
    svc.doc_repo = FakeDocRepo()
    svc.kb_repo = FakeKbRepo()
    svc.chunk_repo = FakeChunkRepo()
    svc.parser = FakeParser()
    svc.splitter = FakeSplitter()
    svc.embedder = FailingEmbedder()
    svc.vector_store = RecordingVectorStore()

    async def fake_save_upload(file_obj, user_id, kb_id, filename):
        """B5 后落盘返回 (路径, 字节数, sha256)"""
        return Path("uploads/fake.txt"), 11, "deadbeef"

    svc._save_upload = fake_save_upload
    for key, value in overrides.items():
        setattr(svc, key, value)
    return svc


@pytest.mark.asyncio
async def test_upload_marks_failed_when_embedding_fails():
    """核心用例：向量生成失败时，文档必须是 failed，且原因出现在响应里"""
    metrics.reset()
    svc = make_document_service()
    result = await svc.upload(1, 1, FakeUpload())

    assert result.document.status == "failed"
    assert "向量生成失败" in result.message
    assert result.chunk_count == 2  # 切片已落库，保留以便后续补向量
    counters = metrics.snapshot()["counters"]
    assert counters.get("document_upload_total{status=failed}") == 1


@pytest.mark.asyncio
async def test_upload_marks_completed_when_embedding_succeeds():
    metrics.reset()
    svc = make_document_service(embedder=OkEmbedder())
    result = await svc.upload(1, 1, FakeUpload())

    assert result.document.status == "completed"
    assert result.chunk_count == 2
    counters = metrics.snapshot()["counters"]
    assert counters.get("document_upload_total{status=completed}") == 1


@pytest.mark.asyncio
async def test_upload_marks_failed_when_vector_store_write_fails():
    svc = make_document_service(
        embedder=OkEmbedder(),
        vector_store=RecordingVectorStore(error=RuntimeError("列类型不匹配")),
    )
    result = await svc.upload(1, 1, FakeUpload())

    assert result.document.status == "failed"
    assert "向量写入向量库失败" in result.message


@pytest.mark.asyncio
async def test_upload_rejects_when_vector_db_unavailable():
    """向量库不可用是前置条件，直接 503，不留下半成品记录"""
    metrics.reset()
    svc = make_document_service(pg_db=None, vector_store=None)
    with pytest.raises(AppException) as exc_info:
        await svc.upload(1, 1, FakeUpload())

    assert exc_info.value.http_status_code == 503
    assert "向量库不可用" in exc_info.value.message
    counters = metrics.snapshot()["counters"]
    assert counters.get("document_upload_total{status=unavailable}") == 1


# ─────────────── 5. 流式问答：失败一定变成 event: error ───────────────


class FakeSessionRepo:
    async def verify_owner(self, session_id, user_id):
        return SimpleNamespace(id=session_id)


def make_chat_service(rag_retriever=None) -> ChatService:
    svc = ChatService.__new__(ChatService)
    svc.session_repo = FakeSessionRepo()
    svc.message_repo = SimpleNamespace()
    svc._rag_retriever = rag_retriever
    svc._kb_repo = None
    svc._doc_repo = None
    svc.pg_db = None
    return svc


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_when_vector_db_missing():
    svc = make_chat_service(rag_retriever=None)
    events = []
    async for event in svc.send_message_stream(
        session_id=1, user_id=1, content="问点什么", knowledge_base_ids=[1]
    ):
        events.append(event)

    text = "".join(events)
    assert "event: error" in text, f"失败必须发出 error 事件，实际：{text!r}"
    assert "向量库未连接" in text
    assert '"done": true' in text, "出错后也要发结束事件，否则前端会一直转圈"


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_when_retrieval_fails():
    retriever = Retriever(
        FakeEmbedder(), FakeVectorStore(error=RuntimeError("connection refused"))
    )
    svc = make_chat_service(rag_retriever=retriever)
    svc._kb_repo = SimpleNamespace()
    svc._doc_repo = SimpleNamespace()

    async def verify_owner(kb_id, user_id):
        return SimpleNamespace(id=kb_id)

    async def get_by_knowledge_base(kb_id, skip, limit):
        return [SimpleNamespace(id=10)], 1

    svc._kb_repo.verify_owner = verify_owner
    svc._doc_repo.get_by_knowledge_base = get_by_knowledge_base

    events = []
    async for event in svc.send_message_stream(
        session_id=1, user_id=1, content="问点什么", knowledge_base_ids=[1]
    ):
        events.append(event)

    text = "".join(events)
    assert "event: error" in text
    assert "向量检索出错" in text


@pytest.mark.asyncio
async def test_plain_chat_without_kb_does_not_require_vector_db():
    """没选知识库 = 普通聊天，不应该因为向量库缺失而失败"""
    svc = make_chat_service(rag_retriever=None)
    # P2-10 起返回 (上下文, 引用列表)：没选库时两者都空
    assert await svc._retrieve_rag_context("你好", None, 1) == ("", [])
    assert await svc._retrieve_rag_context("你好", [], 1) == ("", [])
