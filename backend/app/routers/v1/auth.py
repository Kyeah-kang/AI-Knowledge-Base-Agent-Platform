"""
认证路由 — 注册 / 登录 / 刷新 Token

POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.repositories.user_repo import UserRepository
from app.schemas.common import Response
from app.schemas.user import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """依赖注入：创建 AuthService 实例"""
    repo = UserRepository(db)
    return AuthService(repo)


@router.post("/register", response_model=Response[TokenResponse])
async def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
):
    """用户注册"""
    result = await service.register(request)
    return Response(data=result)


@router.post("/login", response_model=Response[TokenResponse])
async def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    """用户登录，返回 access_token + refresh_token"""
    result = await service.login(request)
    return Response(data=result)


@router.post("/refresh", response_model=Response[TokenResponse])
async def refresh_token(
    request: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
):
    """刷新 Access Token"""
    result = await service.refresh_token(request.refresh_token)
    return Response(data=result)
