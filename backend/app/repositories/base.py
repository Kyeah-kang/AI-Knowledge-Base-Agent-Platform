"""
Repository 基类 — 通用 CRUD 操作

Repository 模式的作用：
  将数据访问逻辑从业务逻辑中分离。
  业务层（service）不需要知道用的是 MySQL 还是 PostgreSQL，
  只需要调用 repository 的方法。

泛型 T 继承 MySQLBase，确保只能用于 MySQL 模型。

这段代码相当于数据库万能工具类，让所有表都能直接用增删改查，不用重复写代码
"""

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import MySQLBase

T = TypeVar("T", bound=MySQLBase)


class BaseRepository(Generic[T]):
    """通用 Repository 基类"""

    def __init__(self, db: AsyncSession, model: type[T]):
        self.db = db
        self.model = model

    async def create(self, **kwargs) -> T:
        """创建一条记录"""
        obj = self.model(**kwargs)
        self.db.add(obj)
        await self.db.flush()   # flush 让数据库生成 id，但不 commit
        await self.db.refresh(obj)
        return obj

    async def get(self, id: int) -> T | None:
        """根据主键 ID 查询"""
        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_all(
        self, skip: int = 0, limit: int = 20, **filters
    ) -> tuple[list[T], int]:
        """
        分页查询列表 + 总数。

        返回 (items, total) 元组，配合分页响应使用。
        filters 参数用于精确过滤，如 get_all(is_admin=True)
        """
        query = select(self.model)

        # 应用过滤条件
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)

        # 先查总数
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # 再查分页数据
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def update(self, id: int, **kwargs) -> T | None:
        """更新记录，返回更新后的对象"""
        obj = await self.get(id)
        if not obj:
            return None
        for key, value in kwargs.items():
            if value is not None:   # 只更新非 None 的字段
                setattr(obj, key, value)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, id: int) -> bool:
        """删除记录，返回是否删除成功"""
        obj = await self.get(id)
        if not obj:
            return False
        await self.db.delete(obj)
        await self.db.flush()
        return True
