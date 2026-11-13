"""
Retriever — RAG 检索编排

完整的检索流程：
  用户问题 → 生成 embedding → 向量相似度搜索 → 格式化上下文 → 注入 LLM

职责：
  1. 接收用户问题 + 知识库 ID
  2. 生成问题 embedding
  3. 在指定知识库的文档切片中做相似度搜索
  4. 将检索结果格式化为 LLM 可用的上下文文本

用法：
    retriever = Retriever(embedding_service, vector_store)
    context = await retriever.retrieve("什么是Python", kb_ids=[1])
    # → "以下是与问题相关的文档内容：\n\n[切片1内容]\n---\n[切片2内容]..."
"""

import logging
import time
from typing import Any

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import RetrievalError
from app.rag.embeddings import EmbeddingService
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """
    RAG 检索器 — 编排检索流程

    包含三步骤：
      1. embed: 将用户问题转为向量
      2. search: 在向量库中做相似度搜索
      3. format: 将结果格式化为 LLM 上下文
    """

    def __init__(
        self,
        embed_service: EmbeddingService,
        vector_store: VectorStore,
    ):
        """
        参数：
            embed_service: Embedding 服务（文本→向量）
            vector_store: 向量存储（相似度搜索）
        """
        self.embedder = embed_service
        self.vector_store = vector_store

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
    ) -> str:
        """
        检索相关文档片段并格式化为上下文。

        参数：
            query: 用户问题
            top_k: 返回最多 K 个切片（默认从配置读取）
            document_ids: 可选，限定搜索的文档范围

        返回：
            格式化后的上下文文本；**检索成功但没有命中时返回空字符串**

        异常：
            RetrievalError: 检索链路不可用（Embedding 未配置 / 调用失败 / 向量库报错）。
                            调用方必须处理，不允许把它当成"没找到"继续回答。
        """
        result = await self._search(query, top_k=top_k, document_ids=document_ids)
        if not result:
            return ""
        return self._format_context(result)

    async def _search(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        检索的共用内核：embed → 向量搜索 → 返回原始结果列表（可能为空）。

        把"失败"和"空结果"分开表达：失败抛 RetrievalError，空结果返回 []。
        """
        if not self.embedder.is_available:
            metrics.incr("rag_retrieval_total", status="unavailable")
            logger.error("RAG 检索不可用：Embedding 服务未配置（EMBEDDING_API_KEY 为空）")
            raise RetrievalError(
                "知识库检索不可用：未配置 Embedding 服务",
                detail="EmbeddingService.is_available=False",
            )

        top_k = top_k or settings.VECTOR_TOP_K
        started = time.perf_counter()
        try:
            try:
                query_embedding = await self.embedder.embed(query)
            except Exception as e:
                metrics.incr("rag_retrieval_total", status="error")
                logger.error("RAG 检索失败：查询向量生成失败: %s", e)
                raise RetrievalError(
                    "知识库检索失败：查询向量生成失败", detail=str(e)
                ) from e

            if not query_embedding:
                metrics.incr("rag_retrieval_total", status="empty")
                return []

            try:
                results = await self.vector_store.similarity_search(
                    query_embedding=query_embedding,
                    top_k=top_k,
                    document_ids=document_ids,
                )
            except Exception as e:
                metrics.incr("rag_retrieval_total", status="error")
                logger.error("RAG 检索失败：向量检索出错: %s", e)
                raise RetrievalError(
                    "知识库检索失败：向量检索出错", detail=str(e)
                ) from e

            if not results:
                metrics.incr("rag_retrieval_total", status="empty")
                logger.info("RAG 检索未找到相关内容（top_k=%s）", top_k)
                return []

            metrics.incr("rag_retrieval_total", status="ok")
            return results
        finally:
            metrics.observe_ms(
                "rag_retrieval_latency", (time.perf_counter() - started) * 1000
            )

    async def retrieve_with_details(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        检索并返回详细结果（含元数据，按阈值过滤）。

        返回：
            {
                "has_results": bool,
                "context": "格式化后的文本",
                "chunks": [{"content": "...", "similarity": 0.92, ...}, ...],
                "chunk_count": int,
            }

        异常：
            RetrievalError: 同 retrieve()，链路不可用时抛出而不是伪装成"无结果"。
        """
        results = await self._search(query, top_k=top_k, document_ids=document_ids)
        if not results:
            return {
                "has_results": False,
                "context": "",
                "chunks": [],
                "chunk_count": 0,
            }

        # 过滤低相似度结果
        threshold = settings.VECTOR_SIMILARITY_THRESHOLD
        filtered = [r for r in results if r["similarity"] >= threshold]

        return {
            "has_results": len(filtered) > 0,
            "context": self._format_context(filtered),
            "chunks": filtered,
            "chunk_count": len(filtered),
        }

    def _format_context(self, chunks: list[dict[str, Any]]) -> str:
        """
        将检索结果格式化为 LLM 上下文。

        格式：
            以下是与用户问题相关的文档内容：

            [文档片段 1]
            ...

            ---

            [文档片段 2]
            ...
        """
        if not chunks:
            return ""

        parts = ["以下是与用户问题相关的文档内容：\n"]
        for i, chunk in enumerate(chunks, 1):
            similarity = chunk.get("similarity", 0)
            sim_str = f"（相关度: {similarity:.2f}）" if similarity else ""
            parts.append(f"[文档片段 {i}] {sim_str}")
            parts.append(chunk["content"].strip())
            parts.append("")

        return "\n---\n".join(parts)
