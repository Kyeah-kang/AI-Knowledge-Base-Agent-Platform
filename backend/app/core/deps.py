"""
 公共依赖注入 — 数据库会话 + 当前用户
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_mysql_db, get_pg_db


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

    PG 不可用时返回 None（开发阶段降级），
    让业务层自行决定是否跳过向量相关操作。
    """
    try:
        async for session in get_pg_db():
            yield session
    except Exception as e:
        import logging
        logging.warning(f"PostgreSQL 不可用，跳过向量操作: {e}")
        yield None
