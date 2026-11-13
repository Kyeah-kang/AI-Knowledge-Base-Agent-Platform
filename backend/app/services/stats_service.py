"""
用户数据统计（P2-9）。

为什么需要它：Dashboard 的"文档"卡片原来是
`const [docCount] = useState(0)` —— 定义了、展示了、从来没请求过，
页面上永远显示 0。这类"假数据"比缺功能更伤，因为用户会据此做判断。

一次请求把首页要的数字都算出来，避免前端并发打 4 个列表接口再自己数。
所有查询都带 `owner_id`，天然按用户隔离。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.chat_repo import ChatMessageRepository, ChatSessionRepository
from app.repositories.document_repo import DocumentRepository
from app.repositories.knowledge_base_repo import KnowledgeBaseRepository

logger = logging.getLogger(__name__)


class StatsService:
    """Dashboard 统计（按当前用户）"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kb_repo = KnowledgeBaseRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.session_repo = ChatSessionRepository(db)
        self.message_repo = ChatMessageRepository(db)

    async def overview(self, user_id: int) -> dict:
        """一次拿全：知识库 / 文档 / 失败文档 / 会话 / 消息"""
        kb_count = await self.kb_repo.count_by_owner(user_id)
        doc_count = await self.doc_repo.count_by_owner(user_id)
        failed_doc_count = await self.doc_repo.count_failed_by_owner(user_id)
        session_count = await self.session_repo.count_by_user(user_id)
        message_count = await self.message_repo.count_by_user(user_id)

        return {
            "kb_count": kb_count,
            "doc_count": doc_count,
            "failed_doc_count": failed_doc_count,
            "session_count": session_count,
            "message_count": message_count,
        }
