"""
用户数据访问层（User Repository）

继承 BaseRepository 获得通用 CRUD 能力，
添加用户特有的查询方法（如按用户名查找）。
"""

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户 Repository"""

    def __init__(self, db):
        super().__init__(db, User)

    async def get_by_username(self, username: str) -> User | None:
        """按用户名查找用户（用于登录时校验）"""
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_list(
        self, skip: int = 0, limit: int = 20, is_admin: bool | None = None
    ) -> tuple[list[User], int]:
        """
        获取用户列表（管理员用）。

        is_admin=None 返回所有用户，True/False 按角色筛选。
        """
        filters = {}
        if is_admin is not None:
            filters["is_admin"] = is_admin
        return await self.get_all(skip=skip, limit=limit, **filters)
