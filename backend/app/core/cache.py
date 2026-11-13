"""
缓存层 — 基于 Redis 的多级缓存工具

提供三种缓存能力：
  1. LLM 响应缓存：相同问题命中缓存直接返回，节省 API 费用
  2. 文档切片缓存：频繁读取的文档切片缓存到 Redis
  3. 通用缓存装饰器：@cached 一行代码给任意函数加缓存

使用方式：
    # 方式 1：直接调用缓存函数
    from app.core.cache import cache_llm_response, get_cached_llm_response

    cached = await get_cached_llm_response(messages, model)
    if cached:
        return cached
    response = await llm.chat(messages)
    await cache_llm_response(messages, model, response)

    # 方式 2：使用装饰器（对 LLM 调用自动加缓存）
    @cached(expire=300, key_prefix="llm:")
    async def call_llm(messages): ...

缓存键设计：
  所有缓存键以 app: 为前缀，避免与其他应用冲突
  app:llm:<model_hash>:<messages_hash>  → LLM 响应
  app:doc:<document_id>:chunks           → 文档切片
  app:session:<session_id>               → 会话信息

降级策略：
  Redis 不可用时，所有缓存操作自动跳过，业务逻辑不受影响。
"""

import hashlib
import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from app.core.redis_client import redis_manager

logger = logging.getLogger(__name__)


# ─── 工具函数：生成缓存键 ───


def _hash_data(data: Any) -> str:
    """将任意数据转为 MD5 哈希，用作缓存键的一部分"""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _llm_cache_key(messages: list[dict], model: str) -> str:
    """生成 LLM 响应的缓存键（基于消息内容和模型名）"""
    msg_hash = _hash_data(messages)
    return f"app:llm:{model}:{msg_hash}"


def _doc_chunks_key(document_id: int) -> str:
    """生成文档切片缓存键"""
    return f"app:doc:{document_id}:chunks"


def _session_cache_key(session_id: int) -> str:
    """生成会话缓存键"""
    return f"app:session:{session_id}"


# ─── LLM 响应缓存 ───


async def get_cached_llm_response(
    messages: list[dict], model: str = ""
) -> str | None:
    """
    获取缓存的 LLM 响应。

    参数：
        messages: LLM 调用的消息列表
        model: 模型名称

    返回：
        如果命中缓存返回缓存的响应文本，否则返回 None
    """
    if not redis_manager.is_available:
        return None

    key = _llm_cache_key(messages, model)
    cached = await redis_manager.get(key)
    if cached is not None:
        logger.info(f"LLM 响应缓存命中 (key={key[:50]}...)")
    return cached


async def cache_llm_response(
    messages: list[dict], model: str, response: str, expire: int = 3600
) -> bool:
    """
    缓存 LLM 响应。

    参数：
        messages: LLM 调用的消息列表
        model: 模型名称
        response: LLM 的响应文本
        expire: 过期时间（秒），默认 1 小时

    返回：
        是否成功缓存
    """
    key = _llm_cache_key(messages, model)
    return await redis_manager.set(key, response, expire=expire)


async def invalidate_llm_cache(messages: list[dict], model: str = "") -> bool:
    """清除特定的 LLM 缓存"""
    key = _llm_cache_key(messages, model)
    return await redis_manager.delete(key)


# ─── 文档切片缓存 ───


async def get_cached_document_chunks(document_id: int) -> list[dict] | None:
    """获取缓存的文档切片列表"""
    if not redis_manager.is_available:
        return None

    key = _doc_chunks_key(document_id)
    cached = await redis_manager.get(key)
    if cached:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


async def cache_document_chunks(
    document_id: int, chunks: list[dict], expire: int = 1800
) -> bool:
    """
    缓存文档切片列表。

    参数：
        document_id: 文档 ID
        chunks: 切片列表
        expire: 过期时间（秒），默认 30 分钟
    """
    key = _doc_chunks_key(document_id)
    data = json.dumps(chunks, ensure_ascii=False, default=str)
    return await redis_manager.set(key, data, expire=expire)


async def invalidate_document_cache(document_id: int) -> bool:
    """文档变更时清除缓存"""
    return await redis_manager.delete(_doc_chunks_key(document_id))


# ─── 通用缓存装饰器 ───


def cached(expire: int = 300, key_prefix: str = "cache:"):
    """
    通用缓存装饰器。

    自动缓存函数的返回值，下次相同参数调用时直接返回缓存。

    使用方式：
        @cached(expire=600, key_prefix="search:")
        async def search_documents(query: str, top_k: int = 5):
            ...

    注意：
        函数的参数必须可 JSON 序列化。
        只适用于纯函数（相同输入 → 相同输出）。
        不适合有副作用的函数（如写数据库、调 LLM 每次可能不同）。

    参数：
        expire: 缓存过期时间（秒）
        key_prefix: 缓存键前缀，用于区分不同功能
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if not redis_manager.is_available:
                return await func(*args, **kwargs)

            # 生成缓存键
            key_data = {
                "func": f"{func.__module__}.{func.__qualname__}",
                "args": args,
                "kwargs": kwargs,
            }
            cache_key = f"{key_prefix}{_hash_data(key_data)}"

            # 尝试获取缓存
            cached_value = await redis_manager.get(cache_key)
            if cached_value is not None:
                try:
                    return json.loads(cached_value)
                except (json.JSONDecodeError, TypeError):
                    pass

            # 执行原函数
            result = await func(*args, **kwargs)

            # 缓存结果
            try:
                await redis_manager.set(
                    cache_key,
                    json.dumps(result, ensure_ascii=False, default=str),
                    expire=expire,
                )
            except (TypeError, ValueError) as e:
                logger.warning(f"缓存序列化失败: {e}")

            return result
        return wrapper
    return decorator
