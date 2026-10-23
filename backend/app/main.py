"""
 FastAPI 主入口 — 应用的启动核心

启动方式：
    cd backend
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers


def _validate_runtime_config() -> None:
    if not settings.DEBUG and settings.JWT_SECRET_KEY == "your-secret-key-change-in-production":
        raise RuntimeError("JWT_SECRET_KEY must be changed before running in non-debug mode")
    if settings.DEBUG and settings.JWT_SECRET_KEY == "your-secret-key-change-in-production":
        print("Warning: JWT_SECRET_KEY is still the default value; set a custom secret for production.")


# 应用生命周期管理（async context manager）
# startup：应用启动时执行（创建数据库连接池等）
# shutdown：应用关闭时执行（释放连接池等）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ─── 启动时执行 ───
    _validate_runtime_config()
    print(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    print(f"   MySQL:     {settings.MYSQL_HOST}:{settings.MYSQL_PORT}")
    print(f"   PostgreSQL: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
    print(f"   LLM Model:  {settings.LLM_MODEL_NAME}")

    # 尝试连接 Redis
    try:
        from app.core.redis_client import redis_manager
        redis = await redis_manager.get_client()
        if redis:
            print(f"   Redis:     {settings.REDIS_HOST}:{settings.REDIS_PORT} ✅")
        else:
            print(f"   Redis:     未连接（缓存/限流降级）")
    except Exception:
        print(f"   Redis:     未连接（缓存/限流降级）")

    yield
    # ─── 关闭时执行 ───
    try:
        from app.core.redis_client import redis_manager
        await redis_manager.close()
    except Exception:
        pass
    print(f"{settings.APP_NAME} 已关闭")


# FastAPI 应用实例
app = FastAPI(
    title=settings.APP_NAME,
    description="企业级AI知识库Agent平台后端API",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
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
try:
    from app.core.rate_limiter import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        user_limit=settings.RATE_LIMIT_USER_PER_MINUTE,
        ip_limit=settings.RATE_LIMIT_IP_PER_MINUTE,
        global_limit=settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
        window=60,
        exclude_paths=["/", "/health", "/docs", "/redoc", "/openai.json"],
    )
except ImportError:
    pass


# 注册全局异常处理器
register_exception_handlers(app)


# ─── 路由注册 ───
# prefix: /api/v1 是所有 v1 接口的统一前缀
from app.routers.v1 import agent, auth, chat, document, knowledge_base, user

app.include_router(auth.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(knowledge_base.router, prefix="/api/v1")
app.include_router(document.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")


# 根路由（健康检查）
@app.get("/")
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


@app.get("/health")
async def health_check():
    """健康检查接口 — 给 Docker/K8s 探针用"""
    return {"status": "healthy", "version": settings.APP_VERSION}
