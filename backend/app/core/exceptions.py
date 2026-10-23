"""
全局异常处理 — 统一错误拦截
"""

import logging

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

logger = logging.getLogger(__name__)


# 自定义业务异常
# AppException 把"HTTP 状态码"和"业务错误码"解耦
class AppException(Exception):
    """业务异常 — 主动抛出的可预知错误"""

    def __init__(
        self,
        code: int = 400,
        message: str = "请求失败",
        data: any = None,
        detail: any = None,
        http_status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.detail = detail
        self.http_status_code = http_status_code


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

    # FastAPI HTTPException
    @app.exception_handler(HTTPException)
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
