"""
文档业务逻辑层 — 上传 → 解析 → 切片 → 存储

完整的文档处理流水线：
  上传 → 校验格式 → 保存到磁盘 → 解析文本 → 切片 → 存 PostgreSQL → 完成

涉及两个数据库：
  - MySQL：存 Document 元信息
  - PostgreSQL：存 DocumentChunk 切片
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import AppException
from app.rag.document_parser import DocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.text_splitter import TextSplitter
from app.rag.vector_store import VectorStore
from app.repositories.document_repo import DocumentChunkRepository, DocumentRepository
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository
from app.schemas.document import (
    DocumentChunkResponse,
    DocumentDetailResponse,
    DocumentResponse,
    DocumentUploadResponse,
)

logger = logging.getLogger(__name__)


class DocumentService:
    """文档业务"""

    def __init__(self, mysql_db, pg_db):
        """
        参数：
            mysql_db: MySQL 异步会话（业务数据）
            pg_db: PostgreSQL 异步会话（向量/切片数据）
        """
        self.mysql_db = mysql_db
        self.pg_db = pg_db
        self.doc_repo = DocumentRepository(mysql_db)
        self.kb_repo = KnowledgeBaseRepository(mysql_db)
        self.chunk_repo = DocumentChunkRepository(pg_db)
        self.parser = DocumentParser()
        self.splitter = TextSplitter(
            chunk_size=settings.VECTOR_CHUNK_SIZE,
            chunk_overlap=settings.VECTOR_CHUNK_OVERLAP,
        )
        # RAG 组件（可选）
        self.embedder = EmbeddingService()
        self.vector_store = VectorStore(pg_db) if pg_db else None

    async def upload(
        self,
        kb_id: int,
        user_id: int,
        file_obj,  # UploadFile
    ) -> DocumentUploadResponse:
        """
        上传文档 → 解析 → 切片 → 向量化 → 存储。

        失败语义（P0-1 的核心约定）：
          - 前置依赖缺失（向量库未连接）→ 抛 AppException(503)，不落任何数据
          - 文档记录已创建后的任何失败（解析为空 / 切片写库失败 / 向量生成失败）
            → 文档落库为 failed，并在响应里给出具体原因，**绝不返回 completed**

        为什么失败时返回 failed 而不是抛异常：
          "上传"这个动作成功了（文件已落盘、记录已建立），失败的是"处理"。
          返回 200 + failed + 原因，客户端才能把这条记录显示出来并提供重试；
          若直接抛异常，依赖注入会回滚整个事务，"失败过"这件事连同记录一起消失，
          用户和运维都看不见 —— 这正是修复前的问题。
        """
        # ① 向量库是硬依赖：没有它，切片无处存放，文档必然不可检索
        if self.pg_db is None or self.vector_store is None:
            metrics.incr("document_upload_total", status="unavailable")
            logger.error("文档上传被拒绝：向量库未连接")
            raise AppException(
                code=503,
                message="向量库不可用：请检查 PostgreSQL / pgvector 连接后再上传",
                http_status_code=503,
            )

        # ② 校验知识库归属
        kb = await self.kb_repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # ③ 校验文件格式（按客户端给的原名判断扩展名）
        raw_filename = file_obj.filename or ""
        file_type = self._get_file_type(raw_filename)
        self._validate_file_type(file_type)

        # ④ 文件名净化 + 流式落盘 + 路径包含校验（P0-8）
        #    `filename` 落库的是**净化后的 basename**：原始值可能带目录成分
        #    （`..\..\evil.txt`），既没有展示价值，也不该被原样回显到任何地方。
        safe_filename = self._sanitize_filename(raw_filename)
        saved_path, file_size, file_hash = await self._save_upload(
            file_obj, user_id, kb_id, safe_filename
        )

        # ④' 内容去重（P0-8 遗留）：同一知识库里内容相同的文件不再重复处理。
        #     比对 sha256 而不是文件名 —— 改名重传同样应该被拦。
        duplicate = await self.doc_repo.get_by_hash(kb_id, file_hash)
        if duplicate is not None:
            saved_path.unlink(missing_ok=True)  # 刚写的这份是多余的，删掉
            metrics.incr("document_upload_total", status="duplicate")
            logger.info(
                "文档内容重复，已拒绝上传",
                extra={"kb_id": kb_id, "duplicate_of": duplicate.id},
            )
            raise AppException(
                code=409,
                message=(
                    f"该文件内容已存在于本知识库（{duplicate.filename}，"
                    f"状态 {duplicate.status}），无需重复上传"
                ),
                http_status_code=409,
            )

        # ⑤ 建立文档记录（此后的失败都会写进这条记录，而不是只留在日志里）
        doc = await self.doc_repo.create(
            knowledge_base_id=kb_id,
            filename=safe_filename,
            file_type=file_type,
            file_size=file_size,
            file_path=str(saved_path),
            status="pending",
            file_hash=file_hash,
        )

        started = time.perf_counter()
        try:
            result = await self._process_document(doc, saved_path, file_type)
            # ⑥ 显式提交：FastAPI 的 yield 依赖要**等响应发出去之后**才 commit，
            #    客户端紧接着的"刷新列表"或"再传一次同一文件"会读到旧快照
            #    （实测：立即重复上传同一个文件，去重会失效）。
            await self._commit_uploaded()
            return result
        finally:
            metrics.observe_ms(
                "document_processing_latency",
                (time.perf_counter() - started) * 1000,
            )

    async def _commit_uploaded(self) -> None:
        """
        提交本次上传的事务（先 PG 后 MySQL）。

        顺序：先把切片/向量落库，再落文档状态。
        反过来的话，中途失败会出现"文档 completed 但没有向量"的假成功。
        """
        if self.pg_db is not None:
            await self.pg_db.commit()
        await self.mysql_db.commit()

    async def _process_document(
        self, doc, saved_path: Path, file_type: str
    ) -> DocumentUploadResponse:
        """
        解析 → 切片 → 写向量库 → 生成向量。

        每一步失败都转成 `status=failed` + 明确原因，不向上抛异常，
        这样请求结束时的提交才会把失败状态持久化下来。
        """
        # ─── 解析（阻塞 IO → 线程池，不占事件循环） ───
        try:
            text = await asyncio.to_thread(
                self.parser.parse, str(saved_path), file_type
            )
        except Exception as e:
            return await self._mark_failed(doc, f"文档解析失败：{e}", 0)

        if not text or not text.strip():
            return await self._mark_failed(doc, "文档解析结果为空，没有可索引的文本", 0)

        await self.doc_repo.update_status(doc.id, "processing")

        # ─── 切片 ───
        chunks_data = self.splitter.split_text(text)
        if not chunks_data:
            return await self._mark_failed(doc, "文本切片结果为空", 0)

        # ─── 写入 PostgreSQL ───
        try:
            await self.chunk_repo.bulk_create(
                [
                    {
                        "document_id": doc.id,
                        "chunk_index": chunk["index"],
                        "content": chunk["content"],
                        "extra_meta": chunk.get("metadata"),
                    }
                    for chunk in chunks_data
                ]
            )
        except Exception as e:
            await self._safe_pg_rollback()
            return await self._mark_failed(doc, f"切片写入向量库失败：{e}", 0)

        # ─── 生成向量 ───
        if not self.embedder.is_available:
            return await self._mark_failed(
                doc,
                "未配置 Embedding 服务（EMBEDDING_API_KEY 为空），该文档将检索不到",
                len(chunks_data),
            )

        try:
            created_chunks = await self.chunk_repo.get_by_document(doc.id)
            chunk_ids = [c.id for c in created_chunks]
            chunk_texts = [c.content for c in created_chunks]
        except Exception as e:
            await self._safe_pg_rollback()
            return await self._mark_failed(doc, f"读取切片失败：{e}", len(chunks_data))

        try:
            embeddings = await self.embedder.embed_batch(chunk_texts)
            if len(embeddings) != len(chunk_ids):
                raise RuntimeError(
                    f"向量数量与切片数量不一致：{len(embeddings)} vs {len(chunk_ids)}"
                )
        except Exception as e:
            # 外部 API 失败：切片已落库，保留它们以便后续补向量，只把文档标成 failed
            return await self._mark_failed(doc, f"向量生成失败：{e}", len(chunks_data))

        try:
            await self.vector_store.store_embeddings(chunk_ids, embeddings)
        except Exception as e:
            await self._safe_pg_rollback()
            return await self._mark_failed(doc, f"向量写入向量库失败：{e}", len(chunks_data))

        # ─── 完成 ───
        doc = await self.doc_repo.update_status(
            doc.id, "completed", len(chunks_data), clear_error=True
        )
        metrics.incr("document_upload_total", status="completed")
        logger.info("文档处理完成 doc_id=%s chunks=%s", doc.id, len(chunks_data))

        return DocumentUploadResponse(
            document=DocumentResponse.model_validate(doc),
            chunk_count=len(chunks_data),
            message=f"文档上传并处理完成，共 {len(chunks_data)} 个切片，已生成向量索引",
        )

    async def _mark_failed(
        self, doc, reason: str, chunk_count: int
    ) -> DocumentUploadResponse:
        """
        把文档标记为 failed 并返回带原因的响应。

        注意：这里**不抛异常**，让请求正常提交，失败状态才会留在数据库里。
        """
        logger.error(
            "文档处理失败 doc_id=%s filename=%s reason=%s",
            doc.id,
            getattr(doc, "filename", "?"),
            reason,
        )
        metrics.incr("document_upload_total", status="failed")
        doc = await self.doc_repo.update_status(
            doc.id, "failed", chunk_count, error_message=reason
        )
        return DocumentUploadResponse(
            document=DocumentResponse.model_validate(doc),
            chunk_count=chunk_count,
            message=f"文档已接收，但处理失败：{reason}",
        )

    async def _safe_pg_rollback(self) -> None:
        """把 PG 会话从失败事务中恢复；自身失败不抛，避免掩盖原始错误"""
        if self.pg_db is None:
            return
        try:
            await self.pg_db.rollback()
        except Exception as e:
            logger.warning("回滚 PostgreSQL 会话失败：%s", e)

    async def list_by_knowledge_base(
        self, kb_id: int, user_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[DocumentResponse], int]:
        """获取知识库下的文档列表"""
        kb = await self.kb_repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        skip = (page - 1) * page_size
        items, total = await self.doc_repo.get_by_knowledge_base(kb_id, skip, page_size)
        result = [DocumentResponse.model_validate(doc) for doc in items]
        return result, total

    async def get_detail(
        self, doc_id: int, user_id: int
    ) -> DocumentDetailResponse:
        """获取文档详情（含切片内容）"""
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            raise AppException(code=404, message="文档不存在", http_status_code=404)

        # 校验知识库归属（verify_owner 已隐式确认知识库存在）
        kb = await self.kb_repo.verify_owner(doc.knowledge_base_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # 获取切片（PG 不可用时返回空列表）
        chunks = []
        if self.pg_db is not None:
            # 尝试从缓存读取
            try:
                from app.core.cache import get_cached_document_chunks
                cached_chunks = await get_cached_document_chunks(doc_id)
                if cached_chunks is not None:
                    chunk_responses = [DocumentChunkResponse(**c) for c in cached_chunks]
                    doc_resp = DocumentDetailResponse.model_validate(doc)
                    doc_resp.chunks = chunk_responses
                    return doc_resp
            except ImportError:
                pass

            # 缓存未命中，从数据库查询
            chunks = await self.chunk_repo.get_by_document(doc_id)

        chunk_responses = [DocumentChunkResponse.model_validate(c) for c in chunks]

        # 写入缓存
        if chunks:
            try:
                from app.core.cache import cache_document_chunks
                chunks_data = [c.model_dump() for c in chunk_responses]
                await cache_document_chunks(doc_id, chunks_data)
            except ImportError:
                pass

        doc_resp = DocumentDetailResponse.model_validate(doc)
        doc_resp.chunks = chunk_responses
        return doc_resp

    async def delete(self, doc_id: int, user_id: int) -> None:
        """删除文档（同时删除切片和文件）"""
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            raise AppException(code=404, message="文档不存在", http_status_code=404)

        # 校验知识库归属
        kb = await self.kb_repo.verify_owner(doc.knowledge_base_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # 删除磁盘文件
        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()

        # 清除缓存
        try:
            from app.core.cache import invalidate_document_cache
            await invalidate_document_cache(doc_id)
        except ImportError:
            pass

        # 删除 PostgreSQL 中的切片（如果 PG 可用）
        if self.pg_db is not None:
            await self.chunk_repo.delete_by_document(doc_id)

        # 删除 MySQL 中的文档记录
        await self.doc_repo.delete(doc_id)

    # ─── 私有辅助方法 ───

    def _get_file_type(self, filename: str) -> str:
        """从文件名中提取扩展名作为文件类型"""
        if "." not in filename:
            raise AppException(code=400, message="文件名缺少扩展名", http_status_code=400)
        ext = filename.rsplit(".", 1)[1].lower()
        return ext

    def _validate_file_type(self, file_type: str) -> None:
        """校验文件类型是否在允许列表中"""
        if file_type not in settings.ALLOWED_EXTENSIONS:
            raise AppException(
                code=400,
                message=f"不支持的文件类型：.{file_type}。支持格式：{', '.join(settings.ALLOWED_EXTENSIONS)}",
                http_status_code=400,
            )

    def _validate_file_size(self, file_size: int) -> None:
        """校验文件大小是否超过限制"""
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise AppException(
                code=413,
                message=f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE_MB}MB）",
                http_status_code=413,
            )

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        只保留"文件名本身"，且只允许安全字符。

        为什么不能只用 `Path(filename).name`：
          Windows 下反斜杠也是路径分隔符，`..\\..\\evil.txt` 在 Linux 语义下会被
          当成一个普通文件名整段保留，两边行为不一致。这里统一把 `\\` 和 `/`
          都当分隔符切掉目录部分，再走白名单过滤，最后兜一个默认名。
        """
        base = str(filename or "").replace("\\", "/").split("/")[-1]
        # \w 在 Python 里是 Unicode 语义，中文会被保留；其余一律替换为下划线
        cleaned = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
        if not cleaned:
            cleaned = "upload"

        if len(cleaned) > 120:
            stem, dot, ext = cleaned.rpartition(".")
            cleaned = (stem[:110] + dot + ext[:9]) if dot else cleaned[:120]
        return cleaned

    async def _save_upload(
        self, file_obj, user_id: int, kb_id: int, filename: str
    ) -> tuple[Path, int, str]:
        """
        把上传文件**流式**写入磁盘，返回 (落盘路径, 字节数, sha256)。

        P0-8 要求的三件事在这里一次做对：
          1. 文件名净化 + `resolve()` 后仍在上传目录内 → 杜绝 `..\\..\\evil.txt` 穿越
          2. 边写边计数，超限立刻中断并删掉半截文件 → 不再把整文件读进内存
          3. 同步 IO 放到线程里跑 → 不阻塞事件循环
        """
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

        # Starlette 会带 Content-Length，能提前拒绝就不必写盘
        declared = getattr(file_obj, "size", None)
        if declared is not None and declared > max_bytes:
            self._validate_file_size(int(declared))

        upload_dir = Path(settings.UPLOAD_DIR) / str(user_id) / str(kb_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(filename)
        dest = upload_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"

        # 双保险：即使净化有漏，也不允许落盘路径逃出本次上传目录
        resolved_dir = upload_dir.resolve()
        resolved_dest = dest.resolve()
        if not resolved_dest.is_relative_to(resolved_dir):
            logger.error("拒绝可疑的上传路径：%r → %s", filename, resolved_dest)
            raise AppException(
                code=400, message="非法的文件名", http_status_code=400
            )

        size, digest = await asyncio.to_thread(
            self._stream_to_disk, file_obj, resolved_dest, max_bytes
        )
        return dest, size, digest

    @staticmethod
    def _stream_to_disk(file_obj, dest: Path, max_bytes: int) -> tuple[int, str]:
        """
        同步实现（在线程里执行）：分块拷贝 + 超限即删 + 顺带算 sha256。

        为什么在这里算哈希：文件已经要流式过一遍，顺手算比再读一遍磁盘便宜。
        """
        inner = getattr(file_obj, "file", None)
        if inner is None:  # pragma: no cover - UploadFile 一定有 .file
            raise AppException(
                code=400, message="无法读取上传内容", http_status_code=400
            )

        total = 0
        digest = hashlib.sha256()
        inner.seek(0)
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = inner.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                    if total > max_bytes:
                        raise AppException(
                            code=413,
                            message=(
                                "文件大小超过限制"
                                f"（最大 {max_bytes // (1024 * 1024)}MB）"
                            ),
                            http_status_code=413,
                        )
                    out.write(chunk)
        except Exception:
            # 不留半截文件：否则磁盘上会出现"写了一半"的孤儿
            dest.unlink(missing_ok=True)
            raise

        return total, digest.hexdigest()
