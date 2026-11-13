"""
健康检查探针（P1-10）。

原来 `/health` 只是 `return {"status": "healthy"}` —— 数据库挂了它照样 healthy，
K8s/负载均衡会被骗过去。这里改成**真的去探**每个依赖，并分项返回状态与耗时。

语义：
  - MySQL / PostgreSQL 是**硬依赖**：任一 down → 整体 unhealthy → HTTP 503
  - Redis 是**软依赖**（缓存/限流/登录锁定可降级）→ down 时 degraded，但仍 200
    （否则 Redis 一抖，整个服务就被摘掉，得不偿失）
"""

import asyncio
import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 1.5


async def _timed(name: str, coro_factory) -> dict:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT):
            await coro_factory()
        return {
            "status": "up",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as e:  # 超时/连接失败都算 down
        message = f"{type(e).__name__}: {e}".strip()
        logger.warning("依赖探活失败: %s -> %s", name, message)
        return {
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": message[:200] or "timeout",
        }


async def _probe_mysql() -> None:
    from sqlalchemy import text

    from app.database.session import mysql_engine

    async with mysql_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _probe_postgres() -> None:
    from sqlalchemy import text

    from app.database.session import pg_engine

    async with pg_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _probe_redis() -> None:
    from app.core.redis_client import redis_manager

    client = await redis_manager.get_client()
    if client is None:
        raise RuntimeError("redis unavailable")
    await client.ping()


async def probe_dependencies() -> dict:
    """并行探测三个依赖，返回分项结果与整体状态"""
    mysql, postgres, redis = await asyncio.gather(
        _timed("mysql", _probe_mysql),
        _timed("postgres", _probe_postgres),
        _timed("redis", _probe_redis),
    )

    hard_ok = mysql["status"] == "up" and postgres["status"] == "up"
    if not hard_ok:
        overall = "unhealthy"
    elif redis["status"] != "up":
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "dependencies": {"mysql": mysql, "postgres": postgres, "redis": redis},
    }


def http_status_for(overall: str) -> int:
    return 200 if overall in ("healthy", "degraded") else 503


def app_meta() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug": settings.DEBUG,
    }
