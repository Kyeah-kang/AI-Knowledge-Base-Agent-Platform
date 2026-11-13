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

    # API 文档开关（P2-2）
    # None = 跟随 DEBUG（本地开、生产关）；显式 true/false 可强制覆盖。
    # 生产开着 /docs 等于把全部接口结构公开，攻击面直接变大。
    DOCS_ENABLED: bool | None = None

    @property
    def docs_enabled(self) -> bool:
        """最终是否暴露 /docs 与 /openapi.json（可单测，不依赖环境变量）"""
        return self.DEBUG if self.DOCS_ENABLED is None else self.DOCS_ENABLED

    # 日志（P1-9）
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False                # true → 单行 JSON（生产/采集用）
    LOG_DIR: str = "logs"

    # 数据库（P1-10）
    # DEBUG=True 时不再自动开启 SQL echo：SQL 参数里含用户消息与切片正文，
    # 属于敏感数据。需要排查时单独打开这个开关。
    DB_ECHO_SQL: bool = False

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
    # 上游不可靠是常态：没有超时 + 重试时，一次 429/5xx 就直接变成用户可见的失败（P1-14）
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_RETRIES: int = 2          # 额外重试次数（总尝试 = 1 + n），仅对超时/429/5xx 生效

    # Embedding 配置
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    # 向量维度必须与「模型输出维度」和「document_chunks.embedding 列维度」三者一致。
    # 旧默认值 1536 与已迁移的 vector(1024) 冲突，会让新环境写入直接失败（P0-9）。
    EMBEDDING_DIMENSION: int = 1024
    EMBEDDING_TIMEOUT_SECONDS: float = 30.0
    EMBEDDING_MAX_RETRIES: int = 2
    # 一批最多几条文本：长文档有几百个切片，一次性提交会顶到上游的批大小/超时限制
    EMBEDDING_BATCH_SIZE: int = 32

    # 文件上传配置
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50                      # 单文件最大 50MB
    ALLOWED_EXTENSIONS: list[str] = ["pdf", "docx", "md", "txt", "html"]

    # 文档切片配置
    VECTOR_CHUNK_SIZE: int = 500        # 每个切片的目标字符数
    VECTOR_CHUNK_OVERLAP: int = 50      # 相邻切片重叠字符数（保持上下文连贯）

    # PG 跑在容器里时，宿主机没有 pg_dump —— 备份/恢复脚本走 docker exec
    POSTGRES_DOCKER_CONTAINER: str = "kb-postgres-published"

    # 向量检索配置
    VECTOR_TOP_K: int = 5                              # 检索返回 Top-K 条结果
    # 相似度阈值：低于此值的切片不会进上下文。
    # 0.55 是**实测**出来的（scripts/evaluate_rag.py --sweep，36 题 / 8 篇语料）：
    #   0.70 → recall@1 仅 24%（正确切片被大量丢弃，模型拿不到资料）
    #   0.55 → recall@1 85%，且无答案问题不会被误召回
    #   0.50 → recall@1 94%，但无答案问题有一半会进上下文
    # 换 embedding 模型或语料后必须重跑扫描 —— 这不是普适常数。
    VECTOR_SIMILARITY_THRESHOLD: float = 0.55
    # HNSW 查询时的候选集大小（`SET LOCAL hnsw.ef_search`）：
    # 越大召回越高、越慢。40 是 pgvector 默认值附近的稳妥起点。
    HNSW_EF_SEARCH: int = 40

    # 模型选择与主备切换（P2-4）
    # LLM_ALLOWED_MODELS：允许会话/请求指定的模型；空列表 = 只允许默认模型。
    #   作用：用户填了一个平台没有的模型名时，这里直接退回默认并记指标，
    #   而不是把 400 Invalid model 抛给用户。
    # LLM_FALLBACK_MODELS：主模型超时/429/5xx 时依次尝试的备选模型。
    #   .env 里写成 JSON 数组，例如 ["deepseek-chat","deepseek-reasoner"]
    LLM_ALLOWED_MODELS: list[str] = []
    LLM_FALLBACK_MODELS: list[str] = []

    # Agent 搜索配置
    SEARCH_API_URL: str = ""                           # 搜索 API 地址，留空则返回模拟结果

    # 上下文装配（chat 与 agent 共用同一个入口，见 services/message_context.py）
    CONTEXT_HISTORY_LIMIT: int = 20                    # 送进 LLM 的历史消息**条数**上限
    CONTEXT_MAX_TOKENS: int = 3000                     # 历史消息的 token 预算（超过则从最旧的开始丢）
    SESSION_DETAIL_MAX_MESSAGES: int = 500             # 会话详情最多返回多少条消息（超出会截断并告警）

    # Agent 循环
    AGENT_MAX_ITERATIONS: int = 10                     # 单次提问最多允许的工具调用轮数

    # 速率限制配置
    # 关掉后中间件不注册：给"前面已经有网关限流"的部署，以及跑集成测试用。
    # 注意：关掉等于没有任何保护，生产默认必须为 True。
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_USER_PER_MINUTE: int = 30              # 每用户每分钟最多请求数
    RATE_LIMIT_IP_PER_MINUTE: int = 60                # 每 IP 每分钟最多请求数
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 1000          # 全系统每分钟最多请求数

    # 登录防爆破（P1-13）
    LOGIN_MAX_FAILURES: int = 5                       # 同一用户名连续失败多少次后锁定
    LOGIN_LOCKOUT_MINUTES: int = 15                   # 锁定时长（分钟）

    # Redis 故障时的重连冷却：避免每个请求都白等 3 秒连接超时
    REDIS_RETRY_COOLDOWN_SECONDS: int = 30

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
