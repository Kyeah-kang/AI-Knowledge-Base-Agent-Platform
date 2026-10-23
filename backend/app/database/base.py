"""
 SQLAlchemy ORM 基类 — 多数据库绑定
"""

from sqlalchemy.orm import DeclarativeBase


# 继承 MySQLBase 的模型会创建在 MySQL 数据库中
class MySQLBase(DeclarativeBase):
    """MySQL 业务数据库基类"""
    pass


# 继承 PostgreSQLBase 的模型会创建在 PostgreSQL 数据库中
class PostgreSQLBase(DeclarativeBase):
    """PostgreSQL 向量数据库基类"""
    pass
