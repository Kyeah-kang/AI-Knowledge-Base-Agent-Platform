"""
用户业务逻辑 — 个人信息管理、管理员用户管理
"""

from app.core.exceptions import AppException
from app.repositories.user_repo import UserRepository
from app.schemas.user import UpdateUserRequest, UserResponse


class UserService:
    """用户服务"""

    # 用户个人信息管理（普通用户）
    def __init__(self, repo: UserRepository):
        self.repo = repo

    async def get_profile(self, user_id: int) -> UserResponse:
        """获取用户个人信息"""
        user = await self.repo.get(user_id)
        if not user:
            raise AppException(code=404, message="用户不存在")
        return UserResponse.model_validate(user)

    async def update_profile(
        self, user_id: int, request: UpdateUserRequest
    ) -> UserResponse:
        """更新个人信息"""
        user = await self.repo.update(
            user_id,
            nickname=request.nickname,
            avatar=request.avatar,
        )
        if not user:
            raise AppException(code=404, message="用户不存在")
        return UserResponse.model_validate(user)

    # 管理员用户管理
    async def get_user_list(
        self, page: int = 1, page_size: int = 20
    ) -> tuple[list[UserResponse], int]:
        """获取用户列表（管理员）"""
        skip = (page - 1) * page_size
        users, total = await self.repo.get_user_list(skip=skip, limit=page_size)
        return [UserResponse.model_validate(u) for u in users], total

    async def toggle_user_status(self, user_id: int) -> UserResponse:
        """启用/禁用用户（管理员）"""
        user = await self.repo.get(user_id)
        if not user:
            raise AppException(code=404, message="用户不存在")

        user = await self.repo.update(user_id, is_active=not user.is_active)
        return UserResponse.model_validate(user)
