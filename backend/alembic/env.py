"""
Alembic 迁移环境 — **双数据库**（MySQL 业务库 + PostgreSQL 向量库）。

为什么需要两个目标（P1-2）：
  业务表在 MySQL、切片/向量在 PostgreSQL，两边的 metadata 完全不同，
  一个 env.py 只能管一边 —— 这就是原来"迁移目录为空、靠 create_all 建表"的根因。

用法：
    alembic upgrade head                 # MySQL（默认段 [alembic]）
    alembic -n postgres upgrade head     # PostgreSQL（[postgres] 段）
    alembic revision --autogenerate -m "xxx"            # MySQL
    alembic -n postgres revision --autogenerate -m "xxx" # PostgreSQL

已有数据库的接法（重要）：
    老库里的表是 create_all 建的，第一次接入迁移系统要 **stamp** 而不是 upgrade，
    否则会重复建表：
        alembic stamp head
        alembic -n postgres stamp head

临时指向别的库（演练 / CI）：
    ALEMBIC_DATABASE_URL=... alembic upgrade head
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

# ⭐ 将 backend 目录加入 Python 路径，才能导入 app 包
sys.path.append(str(Path(__file__).parent.parent))

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ─── 导入所有模型，让 Alembic 检测到它们的变化 ───
import app.models  # noqa: F401
from app.core.config import settings
from app.database.base import MySQLBase, PostgreSQLBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _target() -> tuple[str, object, str, bool]:
    """
    根据使用的配置段决定连哪个库。

    返回：(name, metadata, url, render_as_batch)
      render_as_batch：MySQL 的 ALTER 能力有限，批量模式能生成
      "建临时表 → 拷数据 → 换名" 的安全迁移。
    """
    is_postgres = config.config_ini_section == "postgres"

    override = os.getenv("ALEMBIC_DATABASE_URL")
    if is_postgres:
        url = override or settings.POSTGRES_URL
        return "postgres", PostgreSQLBase.metadata, url, False

    url = override or settings.ASYNC_MYSQL_URL
    return "mysql", MySQLBase.metadata, url, True


TARGET_NAME, TARGET_METADATA, TARGET_URL, RENDER_AS_BATCH = _target()
target_metadata = TARGET_METADATA


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """跳过 MySQL 内部的 alembic_version 之外的噪音（暂无需要排除的对象）"""
    return True


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不执行"""
    context.configure(
        url=TARGET_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=RENDER_AS_BATCH,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=RENDER_AS_BATCH,
        include_object=_include_object,
        # 版本表按目标分开命名，避免两个库共用一个名字时互相干扰
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：异步引擎（项目本身全异步，用 aiomysql / asyncpg）"""
    connectable = create_async_engine(TARGET_URL, poolclass=NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
