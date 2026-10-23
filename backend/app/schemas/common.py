"""
 统一响应格式 & 分页 & 通用 Schema
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

# TypeVar + Generic — Pydantic 泛型
# T 是一个"类型占位符"，在使用时指定具体的类型
# 比如 Response[User] → data 字段的类型就是 User
# 这样每个接口返回的数据类型都是明确的
T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    所有接口统一返回这个结构，前端统一解析：
    {
        "code": 200,
        "message": "success",
        "data": { ... }
    }
    """
    code: int = 200
    message: str = "success"
    data: Optional[T] = None       # 允许值为None(调用时可以不传)


class PaginationResponse(BaseModel, Generic[T]):
    """
    分页响应

    所有列表接口统一分页格式：
    {
        "items": [...],
        "total": 100,
        "page": 1,
        "page_size": 20
    }
    """
    items: list[T]                     # 当前页的数据列表
    total: int                         # 总记录数
    page: int                          # 当前页码
    page_size: int                     # 每页条数


class PaginationParams(BaseModel):
    """
    分页请求参数

    所有列表接口统一接收的分页参数。
    """
    page: int = 1                      # 页码，从1开始
    page_size: int = 20                # 每页条数
