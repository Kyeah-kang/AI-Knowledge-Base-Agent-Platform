"""
聊天数据访问层 — 会话 + 消息

作用：封装对chat_session和chat_messages两张表的所有数据库操作
"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.repositories.base import BaseRepository
from app.utils.datetime_utils import utc_now


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
        获取用户的会话列表，按更新时间倒序（最新在前）。

        返回：
            (sessions, total) —— total 是**会话条数**，不是消息条数。
            消息数请用 ChatMessageRepository.count_by_sessions() 一次性批量取。
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

    async def count_by_user(self, user_id: int) -> int:
        """某个用户的会话数量（P2-9）"""
        result = await self.db.execute(
            select(func.count(self.model.id)).where(self.model.user_id == user_id)
        )
        return result.scalar_one()

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

    async def touch(self, session_id: int) -> None:
        """
        更新会话的 updated_at（发消息时调用）。

        历史问题：只往 chat_messages 写消息、从不更新 chat_sessions.updated_at，
        于是"按 updated_at 排序"的会话列表永远不变，刚聊过的会话排不到最前（P1-4）。
        """
        await self.db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=utc_now())
        )
        await self.db.flush()

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
        self,
        session_id: int,
        limit: int = 20,
        exclude_id: int | None = None,
    ) -> list[ChatMessage]:
        """
        获取最近 N 条消息（作为 LLM 上下文）。
        按时间正序返回，最新的在最后。

        参数：
            exclude_id: 需要排除的消息 ID。用于「当前这条消息已经单独拼进 prompt」的场景，
                        否则当前问题会在上下文里出现两次（P0-2 的根因）。
        """
        query = select(self.model).where(self.model.session_id == session_id)
        if exclude_id is not None:
            query = query.where(self.model.id != exclude_id)
        query = query.order_by(self.model.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        # 查出来是倒序的，需要反转回正序
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def count_by_user(self, user_id: int) -> int:
        """某个用户的全部消息条数（join 会话表，P2-9）"""
        result = await self.db.execute(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.user_id == user_id)
        )
        return result.scalar_one()

    async def count_by_session(self, session_id: int) -> int:
        """统计某个会话的消息总数"""
        query = select(func.count(self.model.id)).where(
            self.model.session_id == session_id
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def count_by_sessions(self, session_ids: list[int]) -> dict[int, int]:
        """
        一次查出多个会话的消息数（会话列表用）。

        为什么需要：列表页原来对每个会话单独 count，50 个会话就是 51 条 SQL（P1-4）。
        这里用一条 `GROUP BY` 拿全，没消息的会话不出现在结果里，调用方按 0 处理。
        """
        if not session_ids:
            return {}

        result = await self.db.execute(
            select(self.model.session_id, func.count(self.model.id))
            .where(self.model.session_id.in_(session_ids))
            .group_by(self.model.session_id)
        )
        return {session_id: count for session_id, count in result.all()}

    async def delete_by_session(self, session_id: int) -> None:
        """删除某个会话的所有消息（级联删除的备用方案）"""
        await self.db.execute(
            delete(self.model).where(self.model.session_id == session_id)
        )
        await self.db.flush()
