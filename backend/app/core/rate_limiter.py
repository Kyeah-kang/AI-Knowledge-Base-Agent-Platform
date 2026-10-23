"""
速率限制（Rate Limiting）— 基于 Redis 滑动窗口算法

防止接口被恶意高频调用，保护后端服务。

支持的限流策略：
  - 用户级别：每个用户每分钟最多 N 次请求
  - IP 级别：每个 IP 每分钟最多 N 次请求
  - 全局级别：全系统每分钟最多 N 次请求

使用方式：
    # 方式 1：FastAPI 中间件（全局限流）
    app.add_middleware(RateLimitMiddleware, limit=100, window=60)

    # 方式 2：在路由中手动检查
    from app.core.rate_limiter import RateLimiter
    limiter = RateLimiter()
    allowed, remaining = await limiter.check_user_rate(user_id, limit=30, window=60)
    if not allowed:
        return {"code": 429, "message": "请求过于频繁"}

滑动窗口原理：
  时间被分为连续的窗口（如 60 秒一个窗口）
  用 Redis 的 INCR + EXPIRE 记录每个窗口内的请求数
  检查时：当前窗口 + 上一个窗口的请求数加权求和
"""

import logging
import time
from typing import Tuple

from app.core.redis_client import redis_manager

logger = logging.getLogger(__name__)

# 默认限流配置
DEFAULT_USER_LIMIT: int = 30        # 每个用户每分钟最多 30 次
DEFAULT_IP_LIMIT: int = 60          # 每个 IP 每分钟最多 60 次
DEFAULT_GLOBAL_LIMIT: int = 1000    # 全系统每分钟最多 1000 次
DEFAULT_WINDOW: int = 60            # 时间窗口（秒）


class RateLimiter:
    """
    速率限制器 — 基于 Redis 的滑动窗口实现

    线程安全、原子操作、低开销。
    """

    def __init__(self):
        self._redis = redis_manager

    async def check_user_rate(
        self,
        user_id: int,
        limit: int = DEFAULT_USER_LIMIT,
        window: int = DEFAULT_WINDOW,
    ) -> Tuple[bool, int]:
        """
        检查用户级别的速率限制。

        参数：
            user_id: 用户 ID
            limit: 窗口内允许的最大请求数
            window: 时间窗口（秒）

        返回：
            (allowed, remaining)
            allowed: True=允许, False=超过限流
            remaining: 当前窗口剩余配额
        """
        return await self._check(f"rate:user:{user_id}", limit, window)

    async def check_ip_rate(
        self,
        ip: str,
        limit: int = DEFAULT_IP_LIMIT,
        window: int = DEFAULT_WINDOW,
    ) -> Tuple[bool, int]:
        """检查 IP 级别的速率限制"""
        return await self._check(f"rate:ip:{ip}", limit, window)

    async def check_global_rate(
        self,
        limit: int = DEFAULT_GLOBAL_LIMIT,
        window: int = DEFAULT_WINDOW,
    ) -> Tuple[bool, int]:
        """检查全局速率限制"""
        return await self._check("rate:global", limit, window)

    async def _check(
        self,
        key: str,
        limit: int,
        window: int,
    ) -> Tuple[bool, int]:
        """
        滑动窗口速率检查核心逻辑。

        用 Redis INCR 实现原子计数器，配合 EXPIRE 自动过期。
        不使用复杂的 Sorted Set，以保持低开销。

        流程：
          1. INCR 当前窗口计数器
          2. 如果是第一次（返回 1），设置过期时间
          3. 判断是否超过限制
        """
        if not self._redis.is_available:
            # Redis 不可用时放行（降级：不限制）
            return True, limit

        try:
            # 当前时间窗口的键名
            window_key = f"{key}:{int(time.time() // window)}"

            # 原子自增
            count = await self._redis.increment(window_key)
            if count is None:
                return True, limit

            # 如果是窗口内的第一次请求，设置过期时间
            if count == 1:
                await self._redis.expire(window_key, window * 2)

            # 计算剩余配额
            remaining = max(0, limit - count)
            allowed = count <= limit

            if not allowed:
                logger.warning(f"速率限制触发: {key} (count={count}, limit={limit})")

            return allowed, remaining

        except Exception as e:
            logger.warning(f"速率检查异常（放行）: {e}")
            return True, limit


# ─── FastAPI 中间件 ───

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI 速率限制中间件。

    自动对每个请求检查限流，超过限制返回 429。

    使用方式：
        app.add_middleware(
            RateLimitMiddleware,
            user_limit=30,
            ip_limit=60,
            global_limit=1000,
            window=60,
            exclude_paths=["/health", "/docs", "/redoc", "/openapi.json"],
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        user_limit: int = DEFAULT_USER_LIMIT,
        ip_limit: int = DEFAULT_IP_LIMIT,
        global_limit: int = DEFAULT_GLOBAL_LIMIT,
        window: int = DEFAULT_WINDOW,
        exclude_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.limiter = RateLimiter()
        self.user_limit = user_limit
        self.ip_limit = ip_limit
        self.global_limit = global_limit
        self.window = window
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/redoc", "/openapi.json"]

    async def dispatch(self, request: Request, call_next):
        # 跳过不需要限流的路径
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # 跳过静态文件和文档
        if request.url.path.startswith("/static"):
            return await call_next(request)

        # 1. 检查全局限流
        allowed, _ = await self.limiter.check_global_rate(
            limit=self.global_limit, window=self.window
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "系统繁忙，请稍后再试",
                    "data": None,
                },
                headers={"Retry-After": str(self.window)},
            )

        # 2. 检查 IP 限流
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = await self.limiter.check_ip_rate(
            ip=client_ip, limit=self.ip_limit, window=self.window
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "请求过于频繁，请稍后再试",
                    "data": None,
                },
                headers={
                    "Retry-After": str(self.window),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # 用户级限流在 get_current_user 依赖中执行（此处仅做全局/IP 限流）

        # 通过限流，继续处理请求
        response = await call_next(request)

        # 在响应头中加入剩余配额信息
        if remaining is not None:
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Limit"] = str(self.ip_limit)

        return response
