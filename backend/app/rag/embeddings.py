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
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

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
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
        else:
            self.client = None
            logger.warning("EmbeddingService: 未配置 API Key，embedding 功能不可用")

    @property
    def is_available(self) -> bool:
        """Embedding 服务是否可用"""
        return self._available

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

        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding 调用失败: {e}")
            raise RuntimeError(f"Embedding 生成失败: {e}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量将文本转为向量（推荐方式，API 支持批量处理以提高效率）。

        参数：
            texts: 要嵌入的文本列表

        返回：
            向量数组列表，顺序与输入一致
        """
        if not self._available:
            raise RuntimeError("Embedding 服务未配置，无法生成向量")

        if not texts:
            return []

        # 过滤空文本
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return [[0.0] * self.dimension for _ in texts]

        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=valid_texts,
            )
            # 返回顺序与输入一致
            embeddings = [data.embedding for data in response.data]

            # 如果有空文本被过滤，补回零向量以保持索引对应
            if len(embeddings) < len(texts):
                result = []
                idx = 0
                for t in texts:
                    if t and t.strip():
                        result.append(embeddings[idx])
                        idx += 1
                    else:
                        result.append([0.0] * self.dimension)
                return result

            return embeddings
        except Exception as e:
            logger.error(f"批量 Embedding 调用失败: {e}")
            raise RuntimeError(f"批量 Embedding 生成失败: {e}")
