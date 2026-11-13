"""
 FastAPI 主入口 — 应用的启动核心

启动方式：
    cd backend
    uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.health import app_meta, http_status_for, probe_dependencies
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware

setup_logging()

logger = logging.getLogger(__name__)


def _validate_runtime_config() -> None:
    if settings.JWT_SECRET_KEY == "your-secret-key-change-in-production":
        message = (
            "JWT_SECRET_KEY 仍是默认占位符：任何知道该默认值的人都能伪造任意用户/管理员的 token。"
            '请生成随机密钥写入 .env：python -c "import secrets;print(secrets.token_hex(32))"'
        )
        if not settings.DEBUG:
            raise RuntimeError(message)
        # DEBUG 下不阻止启动，但必须刺眼：原来是 print("Warning: ...")，很容易被刷过去
        logger.error(message)
    elif len(settings.JWT_SECRET_KEY) < 32 and not settings.DEBUG:
        raise RuntimeError("JWT_SECRET_KEY 过短（至少 32 字符），请使用随机密钥")


def _check_vector_stack() -> None:
    """
    启动时校验向量链路是否完整。

    为什么要在启动时做：
      历史上缺 pgvector Python 客户端会让 embedding 列静默退化为 TEXT，
      上传"成功"但向量永远写不进去。这类问题必须在启动时就暴露，
      而不是等用户上传文档后才发现检索不到东西。
    """
    from app.models.document import _HAS_PGVECTOR, DocumentChunk

    if not _HAS_PGVECTOR:
        message = (
            "缺少 pgvector Python 客户端：向量列无法注册为 VECTOR 类型"
            "（pip install pgvector）。文档将无法建立向量索引。"
        )
        if not settings.DEBUG:
            raise RuntimeError(message)
        logger.error(message)
        return

    logger.info(
        "向量链路配置",
        extra={
            "model": settings.EMBEDDING_MODEL_NAME,
            "dimension": settings.EMBEDDING_DIMENSION,
            "orm_column": str(DocumentChunk.__table__.c.embedding.type),
        },
    )


async def _probe_embedding_column_dim() -> None:
    """
    就近校验数据库里 embedding 列的真实维度。

    ORM 的 Vector(n) 维度来自配置，而数据库列在建表时就固定了；
    两者不一致时写入会被 PostgreSQL 拒绝。这里做一次 best-effort 探测
    （超时 2 秒，探测不到只告警，不影响启动）。

    注意：pgvector 的 `atttypmod` 直接就是维度值（不像 varchar 要减 4）。
    实测 `vector(1024)` → `atttypmod = 1024`；按 `atttypmod - 4` 解码会误报 1020。
    """
    from sqlalchemy import text

    from app.database.session import pg_engine

    sql = text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
    )
    try:
        async with asyncio.timeout(2):
            async with pg_engine.connect() as conn:
                dim = await conn.scalar(sql)
    except Exception as e:
        logger.warning("跳过向量列维度校验（PostgreSQL 不可用或表不存在）：%s", e)
        return

    if dim is None:
        logger.warning("未能读取 document_chunks.embedding 的列维度")
    elif int(dim) != settings.EMBEDDING_DIMENSION:
        metrics.incr("vector_dimension_mismatch_total")
        logger.error(
            "向量维度不一致：数据库列为 vector(%s)，但 EMBEDDING_DIMENSION=%s。"
            "写入会失败，请对齐配置或迁移列维度。",
            dim,
            settings.EMBEDDING_DIMENSION,
        )
    else:
        logger.info("向量列维度校验通过", extra={"column": f"vector({dim})"})


# 应用生命周期管理（async context manager）
# startup：应用启动时执行（创建数据库连接池等）
# shutdown：应用关闭时执行（释放连接池等）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ─── 启动时执行 ───
    _validate_runtime_config()
    logger.info(
        "%s v%s 启动中",
        settings.APP_NAME,
        settings.APP_VERSION,
        extra={
            "mysql": f"{settings.MYSQL_HOST}:{settings.MYSQL_PORT}",
            "postgres": f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}",
            "llm_model": settings.LLM_MODEL_NAME,
            "debug": settings.DEBUG,
        },
    )
    _check_vector_stack()
    await _probe_embedding_column_dim()

    # 尝试连接 Redis（日志里不要用 emoji：Windows 控制台 cp936 编码会抛异常）
    from app.core.redis_client import redis_manager

    redis = await redis_manager.get_client()
    logger.info(
        "Redis %s",
        "已连接" if redis else "未连接（缓存/限流/登录锁定降级）",
        extra={"redis": f"{settings.REDIS_HOST}:{settings.REDIS_PORT}"},
    )

    yield
    # ─── 关闭时执行 ───
    try:
        from app.core.redis_client import redis_manager
        await redis_manager.close()
    except Exception:
        pass
    logger.info("%s 已关闭", settings.APP_NAME)


# API 是否暴露文档（P2-2）：None 时跟随 DEBUG，生产默认关闭
# 逻辑在 Settings.docs_enabled 里，可以单测，不用改环境变量重来一遍
_docs_enabled = settings.docs_enabled

# 标签说明：让 /docs 里每个分组都有上下文，而不是一堆散接口
_OPENAPI_TAGS = [
    {"name": "认证", "description": "注册 / 登录 / 刷新（轮换）/ 登出（吊销）"},
    {"name": "用户", "description": "当前用户信息"},
    {"name": "聊天", "description": "会话管理与 SSE 流式问答（消息走 POST body）"},
    {"name": "知识库", "description": "知识库 CRUD"},
    {"name": "文档", "description": "上传（流式落盘 + 内容去重）、列表、删除"},
    {"name": "Agent", "description": "工具调用型对话；事件类型见 docs/API_ERRORS.md"},
    {"name": "统计", "description": "Dashboard 用的按用户聚合数字"},
    {"name": "系统", "description": "健康检查"},
]

# 统一错误响应：挂在 include_router 上，所有业务接口都会出现在 /docs 里
_COMMON_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "未认证或凭证无效（code=401）"},
    403: {"description": "已认证但无权限（code=403）"},
    404: {"description": "资源不存在（code=404）"},
    422: {"description": "参数校验失败（code=422，data.errors 指明字段）"},
    429: {"description": "限流或登录锁定（code=429）"},
    503: {"description": "依赖不可用，如向量库/数据库（code=503）"},
}

# FastAPI 应用实例
app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "企业级 AI 知识库 Agent 平台后端 API。\n\n"
        "**统一响应信封**：`{code, message, data}`，前端以 `code` 为准。\n\n"
        "**错误码表**：见仓库 `docs/API_ERRORS.md`。\n\n"
        "**追踪**：每个响应带 `X-Request-ID`，报障时提供它即可定位整条链路。"
    ),
    version=settings.APP_VERSION,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,  # 生命周期管理
)


# CORS 中间件配置
# CORS（跨域资源共享）：浏览器安全策略，控制前端能否跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,    # 是否允许携带 Cookie
    allow_methods=["*"],       # 允许的 HTTP 方法
    allow_headers=["*"],       # 允许的请求头
)

# 速率限制中间件（基于 Redis，Redis 不可用时自动降级）
# RATE_LIMIT_ENABLED=false 时不注册：集成测试或"网关前面已限流"的部署会用
if settings.RATE_LIMIT_ENABLED:
    from app.core.rate_limiter import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        user_limit=settings.RATE_LIMIT_USER_PER_MINUTE,
        ip_limit=settings.RATE_LIMIT_IP_PER_MINUTE,
        global_limit=settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
        window=60,
        exclude_paths=["/", "/health", "/docs", "/redoc", "/openapi.json"],
    )


# 请求上下文中间件：生成/透传 X-Request-ID，记录访问日志与耗时（P1-9）
app.add_middleware(RequestContextMiddleware)

# 注册全局异常处理器
register_exception_handlers(app)


# ─── 路由注册 ───
# prefix: /api/v1 是所有 v1 接口的统一前缀
# 路由模块会反向 import app.core.*，放在这里是刻意的（避免循环依赖）
from app.routers.v1 import (  # noqa: E402
    agent,
    auth,
    chat,
    document,
    knowledge_base,
    stats,
    user,
)

for _router in (
    auth.router,
    user.router,
    chat.router,
    knowledge_base.router,
    document.router,
    agent.router,
    stats.router,
):
    app.include_router(
        _router, prefix="/api/v1", responses=_COMMON_RESPONSES
    )


# 根路由（健康检查）
@app.get("/", tags=["系统"], summary="服务信息")
async def root():
    """API 根路径 — 健康检查"""
    return {
        "code": 200,
        "message": "success",
        "data": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
        },
    }


@app.get("/health", tags=["系统"], summary="健康检查（真实探活三项依赖）")
async def health_check(response: Response):
    """
    健康检查 — 真实探活依赖（P1-10）。

    - MySQL / PostgreSQL 任一 down → `unhealthy` + HTTP 503（负载均衡会摘掉实例）
    - Redis down → `degraded` + HTTP 200（缓存/限流可降级，不该因此整个服务下线）

    同时返回进程内指标，便于在没有 Prometheus 的情况下看到
    "上传失败几次、检索报错几次、重试几次"。
    """
    result = await probe_dependencies()
    status_code = http_status_for(result["status"])
    response.status_code = status_code

    payload = {
        **result,
        **app_meta(),
        "metrics": metrics.snapshot(),
    }
    if status_code != 200:
        logger.error("健康检查失败", extra={"dependencies": result["dependencies"]})
    return payload
