"""
用户路由 — 个人信息管理 / 管理员用户管理

GET    /api/v1/users/me              → 获取当前用户信息
PUT    /api/v1/users/me              → 修改个人信息
GET    /api/v1/users                 → [管理员] 用户列表
PUT    /api/v1/users/{id}/status    → [管理员] 启用/禁用用户
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.routers.v1 import get_current_admin, get_current_user
from app.schemas.common import PaginationResponse, Response
from app.schemas.user import UpdateUserRequest, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["用户管理"])


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    """依赖注入：创建 UserService 实例"""
    repo = UserRepository(db)
    return UserService(repo)



# 普通用户接口（需登录）
@router.get(
    "/me",
    summary="获取当前用户",
    response_model=Response[UserResponse],
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """获取当前登录用户的个人信息"""
    result = await service.get_profile(current_user.id)
    return Response(data=result)


@router.put(
    "/me",
    summary="修改个人资料",
    response_model=Response[UserResponse],
)
async def update_my_profile(
    request: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """更新当前用户的个人信息"""
    result = await service.update_profile(current_user.id, request)
    return Response(data=result)


# 管理员接口
@router.get(
    "",
    summary="知识库列表",
    response_model=Response[PaginationResponse[UserResponse]],
)
async def list_users(
    page: int = 1,
    page_size: int = 20,
    admin: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
):
    """[管理员] 获取用户列表"""
    items, total = await service.get_user_list(page=page, page_size=page_size)
    return Response(
        data=PaginationResponse(
            items=items, total=total, page=page, page_size=page_size
        )
    )


@router.put(
    "/{user_id}/status",
    summary="启用/禁用用户（管理员）",
    response_model=Response[UserResponse],
)
async def toggle_user_status(
    user_id: int,
    admin: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
):
    """[管理员] 启用/禁用用户"""
    result = await service.toggle_user_status(user_id)
    return Response(data=result)
