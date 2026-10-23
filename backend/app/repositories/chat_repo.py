"""
聊天数据访问层 — 会话 + 消息

作用：封装对chat_session和chat_messages两张表的所有数据库操作
"""

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.repositories.base import BaseRepository

# 定义会话数据操作类，专门处理ChatSession（聊天会话）模型的数据库操作
class ChatSessionRepository(BaseRepository[ChatSession]):
    """会话 Repository"""

    def __init__(self, db: AsyncSession):
        # 初始化：绑定数据库会话与会话模型
        super().__init__(db, ChatSession)

    async def get_by_user_id(
        self, user_id: int, skip: int = 0, limit: int = 20
    ) -> tuple[list[ChatSession], int]:
        """
        获取用户的所有会话，按更新时间倒序（最新在前）。
        同时返回每个会话的消息总数。
        """
        # 查询当前用户的会话总数量
        count_query = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # 分页查询该用户会话，按更新时间倒序排列
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        sessions = list(result.scalars().all())

        return sessions, total

    async def verify_owner(self, session_id: int, user_id: int) -> ChatSession | None:
        """
        验证会话是否属于该用户。
        返回会话对象或 None（不属于该用户时返回 None）。
        """
        result = await self.db.execute(
            select(self.model).where(
                self.model.id == session_id,
                self.model.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

# 定义消息数据操作类，专门处理ChatMessage（聊天消息）模型的数据库操作
class ChatMessageRepository(BaseRepository[ChatMessage]):
    """消息 Repository"""

    def __init__(self, db: AsyncSession):
        # 初始化：绑定数据库会话与消息模型
        super().__init__(db, ChatMessage)

    async def get_by_session(
        self, session_id: int, skip: int = 0, limit: int = 100
    ) -> tuple[list[ChatMessage], int]:
        """
        获取某个会话的消息列表（按时间正序）
        同时返回该会话的消息总数
        """
        # 统计当前会话消息总数
        count_query = select(func.count(self.model.id)).where(
            self.model.session_id == session_id
        )
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        # 分页查询会话内消息，按创建时间正序
        query = (
            select(self.model)
            .where(self.model.session_id == session_id)
            .order_by(self.model.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        return messages, total

    async def get_recent_history(
        self, session_id: int, limit: int = 20
    ) -> list[ChatMessage]:
        """
        获取最近 N 条消息（作为 LLM 上下文）。
        按时间正序返回，最新的在最后。
        """
        query = (
            select(self.model)
            .where(self.model.session_id == session_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        # 查出来是倒序的，需要反转回正序
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def count_by_session(self, session_id: int) -> int:
        """统计某个会话的消息总数"""
        query = select(func.count(self.model.id)).where(
            self.model.session_id == session_id
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def delete_by_session(self, session_id: int) -> None:
        """删除某个会话的所有消息（级联删除的备用方案）"""
        await self.db.execute(
            delete(self.model).where(self.model.session_id == session_id)
        )
        await self.db.flush()
