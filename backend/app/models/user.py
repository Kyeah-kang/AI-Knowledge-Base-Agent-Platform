"""
User 模型
"""

from datetime import datetime

#   Mapped[T]       → 声明字段类型（Python 类型注解的方式）
#   mapped_column() → 定义数据库列（替代旧版的 Column()）
#   relationship()  → 定义表之间的关系（一对多、多对多）
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import MySQLBase
from app.utils.datetime_utils import utc_now



# User 模型 — 对应数据库的 users 表
class User(MySQLBase):
    """用户模型"""
    __tablename__ = "users"     # 表名

    # 主键
    # id: Mapped[int] → 表示 id 是 int 类型
    # primary_key=True  → 主键
    # autoincrement=True → 自增
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 用户名
    # unique=True  → 唯一约束（不能有同名用户）
    # index=True   → 创建索引（按用户名查询时快）
    # nullable=False → 不能为空
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="用户名"
    )

    # 密码（哈希后）
    # 永远不存明文密码
    # hashed_password 存的是 bcrypt 哈希后的字符串
    # String(255) 是因为 bcrypt 哈希输出长度固定 60 字符，但留余量
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 哈希密码"
    )

    # 可选字段
    # str | None 表示这个字段可以为 NULL
    # nullable=True → 数据库列允许为空
    nickname: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="昵称"
    )
    avatar: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="头像 URL"
    )

    # 布尔字段
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用（管理员可禁用）"
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否管理员"
    )

    # 时间
    # default=utc_now → 创建记录时自动填入当前 UTC 时间
    # onupdate=utc_now → 更新记录时自动刷新时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="更新时间（UTC）",
    )

    # ORM 关系
    # relationship 只是 ORM 层面的"虚拟关系"，不生成数据库约束
    # back_populates="owner" → 和 KnowledgeBase 模型的 owner 属性双向关联
    # 这样可以通过 user.knowledge_bases 获取该用户的所有知识库
    knowledge_bases = relationship("KnowledgeBase", back_populates="owner")
    chat_sessions = relationship("ChatSession", back_populates="user")

    #  __repr__ → 打印对象时的显示格式，方便调试
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"
