"""
Refresh Token 的服务端状态 —— 轮换与吊销（P1-12）。

解决两个问题：
  1. **refresh 不轮换**：一张 refresh token 泄露后可以长期复用。现在每次刷新都会
     消费掉旧的 jti 并签发新的（一次性使用），重放旧 token 直接 401。
  2. **登出无效**：JWT 无状态，登出后 token 仍然有效。现在把 jti 记在 Redis，
     登出即删；access token 因为是 30 分钟短票，不在本轮做黑名单（见 FIX_PLAN）。

降级策略：Redis 不可用时**无法判定**，此时放行（fail-open）并记指标。
  理由：把"Redis 挂了"变成"所有人都无法刷新登录"，损失远大于收益。
"""

import logging

from app.core import metrics
from app.core.redis_client import redis_manager

logger = logging.getLogger(__name__)

_KEY_PREFIX = "auth:refresh:"


def _key(jti: str) -> str:
    return f"{_KEY_PREFIX}{jti}"


async def register_refresh(jti: str, user_id: int, ttl_seconds: int) -> bool:
    """登录/刷新成功后登记新的 refresh jti"""
    ok = await redis_manager.set(_key(jti), str(user_id), expire=max(ttl_seconds, 60))
    if not ok:
        metrics.incr("refresh_token_store_total", status="unavailable")
    return ok


async def consume_refresh(jti: str) -> tuple[bool, int | None]:
    """
    消费一个 refresh jti（一次性）。

    返回：
        (store_available, user_id)
        - (False, None) → Redis 不可用，无法判定，调用方应放行
        - (True, None)  → token 不存在/已被用过/已被吊销 → 调用方应返回 401
        - (True, uid)   → 合法且已被消费
    """
    client = await redis_manager.get_client()
    if client is None:
        metrics.incr("refresh_token_store_total", status="unavailable")
        return False, None

    try:
        raw = await client.get(_key(jti))
        if raw is None:
            metrics.incr("refresh_token_store_total", status="invalid")
            return True, None

        # 先删再返回：并发重放时只有一个请求能拿到值
        await client.delete(_key(jti))
        metrics.incr("refresh_token_store_total", status="rotated")
        return True, int(raw)
    except Exception as e:
        logger.warning("消费 refresh jti 失败（放行）: %s", e)
        metrics.incr("refresh_token_store_total", status="error")
        return False, None


async def revoke_refresh(jti: str) -> bool:
    """登出：吊销 refresh jti"""
    existed = await redis_manager.delete(_key(jti))
    metrics.incr("refresh_token_store_total", status="revoked" if existed else "revoke_miss")
    return existed
