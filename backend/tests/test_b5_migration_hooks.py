"""
B5 回归测试 — 迁移落地的三项能力

覆盖：
  - 内容去重（P0-8 遗留）：同库同 sha256 直接 409，且不留下多余文件
  - 失败原因持久化（P0-1 遗留）：failed 时写 error_message，成功时清空
  - HNSW 查询参数（P1-1）：检索前发 `SET LOCAL hnsw.ef_search`，否则索引召回不可控

不依赖数据库 / 网络。
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import metrics
from app.core.exceptions import AppException
from app.repositories.document_repo import DocumentChunkRepository
from app.services.document_service import DocumentService

# ─────────────────── 通用 Fake ───────────────────


class FakeDocRepo:
    def __init__(self, duplicate=None):
        self.duplicate = duplicate
        self.calls: list[dict] = []
        self.doc = SimpleNamespace(
            id=1,
            knowledge_base_id=1,
            filename="notes.txt",
            file_type="txt",
            file_size=10,
            status="pending",
            chunk_count=0,
            error_message=None,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )

    async def create(self, **kwargs):
        self.calls.append({"op": "create", **kwargs})
        self.doc.file_hash = kwargs.get("file_hash")
        self.doc.status = kwargs.get("status", "pending")
        return self.doc

    async def update_status(
        self, doc_id, status, chunk_count=None, error_message=None, clear_error=False
    ):
        self.calls.append(
            {
                "op": "update_status",
                "status": status,
                "error_message": error_message,
                "clear_error": clear_error,
            }
        )
        self.doc.status = status
        if chunk_count is not None:
            self.doc.chunk_count = chunk_count
        if error_message is not None:
            self.doc.error_message = error_message
        if clear_error:
            self.doc.error_message = None
        return self.doc

    async def get_by_hash(self, knowledge_base_id, file_hash):
        self.calls.append({"op": "get_by_hash", "hash": file_hash})
        return self.duplicate


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
    def parse(self, path, file_type):
        return "一段足够长的正文内容，用于切片。"


class FakeSplitter:
    def split_text(self, text):
        return [
            {"content": "切片一", "index": 0, "metadata": {}},
            {"content": "切片二", "index": 1, "metadata": {}},
        ]


class OkEmbedder:
    is_available = True

    async def embed_batch(self, texts):
        return [[0.1] * 1024 for _ in texts]


class FailingEmbedder:
    is_available = True

    async def embed_batch(self, texts):
        raise RuntimeError("401 Unauthorized")


class FakeVectorStore:
    def __init__(self, error=None):
        self.error = error
        self.stored = []

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


def make_service(tmp_path: Path, **overrides) -> DocumentService:
    svc = DocumentService.__new__(DocumentService)
    svc.mysql_db = FakeSession()
    svc.pg_db = FakeSession()
    svc.doc_repo = overrides.pop("doc_repo", FakeDocRepo())
    svc.kb_repo = FakeKbRepo()
    svc.chunk_repo = FakeChunkRepo()
    svc.parser = FakeParser()
    svc.splitter = FakeSplitter()
    svc.embedder = overrides.pop("embedder", OkEmbedder())
    svc.vector_store = overrides.pop("vector_store", FakeVectorStore())

    async def fake_save_upload(file_obj, user_id, kb_id, filename):
        dest = tmp_path / "saved.txt"
        dest.write_bytes(b"hello world")
        return dest, 11, "sha256-abc"

    svc._save_upload = fake_save_upload
    for key, value in overrides.items():
        setattr(svc, key, value)
    return svc


# ─────────────────── 内容去重 ───────────────────


@pytest.mark.asyncio
async def test_upload_rejects_duplicate_content(tmp_path):
    existing = SimpleNamespace(id=99, filename="old.txt", status="completed")
    repo = FakeDocRepo(duplicate=existing)
    svc = make_service(tmp_path, doc_repo=repo)

    with pytest.raises(AppException) as exc_info:
        await svc.upload(1, 1, FakeUpload())

    assert exc_info.value.http_status_code == 409
    assert "old.txt" in exc_info.value.message
    # 刚写的那份文件必须删掉，不能留孤儿
    assert not (tmp_path / "saved.txt").exists()
    # 重复时不应该建文档记录
    assert not [c for c in repo.calls if c["op"] == "create"]


@pytest.mark.asyncio
async def test_upload_records_file_hash(tmp_path):
    repo = FakeDocRepo()
    svc = make_service(tmp_path, doc_repo=repo)

    await svc.upload(1, 1, FakeUpload())

    created = next(c for c in repo.calls if c["op"] == "create")
    assert created["file_hash"] == "sha256-abc"


# ─────────────────── 失败原因持久化 ───────────────────


@pytest.mark.asyncio
async def test_failed_upload_persists_error_message(tmp_path):
    repo = FakeDocRepo()
    svc = make_service(tmp_path, doc_repo=repo, embedder=FailingEmbedder())

    result = await svc.upload(1, 1, FakeUpload())

    assert result.document.status == "failed"
    assert "向量生成失败" in result.message
    failed_call = next(c for c in repo.calls if c.get("status") == "failed")
    assert failed_call["error_message"], "失败原因必须落库，而不是只写日志"
    assert "向量生成失败" in failed_call["error_message"]
    # 响应里也要带上原因，前端可直接展示
    assert result.document.error_message


@pytest.mark.asyncio
async def test_successful_upload_clears_previous_error(tmp_path):
    repo = FakeDocRepo()
    svc = make_service(tmp_path, doc_repo=repo)

    result = await svc.upload(1, 1, FakeUpload())

    assert result.document.status == "completed"
    completed_call = next(c for c in repo.calls if c.get("status") == "completed")
    assert completed_call["clear_error"] is True


# ─────────────────── HNSW 查询参数 ───────────────────


class RecordingSession:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return SimpleNamespace(all=lambda: [], rowcount=0)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_similarity_search_sets_hnsw_ef_search():
    session = RecordingSession()
    repo = DocumentChunkRepository(session)

    await repo.similarity_search([0.1] * 1024, top_k=5)

    assert any("hnsw.ef_search" in s for s in session.statements), session.statements
    # 参数必须是字面量整数（SET 不支持绑定参数）
    ef_stmt = next(s for s in session.statements if "hnsw.ef_search" in s)
    assert ef_stmt.split("=")[-1].strip().isdigit()
    metrics.reset()
