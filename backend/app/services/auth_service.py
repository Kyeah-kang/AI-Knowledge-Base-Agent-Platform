"""
认证业务逻辑 — 注册、登录、刷新 Token

职责：
  1. 注册：验证用户名唯一性 → 密码哈希 → 创建用户
  2. 登录：校验用户名密码 → 生成 Token 对
  3. 刷新：验证 Refresh Token → 签发新 Access Token
"""

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.redis_client import redis_manager
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_dummy_password,
    verify_password,
    verify_token,
)
from app.core.token_store import consume_refresh, register_refresh, revoke_refresh
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

    @staticmethod
    def _fail_key(username: str) -> str:
        """按用户名记失败次数（不区分大小写，防止换个大小写绕过锁定）"""
        return f"login:fail:{(username or '').strip().lower()[:64]}"

    async def _ensure_not_locked(self, username: str) -> None:
        """
        连续失败达到上限就短期锁定（P1-13）。

        Redis 不可用时 `get` 返回 None → 视为未锁定（fail-open）：
        锁定是增强项，不能让 Redis 故障变成"所有人都登不上"。
        """
        raw = await redis_manager.get(self._fail_key(username))
        try:
            failures = int(raw or 0)
        except (TypeError, ValueError):
            failures = 0

        if failures >= settings.LOGIN_MAX_FAILURES:
            metrics.incr("login_locked_total")
            raise AppException(
                code=429,
                message=(
                    f"登录失败次数过多，请 {settings.LOGIN_LOCKOUT_MINUTES} 分钟后再试"
                ),
                http_status_code=429,
            )

    async def _record_login_failure(self, username: str) -> None:
        key = self._fail_key(username)
        count = await redis_manager.increment(key)
        if count == 1:
            await redis_manager.expire(key, settings.LOGIN_LOCKOUT_MINUTES * 60)
        metrics.incr("login_failed_total")

    async def _clear_login_failures(self, username: str) -> None:
        await redis_manager.delete(self._fail_key(username))

    async def login(self, request: LoginRequest) -> TokenResponse:
        """用户登录（带失败计数与短期锁定）"""
        # 0. 已被锁定就直接拒绝，别再去查库/算哈希
        await self._ensure_not_locked(request.username)

        user = await self.repo.get_by_username(request.username)

        # 1. 用户不存在 / 密码错误 → 同一个提示，且耗时对齐（防用户名枚举）
        if not user:
            verify_dummy_password(request.password)
            await self._record_login_failure(request.username)
            raise AppException(code=401, message="用户名或密码错误", http_status_code=401)

        if not verify_password(request.password, user.hashed_password):
            await self._record_login_failure(request.username)
            raise AppException(code=401, message="用户名或密码错误", http_status_code=401)

        if not user.is_active:
            raise AppException(code=403, message="账号已被禁用", http_status_code=403)

        # 2. 登录成功 → 清空失败计数
        await self._clear_login_failures(request.username)
        return await self._generate_tokens(user)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        刷新 Access Token（**轮换式**，P1-12）。

        流程：验签 → 消费旧 jti（一次性）→ 校验用户 → 签发全新 token 对。
        旧 refresh 在消费后立即失效，重复使用会得到 401。
        """
        payload = verify_token(refresh_token, expected_type="refresh")
        if not payload:
            raise AppException(code=401, message="无效的刷新令牌", http_status_code=401)

        jti = payload.get("jti")
        store_available, stored_user_id = (False, None)
        if jti:
            store_available, stored_user_id = await consume_refresh(jti)
        # Redis 可用但 jti 查不到 = 已用过 / 已吊销 / 伪造
        if store_available and stored_user_id is None:
            raise AppException(
                code=401, message="刷新令牌已失效，请重新登录", http_status_code=401
            )

        subject = payload.get("sub")
        if stored_user_id is None and subject is None:
            raise AppException(
                code=401, message="无效的刷新令牌", http_status_code=401
            )
        user_id = stored_user_id or int(subject)  # type: ignore[arg-type]
        user = await self.repo.get(user_id)
        if not user or not user.is_active:
            raise AppException(code=401, message="用户不存在或已被禁用", http_status_code=401)

        return await self._generate_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        """
        登出：吊销这张 refresh token。

        说明：access token 是无状态短票（默认 30 分钟），本轮不做黑名单，
        因此登出后 access 在过期前仍可用 —— 这是明确取舍，写在 FIX_PLAN 里。
        """
        payload = verify_token(refresh_token, expected_type="refresh")
        jti = (payload or {}).get("jti")
        if jti:
            await revoke_refresh(jti)

    async def _generate_tokens(self, user) -> TokenResponse:
        """生成 Token 对（access + refresh）"""
        token_data = {"sub": str(user.id)}

        refresh_token = create_refresh_token(token_data)

        # 登记 refresh jti：轮换与吊销都依赖它（Redis 不可用时降级，见 token_store）
        payload = verify_token(refresh_token, expected_type="refresh") or {}
        jti = payload.get("jti")
        if jti:
            await register_refresh(
                jti,
                user.id,
                ttl_seconds=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
            )

        return TokenResponse(
            access_token=create_access_token(token_data),
            refresh_token=refresh_token,
            user=UserResponse.model_validate(user),
        )
