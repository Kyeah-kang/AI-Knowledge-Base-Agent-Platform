"""
 KnowledgeBase 模型
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import MySQLBase
from app.utils.datetime_utils import utc_now


class KnowledgeBase(MySQLBase):
    """知识库模型"""
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="知识库名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="知识库描述"
    )

    # 分类字段
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True, comment="分类（如：销售部、技术部）"
    )


    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, comment="创建者ID"
    )

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
    # owner = relationship("User") + User 模型的 knowledge_bases
    # → 通过 user.knowledge_bases 获取"用户的所有知识库"
    # → 通过 kb.owner 获取"这个知识库的创建者"
    owner = relationship("User", back_populates="knowledge_bases")

    # cascade="all, delete-orphan" — 级联删除
    # 含义：当 KnowledgeBase 被删除时，自动删除它下面所有的 Document
    # "all" → 所有操作（增删改）都级联
    # "delete-orphan" → 从关系中移除的文档也被删除
    # 如果不加 cascade，删除知识库时文档会变成"无主数据"
    documents = relationship(
        "Document", back_populates="knowledge_base",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, name='{self.name}')>"
