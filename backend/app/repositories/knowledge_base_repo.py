"""
知识库数据访问层

封装对 knowledge_bases 表的数据库操作。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase
from app.repositories.base import BaseRepository


# 专门操作知识库表的工具类
class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    """知识库 Repository"""

    def __init__(self, db: AsyncSession):
        # 调用父类 BaseRepository 的初始化方法，并把 db 和 KnowledgeBase 传给父类
        super().__init__(db, KnowledgeBase)

    async def count_by_owner(self, owner_id: int) -> int:
        """某个用户拥有的知识库数量（Dashboard 真实统计用，P2-9）"""
        result = await self.db.execute(
            select(func.count(self.model.id)).where(self.model.owner_id == owner_id)
        )
        return result.scalar_one()

    # 根据用户 ID 查询这个用户拥有的知识库，并支持分页
    async def get_by_owner_id(
        self, owner_id: int, skip: int = 0, limit: int = 20
    ) -> tuple[list[KnowledgeBase], int]:
        """
        获取某个用户的所有知识库，按更新时间倒序,并支持分页。
        返回 (items, total)。
        """
        # 总数(查询这个用户一共有多少个知识库)
        count_query = select(func.count(self.model.id)).where(
            self.model.owner_id == owner_id
        )
        # 把这条查询发给数据库执行
        total_result = await self.db.execute(count_query)
        # scalar_one() 直接拿到 count(*) 的结果（一个整数），如果没有结果或多于一个结果会抛异常
        total = total_result.scalar_one()

        # 分页查询(查询具体的知识库列表)
        query = (
            select(self.model)
            .where(self.model.owner_id == owner_id)
            .order_by(self.model.updated_at.desc())    # 按照更新时间倒序排列(最近更新的知识库排在最前面)
            .offset(skip)                              # 跳过前 skip 条记录
            .limit(limit)                              # 最多返回 limit 条记录
        )
        result = await self.db.execute(query)
        items = list(result.scalars().all())

        # 返回当前页的知识库列表, 总数量
        return items, total

    # 校验知识库是否属于当前用户
    async def verify_owner(self, kb_id: int, owner_id: int) -> KnowledgeBase | None:
        """
        验证知识库是否属于该用户（多租户安全校验）。
        返回知识库对象或 None。
        """
        # 查询 ID 等于 kb_id，并且 owner_id 等于当前用户 ID 的知识库
        result = await self.db.execute(
            select(self.model).where(
                self.model.id == kb_id,
                self.model.owner_id == owner_id,
            )
        )
        # 如果查到了唯一一条数据，就返回它；如果没查到，就返回 None
        return result.scalar_one_or_none()
