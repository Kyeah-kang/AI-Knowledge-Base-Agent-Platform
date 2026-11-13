"""
v1 API 路由 — 公共依赖

这里的 get_current_user 作为所有需要登录的接口的依赖注入。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.core.rate_limiter import RateLimiter
from app.core.security import verify_token
from app.models.user import User
from app.repositories.user_repo import UserRepository

# OAuth2PasswordBearer — FastAPI 内置的 Bearer Token 提取器
# 它会从请求头 Authorization: Bearer <token> 中提取 token
# 如果请求头缺失或格式错误，自动返回 401
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# 登录用户认证
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    从 JWT Token 解析当前登录用户。

    注入方式：
        @router.get("/users/me")
        async def get_me(current_user: User = Depends(get_current_user)):
            ...
    """
    payload = verify_token(token, expected_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌",
        )

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌缺少用户标识"
        )
    user_id = int(subject)
    repo = UserRepository(db)
    user = await repo.get(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    limiter = RateLimiter()
    allowed, _ = await limiter.check_user_rate(
        user_id=user.id,
        limit=settings.RATE_LIMIT_USER_PER_MINUTE,
        window=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )

    return user

# 管理员权限校验
async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    验证当前用户是否为管理员。

    注入方式：
        @router.get("/users")
        async def list_users(admin: User = Depends(get_current_admin)):
            ...
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
