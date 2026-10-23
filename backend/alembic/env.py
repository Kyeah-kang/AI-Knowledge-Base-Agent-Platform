"""
Alembic 迁移环境配置

这个文件告诉 Alembic 如何连接到数据库，以及哪些模型需要被跟踪。
当数据库模型变更时，通过以下命令生成迁移脚本：
    alembic revision --autogenerate -m "描述变更内容"
"""

import sys
from pathlib import Path

# ⭐ 将 backend 目录加入 Python 路径，才能导入 app 包
sys.path.append(str(Path(__file__).parent.parent))

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ─── 导入所有模型，让 Alembic 检测到它们的变化 ───
from app.database.base import MySQLBase
import app.models  # noqa: F401

# Alembic Config 对象
config = context.config

# 设置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ⭐ target_metadata — Alembic 通过这个变量知道有哪些表
# 执行 autogenerate 时，会对比数据库当前状态和模型的差异
target_metadata = MySQLBase.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不执行"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
