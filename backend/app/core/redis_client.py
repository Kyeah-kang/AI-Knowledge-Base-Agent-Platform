"""
Redis 连接管理 — 连接池 + 心跳检测 + 自动降级

使用方式：
    from app.core.redis_client import redis_manager

    # 获取 Redis 客户端
    redis = await redis_manager.get_client()
    if redis:
        await redis.set("key", "value")
        value = await redis.get("key")

    # 业务层无需关心连接细节，redis_manager 自动管理

设计决策：
  1. 懒加载：首次使用时才建立连接，启动时不阻塞
  2. 自动降级：Redis 不可用时返回 None，不抛异常
  3. 连接池复用：避免每次请求都创建新连接
  4. 心跳检测：定期检查连接是否健康
"""

import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    """
    Redis 连接管理器（单例）

    管理 Redis 连接池的生命周期。
    所有 Redis 操作都通过此管理器进行。
    """

    def __init__(self):
        self._client = None
        self._available = False
        # 失败后的冷却截止时间（monotonic）：避免每个请求都白等 3 秒连接超时
        self._next_retry_at = 0.0

    async def get_client(self):
        """
        获取 Redis 客户端；不可用时返回 None（业务层负责降级）。

        注意冷却机制（P1-13）：
          原来只要 `_available` 是 False，**每个请求**都会重新连一次 Redis，
          而每次连接失败要等 3 秒超时 —— Redis 一挂，接口整体被拖慢 3 秒。
          现在失败后进入 `REDIS_RETRY_COOLDOWN_SECONDS` 冷却期，期间直接返回 None。
        """
        if self._available:
            return self._client

        if time.monotonic() < self._next_retry_at:
            return None

        await self._connect()
        return self._client if self._available else None

    async def _connect(self):
        """连接 Redis（懒加载）；失败后进入冷却期"""
        try:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                # 连接池配置
                socket_connect_timeout=3,       # 连接超时 3 秒
                socket_timeout=3,               # 读写超时 3 秒
                retry_on_timeout=True,          # 超时自动重试
                max_connections=20,             # 最大连接数
                health_check_interval=30,       # 每 30 秒心跳检测
            )

            # 测试连接是否可用
            await self._client.ping()
            self._available = True
            logger.info(
                f"Redis 连接成功: {settings.REDIS_HOST}:{settings.REDIS_PORT}"
            )

        except ImportError:
            logger.warning("redis 包未安装，缓存功能不可用")
            self._available = False
            self._next_retry_at = time.monotonic() + 3600
        except Exception as e:
            logger.warning(f"Redis 连接失败，缓存功能降级: {e}")
            self._available = False
            self._next_retry_at = (
                time.monotonic() + settings.REDIS_RETRY_COOLDOWN_SECONDS
            )

    async def close(self):
        """关闭 Redis 连接池（应用关闭时调用）"""
        if self._client:
            await self._client.close()
            self._client = None
            self._available = False
            logger.info("Redis 连接已关闭")

    @property
    def is_available(self) -> bool:
        """Redis 是否可用"""
        return self._available

    # ─── 便捷方法（封装常用操作，自动处理不可用降级） ───

    async def get(self, key: str) -> str | None:
        """获取缓存值"""
        client = await self.get_client()
        if not client:
            return None
        try:
            return await client.get(key)
        except Exception as e:
            logger.warning(f"Redis get 失败 (key={key}): {e}")
            return None

    async def set(self, key: str, value: str, expire: int = 300) -> bool:
        """
        设置缓存值。

        参数：
            key: 缓存键
            value: 缓存值
            expire: 过期时间（秒），默认 5 分钟
        """
        client = await self.get_client()
        if not client:
            return False
        try:
            await client.set(key, value, ex=expire)
            return True
        except Exception as e:
            logger.warning(f"Redis set 失败 (key={key}): {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        client = await self.get_client()
        if not client:
            return False
        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis delete 失败 (key={key}): {e}")
            return False

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        client = await self.get_client()
        if not client:
            return False
        try:
            return await client.exists(key) > 0
        except Exception as e:
            logger.warning(f"Redis exists 失败 (key={key}): {e}")
            return False

    async def increment(self, key: str, amount: int = 1) -> int | None:
        """
        原子自增（用于限流计数）。

        参数：
            key: 计数器键
            amount: 增量，默认 1

        返回：
            自增后的值，Redis 不可用时返回 None
        """
        client = await self.get_client()
        if not client:
            return None
        try:
            return await client.incr(key, amount)
        except Exception as e:
            logger.warning(f"Redis incr 失败 (key={key}): {e}")
            return None

    async def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间"""
        client = await self.get_client()
        if not client:
            return False
        try:
            return await client.expire(key, seconds)
        except Exception as e:
            logger.warning(f"Redis expire 失败 (key={key}): {e}")
            return False


# 全局单例
redis_manager = RedisManager()
