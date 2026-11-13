"""
日志配置 — 结构化输出 + request_id 贯穿 + 文件轮转。

修的是什么（P1-9）：
  原来全仓没有 logging 配置，启动靠 print，业务日志靠 root logger 的 lastResort
  打到 stderr（只有 WARNING 以上、没有时间戳、没有 request_id）。
  一次请求跨 5 层，出问题只能靠时间戳猜。

设计取舍：
  - 默认输出**人读格式**（本地开发舒服），`LOG_JSON=true` 时输出单行 JSON（便于采集）
  - 每条记录自动带 `request_id`，由 RequestContextMiddleware 写入 ContextVar
  - 额外字段（`extra={...}`）会被平铺进 JSON，不会变成 `[object Object]`
  - 文件轮转：logs/app.log，10MB × 5，避免磁盘被日志吃满
  - **不记录请求体**：里面有用户问题和文档内容，属于敏感数据（P1-9 的脱敏要求）
"""

import json
import logging
import logging.config
from pathlib import Path

from app.core.config import settings
from app.core.request_context import get_request_id

# 不属于 extras 的标准 LogRecord 属性，序列化时跳过
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class RequestIdFilter(logging.Filter):
    """把当前协程的 request_id 注入每条日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """单行 JSON 格式，便于 ELK/Loki 采集"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }

        # 平铺业务字段（logger.info("x", extra={"http_status": 200})）
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_") or key == "request_id":
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """人读格式：时间 级别 [request_id] logger - 消息"""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", "-")
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<7} "
            f"[{record.request_id}] "
            f"{record.name} - {record.getMessage()}"
        )
        # 附带业务字段，方便一眼看到状态码/耗时
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_") and k != "request_id"
        }
        if extras:
            base += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> None:
    """应用启动时调用一次（在创建 FastAPI app 之前）"""
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter_class = "app.core.logging.JsonFormatter" if settings.LOG_JSON else "app.core.logging.TextFormatter"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,  # 保留 uvicorn 自己的 logger
            "filters": {
                "request_id": {"()": "app.core.logging.RequestIdFilter"},
            },
            "formatters": {
                "app": {"()": formatter_class},
                "access": {
                    "()": formatter_class
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "app",
                    "filters": ["request_id"],
                },
                "file": {
                    "()": "logging.handlers.RotatingFileHandler",
                    "filename": str(log_dir / "app.log"),
                    "maxBytes": 10 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "formatter": "app",
                    "filters": ["request_id"],
                },
            },
            "root": {
                "level": settings.LOG_LEVEL,
                "handlers": ["console", "file"],
            },
            "loggers": {
                # SQLAlchemy 的 SQL 日志：**即使 echo=False，engine logger 在 INFO 级别
                # 也会把带参数的 SQL 打出来**（实测把用户消息原文打进了日志）。
                # 所以这里默认 WARNING，只有显式打开 DB_ECHO_SQL 才降到 INFO。
                "sqlalchemy.engine": {
                    "level": "INFO" if settings.DB_ECHO_SQL else "WARNING",
                    "propagate": True,
                },
                "sqlalchemy.pool": {"level": "WARNING", "propagate": True},
                "uvicorn.access": {"level": "WARNING", "propagate": True},
                "httpx": {"level": "WARNING", "propagate": True},
                "openai": {"level": "WARNING", "propagate": True},
            },
        }
    )

    logging.getLogger(__name__).info(
        "日志系统就绪", extra={"level": settings.LOG_LEVEL, "json": settings.LOG_JSON}
    )
