"""
全局异常处理 — 统一错误拦截
"""

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# 业务码落在这些值里时，它与 HTTP 状态码是同义的（401/403/404/429/502/503 ...）
_HTTP_STATUS_LIKE = range(400, 600)


# 自定义业务异常
# AppException 把"HTTP 状态码"和"业务错误码"解耦
class AppException(Exception):
    """
    业务异常 — 主动抛出的可预知错误。

    状态码约定（P0-6）：
      - 传了 `http_status_code` → 用它
      - 没传 → 用 `code` 本身（当 code 是合法 HTTP 状态码时），否则退回 400

    历史上这里把 `http_status_code` 写死成 400，
    于是 `AppException(code=401)` 会以 **HTTP 400** 返回（body 里才是 401），
    前端拦截器、网关、监控按状态码统计全部失真。
    """

    def __init__(
        self,
        code: int = 400,
        message: str = "请求失败",
        data: Any = None,
        detail: Any = None,
        http_status_code: int | None = None,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.detail = detail
        self.http_status_code = (
            http_status_code
            if http_status_code is not None
            else (code if code in _HTTP_STATUS_LIKE else 400)
        )
        # 必须调用父类构造：否则 str(exc) 是空字符串，
        # 日志里只剩 "app.core.exceptions.AppException" 一个类名（排查时完全看不出原因），
        # 拼进用户可见文案时也会变成 "Agent 执行出错：" 这种没有信息量的句子。
        super().__init__(message)


class RetrievalError(AppException):
    """
    知识库检索失败 — 明确区分「没有相关内容」和「检索坏了」。

    约定：
      - 搜索成功但没有命中 → 不是异常，返回空结果（由调用方决定话术）
      - 检索链路本身不可用或报错 → 抛本异常（HTTP 503）

    为什么继承 AppException：
      这样路由（JSON 响应）、SSE 生成器、Agent 工具三处都能用同一套
      `except AppException` 处理，不需要为检索单独写分支。
    """

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(
            code=503,
            message=message,
            detail=detail,
            http_status_code=503,
        )


# 全局异常处理器（注册函数）
# 在 main.py 中通过 app.add_exception_handler 或 @app.exception_handler 注册

def register_exception_handlers(app):
    """
    注册所有异常处理器到 FastAPI 应用

    在主入口 main.py 中调用：
        from app.core.exceptions import register_exception_handlers
        register_exception_handlers(app)
    """

    # 自定义业务异常
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        if exc.detail:
            logger.error("业务异常（%s）: %s", exc.message, exc.detail)
        return JSONResponse(
            status_code=exc.http_status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "data": exc.data,
            },
        )

    # 请求参数校验异常
    # FastAPI 自动校验 Pydantic 模型，参数不合法时抛出此异常
    # 这里把错误格式化成统一的格式
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        # 提取详细的校验错误信息
        errors = exc.errors()
        error_messages = []
        for error in errors:
            field = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            error_messages.append(f"{field}: {msg}")

        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "message": "参数校验失败",
                "data": {
                    "errors": error_messages,
                },
            },
        )

    # HTTPException —— 同时覆盖 **Starlette** 的那一支。
    # 原因：路由不存在（/api/v1/xxx 打错）时 Starlette 抛的是自己的 HTTPException，
    # 而 @app.exception_handler(HTTPException) 只注册了 fastapi 那个子类，
    # 于是 404 会漏出默认的 {"detail": "Not Found"}，前端得多写一种解析分支。
    # StarletteHTTPException 是父类，注册它即可同时覆盖两者。
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.detail,
                "data": None,
            },
        )

    #  兜底异常处理（未知错误）
    # 防止未捕获的异常导致服务器崩溃或泄露敏感信息
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务器内部错误",
                "data": None,
            },
        )
