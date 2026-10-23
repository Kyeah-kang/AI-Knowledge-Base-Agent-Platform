"""
用户相关 Pydantic Schema — 请求/响应数据校验

"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# 请求 Schema（客户端 → 服务器）

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求"""
    refresh_token: str = Field(..., description="刷新令牌")


class UpdateUserRequest(BaseModel):
    """更新个人信息请求"""
    nickname: Optional[str] = Field(None, max_length=50, description="昵称")
    avatar: Optional[str] = Field(None, max_length=255, description="头像URL")


# 响应 Schema（服务器 → 客户端）

class UserResponse(BaseModel):
    """用户信息响应（不包含密码）"""
    id: int
    username: str
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True   # 允许从 ORM 模型创建


class TokenResponse(BaseModel):
    """登录成功返回的令牌"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
