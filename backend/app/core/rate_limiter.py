"""
速率限制（Rate Limiting）— 基于 Redis 的双窗口加权滑动窗口

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

算法原理（双窗口加权）：
  时间被切成连续窗口（如 60 秒一个）
  每个窗口一个计数器（INCR + EXPIRE，O(1)、原子）
  判定时把"当前窗口计数"与"上一窗口计数 × 剩余权重"相加，
  得到近似滑动窗口的估算值 —— 避免固定窗口在交界处双倍放行
"""

import logging
import time

from app.core.redis_client import redis_manager

logger = logging.getLogger(__name__)

# 默认限流配置
DEFAULT_USER_LIMIT: int = 30        # 每个用户每分钟最多 30 次
DEFAULT_IP_LIMIT: int = 60          # 每个 IP 每分钟最多 60 次
DEFAULT_GLOBAL_LIMIT: int = 1000    # 全系统每分钟最多 1000 次
DEFAULT_WINDOW: int = 60            # 时间窗口（秒）


class RateLimiter:
    """
    速率限制器 — 双窗口加权滑动窗口

    原子操作（INCR/GET）、低开销；Redis 不可用时 fail-open 并记指标。
    """

    def __init__(self):
        self._redis = redis_manager

    async def check_user_rate(
        self,
        user_id: int,
        limit: int = DEFAULT_USER_LIMIT,
        window: int = DEFAULT_WINDOW,
    ) -> tuple[bool, int]:
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
    ) -> tuple[bool, int]:
        """检查 IP 级别的速率限制"""
        return await self._check(f"rate:ip:{ip}", limit, window)

    async def check_global_rate(
        self,
        limit: int = DEFAULT_GLOBAL_LIMIT,
        window: int = DEFAULT_WINDOW,
    ) -> tuple[bool, int]:
        """检查全局速率限制"""
        return await self._check("rate:global", limit, window)

    async def _check(
        self,
        key: str,
        limit: int,
        window: int,
    ) -> tuple[bool, int]:
        """
        滑动窗口限流（双窗口加权近似）。

        为什么不是固定窗口（原实现）：
          固定窗口在交界处可以**双倍放行** —— 窗口末尾打满 + 下个窗口开头再打满，
          实际是 2×limit。原注释写着"滑动窗口"，实现却是固定窗口，属于注释撒谎。

        为什么不用 ZSET 精确滑窗：
          每个请求都要 ZREMRANGEBYSCORE + ZCARD + ZADD + EXPIRE 四条命令并维护集合，
          开销明显更大。双窗口加权（当前窗口计数 + 上一窗口计数 × 剩余权重）
          误差不超过一个窗口内的均匀分布假设，足以压住突发流量，且只要 O(1) 三条命令。

        降级（fail-open）：Redis 不可用时放行，并记指标 —— 限流失效总好过整站不可用。
        """
        from app.core import metrics

        client = await self._redis.get_client()
        if client is None:
            metrics.incr("rate_limit_total", status="redis_unavailable")
            return True, limit

        try:
            now = time.time()
            current_window = int(now // window)
            elapsed = now - current_window * window
            prev_weight = 1 - elapsed / window       # 上一窗口还剩多少权重

            current_key = f"{key}:{current_window}"
            previous_key = f"{key}:{current_window - 1}"

            count_current = await self._redis.increment(current_key)
            if count_current is None:
                metrics.incr("rate_limit_total", status="redis_unavailable")
                return True, limit

            if count_current == 1:
                # 留两个窗口，保证作为"上一窗口"时还没过期
                await self._redis.expire(current_key, window * 2)

            previous_raw = await self._redis.get(previous_key)
            try:
                count_previous = int(previous_raw or 0)
            except (TypeError, ValueError):
                count_previous = 0

            estimated = count_current + count_previous * prev_weight
            allowed = estimated <= limit
            remaining = max(0, int(limit - estimated))

            metrics.incr("rate_limit_total", status="allow" if allowed else "deny")
            if not allowed:
                logger.warning(
                    "速率限制触发: %s (estimated=%.1f, limit=%s)",
                    key,
                    estimated,
                    limit,
                )

            return allowed, remaining

        except Exception as e:
            metrics.incr("rate_limit_total", status="error")
            logger.warning(f"速率检查异常（放行）: {e}")
            return True, limit


# ─── FastAPI 中间件 ───
# 这些 import 故意放在文件末尾：rate_limiter 顶层被 app.core 引用，
# 而 starlette 的中间件基类会反向 import，放在顶部会形成循环依赖。
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.types import ASGIApp  # noqa: E402


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
