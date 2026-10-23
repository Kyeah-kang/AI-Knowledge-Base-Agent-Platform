"""
数据库会话管理 — 异步引擎 + 依赖注入
"""

import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


# MySQL 引擎与会话工厂
# 创建异步数据库引擎
mysql_engine = create_async_engine(
    settings.ASYNC_MYSQL_URL,
    pool_size=settings.DB_POOL_SIZE,              # 连接池保持的连接数，避免反复创建新连接
    max_overflow=settings.DB_MAX_OVERFLOW,        # 高峰时允许额外创建的连接数（总共 pool_size + max_overflow）
    pool_pre_ping=settings.DB_POOL_PRE_PING,      # 取出连接前先执行 SELECT 1 验证连接是否有效
    echo=settings.DEBUG,
)

# 会话工厂
MySQLAsyncSessionLocal = async_sessionmaker(
    bind=mysql_engine,
    class_=AsyncSession,
    expire_on_commit=False,    # 防止 commit 后所有模型对象过期（无法访问属性）
)


# PostgreSQL 引擎与会话工厂
pg_engine = create_async_engine(
    settings.POSTGRES_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    echo=settings.DEBUG,
)

PostgreSQLAsyncSessionLocal = async_sessionmaker(
    bind=pg_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── pgvector 向量类型注册 ───
# 在 asyncpg 连接上注册 Vector 类型，使 pgvector 的 Vector 类型在异步连接中可用
try:
    from pgvector.asyncpg import register_vector
    from sqlalchemy import event

    @event.listens_for(pg_engine.sync_engine, "connect")
    def _register_pgvector(dbapi_connection, connection_record):
        """每次新建 PG 连接时注册 Vector 类型编解码器"""
        try:
            register_vector(dbapi_connection)
        except Exception:
            # 如果 vector 扩展未安装，跳过注册
            pass

    _HAS_PGVECTOR_DRIVER = True
    logger.info("pgvector 驱动已加载，将在 PG 连接时注册 Vector 类型")
except ImportError:
    _HAS_PGVECTOR_DRIVER = False
    logger.warning("pgvector.asyncpg 未安装，Vector 类型不会被注册")



# FastAPI 依赖注入（Depends）— 请求生命周期管理
async def get_mysql_db() -> AsyncSession:
    """FastAPI 依赖注入：获取 MySQL 会话（业务数据）"""
    async with MySQLAsyncSessionLocal() as session:
        try:
            yield session                      # 把会话交给路由函数
            await session.commit()             # 成功后提交事务
        except Exception:
            await session.rollback()           # 失败后回滚事务
            raise
        finally:
            await session.close()              # 释放连接回连接池


async def get_pg_db() -> AsyncSession:
    """FastAPI 依赖注入：获取 PostgreSQL 会话（向量数据）"""
    async with PostgreSQLAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
