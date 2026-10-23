"""
认证业务逻辑 — 注册、登录、刷新 Token

职责：
  1. 注册：验证用户名唯一性 → 密码哈希 → 创建用户
  2. 登录：校验用户名密码 → 生成 Token 对
  3. 刷新：验证 Refresh Token → 签发新 Access Token
"""

from app.core.exceptions import AppException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.repositories.user_repo import UserRepository
from app.schemas.user import LoginRequest, RegisterRequest, TokenResponse, UserResponse


class AuthService:
    """认证服务"""

    def __init__(self, repo: UserRepository):
        self.repo = repo

    async def register(self, request: RegisterRequest) -> TokenResponse:
        """用户注册"""
        # 检查用户名是否已存在
        existing = await self.repo.get_by_username(request.username)
        if existing:
            raise AppException(code=400, message="用户名已存在")

        # 创建用户（密码自动哈希）
        user = await self.repo.create(
            username=request.username,
            hashed_password=hash_password(request.password),
        )

        # 生成 Token
        return await self._generate_tokens(user)

    async def login(self, request: LoginRequest) -> TokenResponse:
        """用户登录"""
        user = await self.repo.get_by_username(request.username)
        if not user:
            raise AppException(code=401, message="用户名或密码错误")

        if not verify_password(request.password, user.hashed_password):
            raise AppException(code=401, message="用户名或密码错误")

        if not user.is_active:
            raise AppException(code=403, message="账号已被禁用")

        return await self._generate_tokens(user)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """刷新 Access Token"""
        payload = verify_token(refresh_token, expected_type="refresh")
        if not payload:
            raise AppException(code=401, message="无效的刷新令牌")

        user_id = int(payload.get("sub"))
        user = await self.repo.get(user_id)
        if not user or not user.is_active:
            raise AppException(code=401, message="用户不存在或已被禁用")

        return await self._generate_tokens(user)

    async def _generate_tokens(self, user) -> TokenResponse:
        """生成 Token 对（access + refresh）"""
        token_data = {"sub": str(user.id)}

        return TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=create_refresh_token(token_data),
            user=UserResponse.model_validate(user),
        )
