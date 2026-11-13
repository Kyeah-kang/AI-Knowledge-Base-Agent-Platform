"""
安全模块 — JWT 令牌 & 密码哈希

职责：
  1. 生成 Access Token 和 Refresh Token
  2. 验证 Token 并解析用户信息
  3. 密码哈希（加密存储）和密码校验
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# 密码哈希
# CryptContext — passlib 的哈希管理器
# schemes=["bcrypt"] → 使用 bcrypt 算法
# deprecated="auto"  → 自动标记过时的哈希算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    对明文密码进行 bcrypt 哈希。

    为什么不能存明文？
      数据库泄露 → 用户密码全曝光
      用户往往多个平台用同一密码 → 连锁危害
    bcrypt 哈希是单向的，即使数据库泄露也无法还原密码。
    """
    return pwd_context.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """
    用于"用户不存在"分支的假校验，只为对齐耗时。

    为什么要这样做：如果"用户不存在"直接返回、跳过 bcrypt，
    那么两种失败的响应时间会差出 ~100ms，攻击者据此可以枚举用户名。
    """
    return pwd_context.hash("timing-equalizer-not-a-real-password")


def verify_dummy_password(plain_password: str) -> None:
    """做一次和真实校验等价的 bcrypt 计算，然后丢弃结果"""
    pwd_context.verify(plain_password, _dummy_hash())


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    校验明文密码是否和哈希匹配。

    登录时使用：
      if verify_password(input_password, db_user.hashed_password):
          → 密码正确
    """
    return pwd_context.verify(plain_password, hashed_password)


# JWT 令牌
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    生成 Access Token（短期有效，默认 30 分钟）。

    JWT 的结构：
      header.payload.signature
      头部.载荷.签名

    data 中的 sub（subject）标准字段存用户ID：
      {"sub": "1", "type": "access", "exp": 1700000000}
    """
    # 复制入参，避免修改原字典
    to_encode = data.copy()
    # 计算过期时间：优先用传入的 expires_delta，否则用配置的 30 分钟
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # 向载荷中添加过期时间、令牌类型（access）
    to_encode.update({"exp": expire, "type": "access"})
    # 编码生成 JWT 字符串：使用配置的密钥和算法
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    生成 Refresh Token（长期有效，默认 7 天）。

    每个 refresh token 带一个 **jti**（唯一 ID），服务端据此做两件事（P1-12）：
      - 轮换：用一次就作废，防止泄露后被长期复用
      - 吊销：登出时把 jti 从 Redis 删掉
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update(
        {
            "exp": expire,
            "type": "refresh",
            "jti": uuid.uuid4().hex,
        }
    )
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str, expected_type: str = "access") -> dict | None:
    """
    验证 Token 并解析载荷。

    校验内容：
      1. 签名是否正确（防篡改）
      2. 是否过期
      3. type 是否匹配（access 不能用 refresh token）

    返回：载荷字典（包含用户ID等），校验失败返回 None
    """
    try:
        # 解码令牌：验证签名、过期时间（jose 自动校验 exp 字段）
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        # 校验令牌类型是否匹配（如接口认证只能用 access token）
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None
