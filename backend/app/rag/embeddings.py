"""
Embedding 服务 — 文本转向量嵌入

将文本转为向量表示（embedding），用于 RAG 相似度检索。

支持两种模式：
  1. OpenAI 兼容 API 嵌入（如 OpenAI / 通义千问 / DeepSeek 的 embedding 接口）
  2. 降级模式：如果未配置 Embedding API，则跳过 embedding 生成（切片仍可保存，但无法做向量检索）

用法：
    embed_service = EmbeddingService()
    vector = await embed_service.embed("要转换的文本")
    vectors = await embed_service.embed_batch(["文本1", "文本2"])
"""

import logging
import time
from typing import Any

from openai import AsyncOpenAI

from app.core import metrics
from app.core.config import settings
from app.core.retry import call_with_retry

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Embedding 服务

    通过 OpenAI 兼容的 API 将文本转为向量。
    支持批量嵌入提高效率。
    """

    def __init__(self):
        # 优先使用专用 Embedding 配置，若未设置则降级使用 LLM 的 API 配置
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self.api_base = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
        self.model = settings.EMBEDDING_MODEL_NAME
        self.dimension = settings.EMBEDDING_DIMENSION  # 向量维度，用于 pgvector 声明

        # 可用性：必须有 API Key 才能工作
        self._available = bool(self.api_key)

        if self._available:
            # 超时 + 重试同 LLMService：SDK 自带重试关掉，统一走 app.core.retry（P1-14）
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
                max_retries=0,
            )
        else:
            self.client = None
            logger.warning("EmbeddingService: 未配置 API Key，embedding 功能不可用")

    @property
    def is_available(self) -> bool:
        """Embedding 服务是否可用"""
        return self._available

    def _check_dimension(self, vector: Any, source: str) -> None:
        """
        校验向量维度与配置一致。

        为什么必须在写库前校验？
          pgvector 的 vector(n) 维度在**建表时固定**，维度不符时数据库会直接拒绝，
          但历史上这个异常会被静默吞掉，文档仍被标为 completed —— 也就是"看起来成功、
          实际没有向量"。在这里提前拦截，可以得到一条人能看懂的错误。
        """
        if not isinstance(vector, (list, tuple)):
            raise RuntimeError(f"Embedding 返回值不是向量（{source}）: {type(vector).__name__}")

        actual = len(vector)
        if actual != self.dimension:
            raise RuntimeError(
                f"Embedding 维度不匹配（{source}）：模型 {self.model} 返回 {actual} 维，"
                f"但 EMBEDDING_DIMENSION={self.dimension}。"
                f"请统一 模型维度 / EMBEDDING_DIMENSION / document_chunks.embedding 列维度 三者。"
            )

    async def embed(self, text: str) -> list[float]:
        """
        将单段文本转为向量。

        参数：
            text: 要嵌入的文本

        返回：
            向量数组（维度由 EMBEDDING_DIMENSION 决定）

        异常：
            RuntimeError: Embedding 服务未配置时调用
        """
        if not self._available:
            raise RuntimeError("Embedding 服务未配置，无法生成向量")

        if not text or not text.strip():
            return [0.0] * self.dimension

        started = time.perf_counter()
        try:
            response = await call_with_retry(
                lambda: self.client.embeddings.create(
                    model=self.model,
                    input=text,
                ),
                operation="embedding",
                max_retries=settings.EMBEDDING_MAX_RETRIES,
            )
            vector = response.data[0].embedding
            self._check_dimension(vector, source="embed")
            metrics.incr("embedding_total", status="ok")
            return vector
        except Exception as e:
            metrics.incr("embedding_total", status="fail")
            metrics.incr("embedding_fail_total")
            logger.error(f"Embedding 调用失败: {e}")
            raise RuntimeError(f"Embedding 生成失败: {e}")
        finally:
            metrics.observe_ms(
                "embedding_latency", (time.perf_counter() - started) * 1000
            )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量将文本转为向量。

        分批策略（P1-14）：
          一次把几百个切片塞进一个请求会顶到上游的批大小/超时限制，
          失败时还会丢掉整篇文档的向量。这里按 `EMBEDDING_BATCH_SIZE`（默认 32）
          分批，每批独立重试：一批失败只影响这一批，且日志能定位到是第几批。

        参数：
            texts: 要嵌入的文本列表

        返回：
            向量数组列表，顺序与输入**严格一致**（空文本用零向量占位）
        """
        if not self._available:
            raise RuntimeError("Embedding 服务未配置，无法生成向量")

        if not texts:
            return []

        # 记录非空文本的位置，最后按原位置回填，保证顺序不变
        positions = [i for i, t in enumerate(texts) if t and t.strip()]
        if not positions:
            return [[0.0] * self.dimension for _ in texts]
        valid_texts = [texts[i] for i in positions]

        batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE))
        total_batches = (len(valid_texts) + batch_size - 1) // batch_size

        started = time.perf_counter()
        embeddings: list[list[float]] = []
        try:
            for index in range(total_batches):
                batch = valid_texts[index * batch_size : (index + 1) * batch_size]
                response = await call_with_retry(
                    lambda batch=batch: self.client.embeddings.create(
                        model=self.model,
                        input=batch,
                    ),
                    operation="embedding_batch",
                    max_retries=settings.EMBEDDING_MAX_RETRIES,
                )

                vectors = [data.embedding for data in response.data]
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"第 {index + 1}/{total_batches} 批数量不匹配："
                        f"请求 {len(batch)} 条，返回 {len(vectors)} 条"
                    )
                for vec in vectors:
                    self._check_dimension(vec, source="embed_batch")

                embeddings.extend(vectors)

            # 按原位置回填（空文本补零向量）
            result = [[0.0] * self.dimension for _ in texts]
            for position, vector in zip(positions, embeddings, strict=True):
                result[position] = vector

            metrics.incr("embedding_total", status="ok")
            metrics.incr("embedding_batches_total", value=total_batches)
            logger.info(
                "Embedding 完成：%s 条 / %s 批（batch_size=%s）",
                len(valid_texts),
                total_batches,
                batch_size,
            )
            return result
        except Exception as e:
            metrics.incr("embedding_total", status="fail")
            metrics.incr("embedding_fail_total")
            logger.error(f"批量 Embedding 调用失败: {e}")
            raise RuntimeError(f"批量 Embedding 生成失败: {e}")
        finally:
            metrics.observe_ms(
                "embedding_latency", (time.perf_counter() - started) * 1000
            )
