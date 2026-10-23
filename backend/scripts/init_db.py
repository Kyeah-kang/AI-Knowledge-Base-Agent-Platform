"""
数据库初始化脚本 — 创建所有表

使用方式：
    cd backend
    python scripts/init_db.py

注意：
    运行前需要确保 MySQL 和 PostgreSQL 数据库已创建。
    MySQL: CREATE DATABASE ai_kb_platform CHARACTER SET utf8mb4;
    PostgreSQL: CREATE DATABASE ai_kb_vector;
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

# 将 backend 目录加入 Python 路径，确保能导入 app 包
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.base import MySQLBase, PostgreSQLBase
from app.database.session import mysql_engine, pg_engine

# 导入所有模型 —— 让 SQLAlchemy 知道这些模型的存在
# 如果不导入，Base.metadata 不会包含对应的表，create_all 会跳过它们
import app.models  # noqa: F401


async def init_mysql():
    """创建 MySQL 所有业务表"""
    print("正在创建 MySQL 表...")
    async with mysql_engine.begin() as conn:
        # create_all — 检查所有继承 MySQLBase 的模型
        # 只创建不存在的表（已存在的表不会覆盖）
        await conn.run_sync(MySQLBase.metadata.create_all)
    print("MySQL 表创建完成")


async def init_postgresql():
    """创建 PostgreSQL 所有向量表"""
    print("正在创建 PostgreSQL 表...")
    async with pg_engine.begin() as conn:
        # 启用 pgvector 扩展（如果尚未启用）
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(PostgreSQLBase.metadata.create_all)
    print("PostgreSQL 表创建完成")


async def main():
    print("=" * 50)
    print("开始初始化数据库...")
    print("=" * 50)

    await init_mysql()
    await init_postgresql()

    print("=" * 50)
    print("所有数据库表创建完成！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
