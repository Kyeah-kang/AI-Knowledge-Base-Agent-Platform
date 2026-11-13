"""
请求上下文中间件 — request_id + 访问日志 + 耗时（P1-9）。

为什么用**纯 ASGI** 中间件而不是 BaseHTTPMiddleware：
  BaseHTTPMiddleware 会包一层 task，对 StreamingResponse（本项目的 SSE）有已知副作用，
  而 SSE 正是我们最不能出问题的地方。纯 ASGI 只包装 send，不动响应体。
"""

import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger("app.http")

# 这些路径的访问日志没有价值（探针/文档），但要保留 request_id
_QUIET_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/"}


class RequestContextMiddleware:
    """给每个请求分配 request_id，并记录一条结构化访问日志"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._extract_request_id(scope) or uuid.uuid4().hex[:16]
        token = set_request_id(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            metrics.observe_ms("http_request_duration", elapsed_ms, status=str(status_code // 100) + "xx")
            metrics.incr(
                "http_requests_total", status=str(status_code // 100) + "xx"
            )

            path = scope.get("path", "")
            if path not in _QUIET_PATHS:
                logger.info(
                    "%s %s -> %s",
                    scope.get("method", "?"),
                    path,
                    status_code,
                    extra={
                        "http_method": scope.get("method"),
                        "http_path": path,
                        "http_status": status_code,
                        "duration_ms": round(elapsed_ms, 2),
                    },
                )
            reset_request_id(token)

    @staticmethod
    def _extract_request_id(scope: Scope) -> str | None:
        """透传上游（网关/前端）带来的 X-Request-ID，便于跨系统串联"""
        for name, value in scope.get("headers") or []:
            if name == b"x-request-id":
                return value.decode("latin-1")[:64]
        return None
