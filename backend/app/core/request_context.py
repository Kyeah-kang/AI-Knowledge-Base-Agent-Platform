"""
请求上下文 — 用 ContextVar 存 request_id。

为什么需要：一次请求会经过 middleware → router → service → repository，
日志散落在各层。没有 request_id 时，只能靠时间戳猜哪几行属于同一次请求（P1-9）。

ContextVar（而不是全局变量）是因为 asyncio 里同一线程会并发处理多个请求。
"""

from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str):
    """设置当前协程的 request_id，返回 token 供 reset 使用"""
    return _request_id.set(value)


def reset_request_id(token) -> None:
    """恢复上一个值（必须和 set_request_id 成对出现）"""
    try:
        _request_id.reset(token)
    except ValueError:  # 跨协程 reset 会抛这个，忽略即可
        pass


def get_request_id() -> str:
    """读取当前 request_id；没有上下文时返回 '-'"""
    return _request_id.get()
