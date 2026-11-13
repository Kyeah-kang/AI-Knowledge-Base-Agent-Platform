"""
 ChatSession + ChatMessage — 一对多关系 + 级联删除 + 排序
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import MySQLBase
from app.utils.datetime_utils import utc_now


class ChatSession(MySQLBase):
    """
    聊天会话（MySQL）

    一次对话就是一个会话，包含多条消息。
    model_name 记录本次对话使用的模型，方便切换不同厂商的模型。
    """
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK → User：每个会话属于一个用户
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(
        String(100), default="新对话", comment="会话标题（可自动生成或用户自定义）"
    )

    # model_name — 记录使用的模型
    # 这样同一个会话切换到不同模型时，可以追溯到之前用的是哪个
    model_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="使用的模型名（如 deepseek-chat）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="更新时间（UTC，每次发消息自动刷新）",
    )

    # 关系
    user = relationship("User", back_populates="chat_sessions")

    # 一对多关系的排序
    # order_by="ChatMessage.created_at" → session.messages 时默认按时间排序
    # 这样获取消息列表时就是按对话顺序排列的
    # cascade="all, delete-orphan" → 删除会话时级联删除所有消息
    messages = relationship(
        "ChatMessage", back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at"
    )

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, title='{self.title}')>"


class ChatMessage(MySQLBase):
    """
    聊天消息（MySQL）

    role 字段和 LLM API 的消息角色对齐：
    system → 系统提示词
    user   → 用户消息
    assistant → AI 回复
    """
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ondelete="CASCADE" → 数据库级联删除
    # 如果 ChatSession 被删了，MySQL 自动删除这个会话的所有消息
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # role: user / assistant / system
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="角色：user / assistant / system"
    )

    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="消息内容"
    )

    # JSON 字段 — 存储辅助信息
    # 注意字段名用 extra_meta，因为 metadata 是 SQLAlchemy 保留属性
    extra_meta: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="扩展信息（token数、耗时等）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )

    # 关系
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, role='{self.role}')>"
