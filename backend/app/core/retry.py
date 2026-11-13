"""
外部 API 调用的超时与重试工具。

为什么自己写而不直接上 tenacity：
  - 当前环境没有装 tenacity，为了一个退避循环不值得新增依赖；
  - 需要把"重试了几次、为什么重试"记进指标（`/health` 里能直接看到），
    第三方装饰器不方便这么统计。

什么该重试（P1-14）：
  - 连接失败 / 超时        → 重试
  - 429（限流）、5xx        → 重试，指数退避 + 抖动
  - 4xx（参数错误、鉴权失败）→ **不重试**，重试只会白烧钱和日志

注意：流式调用只重试"建流"这一步，不重试"读流"——
  已经吐出去一半的内容没法回滚，重试会导致前端收到重复片段。
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 测试里可以替换成 no-op，避免真的等待
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

# 值得重试的 HTTP 状态码（408 请求超时、425 太早、429 限流、5xx 上游故障）
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否值得重试（延迟 import openai，避免 core 层强依赖它）"""
    try:
        import openai
    except ImportError:  # pragma: no cover - openai 是硬依赖
        return False

    # APITimeoutError 是 APIConnectionError 的子类，一并覆盖
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True

    status = getattr(exc, "status_code", None)
    return status in RETRYABLE_STATUS


async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    operation: str,
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> Any:
    """
    执行一次外部调用，失败时按指数退避重试。

    参数：
        fn: 无参协程工厂，例如 `lambda: client.chat.completions.create(...)`
        operation: 指标标签，如 "llm_chat" / "embedding_batch"
        max_retries: **额外**重试次数（总尝试次数 = 1 + max_retries）
        base_delay / max_delay: 退避时长（秒），实际还叠加 ±30% 抖动

    异常：
        最终失败时抛出最后一次的原始异常，由调用方决定怎么包装。
    """
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                metrics.incr("external_call_total", status="fail", operation=operation)
                raise

            attempt += 1
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.3)  # 抖动：避免所有请求同时重试

            metrics.incr("external_retry_total", operation=operation)
            logger.warning(
                "%s 调用失败（第 %s/%s 次尝试），%.2fs 后重试：%s",
                operation,
                attempt,
                max_retries,
                delay,
                exc,
            )
            await _sleep(delay)
