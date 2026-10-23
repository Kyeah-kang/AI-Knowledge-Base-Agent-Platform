"""
项目统一配置管理
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用基础配置
    APP_NAME: str = "AI Knowledge Base Agent Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    #  MySQL 配置（业务数据）
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "ai_kb_platform"

    # @property — 把方法变成属性调用
    # 每次访问 settings.MYSQL_URL 时动态拼接字符串
    # 好处：参数改了，URL 自动更新，不需要重新赋值
    @property
    def MYSQL_URL(self) -> str:
        """构造 MySQL 连接 URL（同步版，用于 SQLAlchemy）"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )

    @property
    def ASYNC_MYSQL_URL(self) -> str:
        """构造 MySQL 异步连接 URL（异步版，用于 create_async_engine）"""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )

    # PostgreSQL 配置（向量数据）
    # MySQL：存业务数据（用户/会话/文档元信息），生态成熟，运维方便
    # PostgreSQL+pgvector：存向量数据（文档切片embedding），原生支持向量检索
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DATABASE: str = "ai_kb_vector"

    @property
    def POSTGRES_URL(self) -> str:
        """构造 PostgreSQL 连接 URL（异步版，用 asyncpg 驱动）"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"
        )

    # Redis 配置（缓存/限流）
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT 配置
    # JWT 三要素：密钥 + 算法 + 过期时间
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"                                   # 对称加密算法
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30                      # Access Token 短期有效
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7                         # Refresh Token 长期有效

    # LLM 配置
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = "https://api.deepseek.com/v1"
    LLM_MODEL_NAME: str = "deepseek-chat"
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7

    # Embedding 配置
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_MODEL_NAME: str = "text-embedding-ada-002"
    EMBEDDING_DIMENSION: int = 1536       # 向量维度，决定了 pgvector 索引的维度

    # 文件上传配置
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50                      # 单文件最大 50MB
    ALLOWED_EXTENSIONS: list[str] = ["pdf", "docx", "md", "txt", "html"]

    # 文档切片配置
    VECTOR_CHUNK_SIZE: int = 500        # 每个切片的目标字符数
    VECTOR_CHUNK_OVERLAP: int = 50      # 相邻切片重叠字符数（保持上下文连贯）

    # 向量检索配置
    VECTOR_TOP_K: int = 5                              # 检索返回 Top-K 条结果
    VECTOR_SIMILARITY_THRESHOLD: float = 0.7           # 相似度阈值，低于此值的结果丢弃

    # Agent 搜索配置
    SEARCH_API_URL: str = ""                           # 搜索 API 地址，留空则返回模拟结果

    # 速率限制配置
    RATE_LIMIT_USER_PER_MINUTE: int = 30              # 每用户每分钟最多请求数
    RATE_LIMIT_IP_PER_MINUTE: int = 60                # 每 IP 每分钟最多请求数
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 1000          # 全系统每分钟最多请求数

    # 数据库连接池配置
    # 连接池的作用：不用每次请求都创建新连接，而是复用已有连接，大幅提升性能
    DB_POOL_SIZE: int = 10          # 连接池中保持的连接数
    DB_MAX_OVERFLOW: int = 20       # 高峰时最多额外创建的连接数
    DB_POOL_PRE_PING: bool = True   # 从连接池取出连接前先 ping 一下，确保连接有效

    # class Config — pydantic-settings 的配置元类
    # 告诉 pydantic 从 .env 文件读取配置
    class Config:
        env_file = ".env"              # 指定 .env 文件路径
        env_file_encoding = "utf-8"


# 全局单例
# 在模块加载时自动执行 Settings()，读取 .env → 赋值给 settings
# 其他文件通过 from app.core.config import settings 获取配置
# 单例的好处：配置只加载一次，全局共享
settings = Settings()
