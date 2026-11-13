"""
 公共依赖注入 — 数据库会话 + 当前用户
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.database.session import PostgreSQLAsyncSessionLocal, get_mysql_db

logger = logging.getLogger(__name__)


# 把数据库依赖重新导出到同一个位置
# 这样所有路由统一从 app.core.deps 导入，而不是从多个地方
# 如果将来要换数据库或改会话策略，只改这一个文件
async def get_db() -> AsyncSession:
    """获取 MySQL 业务数据库会话（别名，最常用）"""
    async for session in get_mysql_db():
        yield session


async def get_vector_db() -> AsyncSession | None:
    """
    获取 PostgreSQL 向量数据库会话。

    ⚠️ 写法约束：**`yield` 不能放进 `try/except Exception` 里**。
      FastAPI 会把路由抛出的异常 throw 回首个 `yield` 处。如果外层再 `except Exception`
      并接着 `yield`，异常就被吞掉，最终报
      `RuntimeError: generator didn't stop after athrow()` → HTTP 500，
      业务状态码（401/403/404/503）全部丢失。
      实测：P0-6 修好映射后，`GET /chat/sessions/{不存在的id}` 仍是 500 而不是 404，
      根因就是这里（原实现 `async for ... yield` 包在 try/except 内）。

    降级约定：
      - 只有"拿不到会话对象"才降级为 None，此时业务层必须显式报错（P0-1）
      - 路由/业务异常一律原样上抛，交给全局异常处理器
    """
    try:
        session = PostgreSQLAsyncSessionLocal()
    except Exception as e:
        # 极少数情况（驱动/配置错误）。真正的连接失败发生在首次查询时，
        # 那种错误会从业务层冒出来，并带上明确原因。
        metrics.incr("vector_db_session_total", status="error")
        logger.error("创建 PostgreSQL 会话失败，本次请求的向量操作不可用: %s", e)
        yield None
        return

    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
