"""
文档业务逻辑层 — 上传 → 解析 → 切片 → 存储

完整的文档处理流水线：
  上传 → 校验格式 → 保存到磁盘 → 解析文本 → 切片 → 存 PostgreSQL → 完成

涉及两个数据库：
  - MySQL：存 Document 元信息
  - PostgreSQL：存 DocumentChunk 切片
"""

import logging
import os
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppException
from app.rag.document_parser import DocumentParser
from app.rag.text_splitter import TextSplitter
from app.rag.embeddings import EmbeddingService
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
        上传文档 → 解析 → 切片 → 存储。

        完整流程：
          ① 校验知识库归属
          ② 校验文件格式和大小
          ③ 保存文件到磁盘
          ④ 创建 Document 记录（MySQL，status=pending）
          ⑤ 解析文档内容
          ⑥ 更新状态为 processing
          ⑦ 切片并存入 PostgreSQL
          ⑧ 更新状态为 completed（含切片数量）
          ⑨ 返回上传结果
        """
        # 校验知识库归属
        kb = await self.kb_repo.verify_owner(kb_id, user_id)
        if not kb:
            raise AppException(code=404, message="知识库不存在", http_status_code=404)

        # 校验文件格式和大小
        filename = file_obj.filename
        file_type = self._get_file_type(filename)
        self._validate_file_type(file_type)

        # 读取文件内容
        content = await file_obj.read()
        file_size = len(content)
        self._validate_file_size(file_size)

        # 保存文件到磁盘
        saved_path = await self._save_file(content, user_id, kb_id, filename)

        try:
            # 创建 Document 记录
            doc = await self.doc_repo.create(
                knowledge_base_id=kb_id,
                filename=filename,
                file_type=file_type,
                file_size=file_size,
                file_path=str(saved_path),
                status="pending",
            )

            # 解析文档内容
            text = await self.parser.parse(str(saved_path), file_type)

            # 更新状态为 processing
            await self.doc_repo.update_status(doc.id, "processing")

            # 切片
            chunks_data = self.splitter.split_text(text)
            chunk_count = len(chunks_data)

            # 存入 PostgreSQL（如果可用）
            if self.pg_db is not None and chunk_count > 0:
                chunk_objs = []
                for chunk in chunks_data:
                    chunk_objs.append(
                        {
                            "document_id": doc.id,
                            "chunk_index": chunk["index"],
                            "content": chunk["content"],
                            "extra_meta": chunk.get("metadata"),
                        }
                    )
                await self.chunk_repo.bulk_create(chunk_objs)
                saved_chunks = chunk_count
            else:
                saved_chunks = 0
                if self.pg_db is None:
                    logger.warning(f"PostgreSQL 不可用，文档 #{doc.id} 的切片未持久化")

            # ⑧+ 生成向量嵌入（如果 Embedding 服务可用）
            has_embedding = False
            if self.pg_db is not None and chunk_count > 0 and self.embedder.is_available:
                try:
                    # 从 DB 中获取刚创建的切片（bulk_create 返回的对象包含 id）
                    created_chunks = await self.chunk_repo.get_by_document(doc.id)
                    chunk_ids = [c.id for c in created_chunks]
                    chunk_texts = [c.content for c in created_chunks]

                    if chunk_texts:
                        embeddings = await self.embedder.embed_batch(chunk_texts)
                        await self.vector_store.store_embeddings(chunk_ids, embeddings)
                        has_embedding = True
                        logger.info(f"文档 #{doc.id} 的 {len(embeddings)} 个切片已生成向量")
                except Exception as e:
                    logger.warning(f"文档 #{doc.id} 向量生成失败（跳过）: {e}")
            elif self.embedder.is_available and chunk_count > 0:
                logger.info(f"文档 #{doc.id} 切片已保存但未生成向量（PG 不可用）")

            # 更新状态为 completed
            doc = await self.doc_repo.update_status(doc.id, "completed", saved_chunks)

        except AppException:
            # 如果解析阶段就出错了，更新状态为 failed 后重新抛出
            if "doc" in locals():
                await self.doc_repo.update_status(doc.id, "failed")
            raise
        except Exception as e:
            # 未知错误 — 更新状态为 failed
            if "doc" in locals():
                await self.doc_repo.update_status(doc.id, "failed")
            raise AppException(
                code=500,
                message=f"文档处理失败：{str(e)}",
                http_status_code=500,
            )

        # 构建提示信息
        msg_parts = [f"文档上传并处理完成，共生成 {chunk_count} 个切片"]
        if not saved_chunks:
            msg_parts.append("切片未持久化：PostgreSQL 不可用")
        elif has_embedding:
            msg_parts.append("已生成向量嵌入")
        else:
            msg_parts.append("未生成向量嵌入：Embedding API 未配置或不可用")

        return DocumentUploadResponse(
            document=DocumentResponse.model_validate(doc),
            chunk_count=saved_chunks or chunk_count,
            message="（" + "，".join(msg_parts) + "）",
        )

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
                code=400,
                message=f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE_MB}MB）",
                http_status_code=400,
            )

    async def _save_file(
        self, content: bytes, user_id: int, kb_id: int, filename: str
    ) -> Path:
        """
        保存文件到磁盘。

        目录结构：uploads/{user_id}/{kb_id}/{uuid}_{filename}
        使用 UUID 前缀防止同名文件覆盖。
        """
        # 构造目录路径
        upload_dir = Path(settings.UPLOAD_DIR) / str(user_id) / str(kb_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名
        unique_name = f"{uuid.uuid4().hex[:12]}_{filename}"
        file_path = upload_dir / unique_name

        # 写入文件
        with open(file_path, "wb") as f:
            f.write(content)

        return file_path
