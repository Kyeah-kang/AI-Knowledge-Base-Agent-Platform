# 差距审计报告 — 企业级 AI 知识库 Agent 平台

> 审计对象：`D:\python\AI Knowledge Base Agent Platform`
> 审计日期：2026-10-23
> 审计范围：`backend/app/` 全部业务代码、脚本、配置、测试；`frontend/src/` 页面与 API；本地 MySQL、Docker PostgreSQL/Redis、Python 虚拟环境。
> 审计方式：**只读**。读代码、`git show`、SQL `SELECT`、import/连接检查；未修改任何文件、未写入数据库。
> 结论：**架构骨架合格，但 RAG 向量链路当前是断的；工程化与评测缺失。** 本报告逐条给出证据、影响、修复方案与验收标准。

---

## 0. 结论摘要（30 秒）

### 0.1 做得好的地方（面试要主动讲）

1. **分层清晰**：`router → service → repository → model`，依赖方向单一，`schemas` 独立，`core` 横切。
2. **依赖注入规范**：`Depends(get_db)` / `get_vector_db` / `get_current_user`，路由不直接建连接。
3. **统一响应与异常**：`Response[T]`、`PaginationResponse[T]`、`AppException` + 4 类全局异常处理器。
4. **越权校验统一**：知识库、文档、会话都有 `verify_owner`；管理端有 `get_current_admin`。
5. **AI 链路完整**：OpenAI 兼容 LLM、SSE 流式、RAG 组件拆分（parser/splitter/embedding/vector store/retriever）、LangGraph Agent + 工具注册表。
6. **基础设施有意识**：Redis 缓存、限流、健康检查、连接池、配置单例、无 Redis 降级。

### 0.2 致命问题（按杀伤力排序）

1. **RAG 没有真正工作**：Docker 里有 pgvector 扩展，但 Python 客户端缺失；`embedding` 字段运行时退化成 `TEXT`；数据库 6 条切片 0 条有向量；维度 1024 与列 1536 冲突；所有失败被静默吞掉。
2. **Agent 有正确性缺陷**：选中的知识库范围不生效、迭代上限返回空、LangGraph 异常降级时消息被覆盖、前端流式结束答案消失。
3. **不可复现**：`requirements.txt` 停在一年前的版本，实际环境是 FastAPI 0.136 / OpenAI 2.41 / LangChain 1.x；旧切片 import 已不存在。
4. **没有评测**：所有 RAG 参数（500/50/0.7/top5）没有数据依据；测试只有 5 个单元测试。
5. **不可交付**：根 README 缺失、无迁移、无 Dockerfile/CI、无结构化日志、无备份演练。

### 0.3 数量

| 级别 | 数量 | 含义 |
|---|---|---|
| P0 | 12 | 阻断“可用/可信”，必须先修 |
| P1 | 17 | 阻断“生产可用”，W1–W5 修 |
| P2 | 11 | 质量与体验，W6–W8 修 |
| 合计 | **40** | 完整清单见 §3–§6 |

---

## 1. 审计方法与证据基线

### 1.1 静态检查

- 逐文件阅读 `backend/app/` 下 60+ 文件、`backend/scripts/`、`backend/tests/`、`frontend/src/`。
- 全仓搜索 `langchain`、`langgraph`、`pgvector`、`create_all`、`CREATE INDEX`、`test_token` 等关键词。
- 检查 `alembic/versions/`、根目录文件、Docker/CI 配置是否存在。

### 1.2 运行时检查（只读）

| 检查 | 命令/方式 | 结果 |
|---|---|---|
| Docker 容器 | `docker ps -a` | `kb-postgres-published`（pgvector 16-0.8.3）、`kb-redis`（redis:7-alpine）运行中 |
| PG 扩展 | `docker exec ... psql -c "select extname,extversion from pg_extension"` | `vector 0.8.3` |
| PG 列类型 | `pg_attribute` / `information_schema` | `document_chunks.embedding = vector(1536)` |
| PG 数据 | `select count(*), count(embedding)` | `6 / 0` |
| PG 索引 | `pg_indexes` | 仅 `document_chunks_pkey`、`ix_document_chunks_document_id` |
| MySQL 数据 | `mysql -N -e "select count(*) ..."` | 4 用户 / 5 知识库 / 4 文档 / 1 会话 / 4 消息 / 3 工具 |
| Python 依赖 | `importlib.metadata` | fastapi 0.136.3、sqlalchemy 2.0.50、openai 2.41.1、langgraph 1.2.4、langchain 1.3.7、langchain-text-splitters 1.1.2、langchain-core 1.4.4 |
| 缺失依赖 | `find_spec` | `pgvector`、`tiktoken`、`cryptography` 缺失 |
| 旧切片 import | 导入 `app.rag.text_splitter` | `_HAS_LANGCHAIN = False`（静默降级） |
| 运行时列类型 | `DocumentChunk.__table__.c.embedding.type` | `TEXT`（不是 `VECTOR`） |
| 连接 | SQLAlchemy async MySQL/PG、Redis、bcrypt | 均成功；bcrypt 有 passlib 兼容告警 |
| 后端 | `app.main` 导入 | 成功，34 条路由；服务未启动 |
| 工具链 | `docker --version`、`node -v` | Docker 29.4.3 / Compose v5.1.3、Node 24 / npm 11 |

### 1.3 本次审计的边界

- 未启动 uvicorn 做完整 HTTP 冒烟（D1 做）。
- 未打开浏览器验证前端（D1 做）。
- 未读取 `.env` 密钥值；只判断是否为空/占位。
- 未修改任何数据；数据库现状可作为修复前基线。

---

## 2. 运行时拓扑（当前真实形态）

```
┌────────────────────────────── Windows 主机 ──────────────────────────────┐
│                                                                          │
│  frontend (Vite 8 + React 19 + AntD 6)   :3000/5173                       │
│        │  HTTP/SSE                                                       │
│        ▼                                                                 │
│  backend (FastAPI + uvicorn)             :8000                            │
│        │                                                                 │
│        ├── MySQL 8.2（Windows 服务 MySQL82）:3306  → 业务数据             │
│        ├── PostgreSQL 16 + pgvector 0.8.3（Docker）:5432 → 切片/向量      │
│        │     container: kb-postgres-published                            │
│        │     image: ai-kb-postgres-pgvector:16-0.8.3                     │
│        │     volume: D:/PostgreSQL                                       │
│        └── Redis 7（Docker）:6379 → 缓存/限流                             │
│              container: kb-redis                                         │
│                                                                          │
│  外部：DeepSeek（LLM）+ SiliconFlow（BAAI/bge-m3, 1024 维）               │
└──────────────────────────────────────────────────────────────────────────┘
```

**关键认知**：`pgvector` 是“数据库扩展”，不是“Python 包”。当前只有前者，缺后者；两者缺一不可。

---

## 3. P0 问题（12 条，必须最先修）

### GAP-001 向量检索实际不可用：有扩展、缺客户端、零向量

**证据**
- Docker PG 已安装 `vector 0.8.3`（`pg_extension`）。
- `.venv` 中 `import pgvector` 失败；启动日志：`pgvector.asyncpg 未安装，Vector 类型不会被注册`。
- 运行时 `DocumentChunk.__table__.c.embedding.type` 为 **`TEXT`**（`backend/app/models/document.py:18-26` 的 `try/except ImportError` 降级）。
- 数据库：`document_chunks` 6 行，`count(embedding)=0`。
- `backend/app/repositories/document_repo.py:164` 使用 `DocumentChunk.embedding.cosine_distance(...)`；列是 `TEXT` 时该方法不存在，异常被 `:179-181` 捕获并 `return []`。

**影响**
- 知识库问答“看起来正常”，实际没有检索到任何文档。
- 前端/接口无法区分“没有相关内容”和“向量检索坏了”。

**复现**
```powershell
cd backend
..\.venv\Scripts\python.exe -c "from app.models.document import DocumentChunk; print(DocumentChunk.__table__.c.embedding.type)"
# 期望 VECTOR(1024)，实际 TEXT
```

**修复方案**
1. 安装 Python 客户端：`pip install pgvector`（写入 requirements）。
2. 确认 `from pgvector.asyncpg import register_vector` 可用；`database/session.py:52-71` 的连接事件能注册。
3. 确认 `DocumentChunk.embedding` 变为 `Vector(settings.EMBEDDING_DIMENSION)`。
4. 给已有 6 条切片补向量（脚本或重传）。
5. 删除/改写 `TEXT` 降级分支：生产路径缺 pgvector 应**启动失败**或显式告警，不允许静默降级。

**验收**
- `DocumentChunk.__table__.c.embedding.type` 显示 `VECTOR(1024)`。
- `select count(*), count(embedding) from document_chunks` 两列相等且 > 0。
- `scripts/prove_rag.py` 返回非空 top-k。

**对应周**：W1-D2。

---

### GAP-002 维度冲突：模型 1024 vs 列 1536

**证据**
- `backend/.env`：`EMBEDDING_MODEL_NAME=BAAI/bge-m3`、`EMBEDDING_DIMENSION=1024`、`EMBEDDING_API_BASE=https://api.siliconflow.cn/v1`。
- `backend/app/core/config.py:91` 默认 `EMBEDDING_DIMENSION=1536`。
- DB 列：`vector(1536)`。

**影响**
- 写入 1024 维向量会报 `expected 1536 dimensions, not 1024`。
- 异常被 `document_service.py:150-153` 吞掉，文档仍标 `completed` → 数据“成功但无向量”。

**修复方案**
1. 统一为 1024：`.env`、`config.py` 默认值、DB 列三处一致。
2. 迁移列（当前全 NULL，安全）：
   ```sql
   ALTER TABLE document_chunks
     ALTER COLUMN embedding TYPE vector(1024)
     USING NULL::vector(1024);
   ```
3. 启动时校验 `len(返回向量) == EMBEDDING_DIMENSION`，不一致直接报错。
4. 文档记录 `embedding_model`/`embedding_dim` 元数据，换模型时能识别需重建。

**验收**
- DB 列 `vector(1024)`；新增文档向量维度 = 1024。
- 故意把 `.env` 改成 1536，启动或上传时显式报错，而不是静默成功。

**对应周**：W1-D2。

---

### GAP-003 失败静默：上传仍 completed、检索返回空

**证据**
- `backend/app/services/document_service.py:150-153`：embedding 异常 → `logger.warning("向量生成失败（跳过）")`；`:155-156` 仍 `update_status(..., "completed")`。
- `backend/app/repositories/document_repo.py:179-181`：向量搜索异常 → `return []`。
- `backend/app/rag/retriever.py:97-99`：检索异常 → `return ""`。
- `backend/app/rag/vector_store.py:70-85`：直接透传空结果。
- `backend/app/services/chat_service.py:119` / `agent_service.py:437`：空上下文被当作“没检索到”，继续用通用知识回答。

**影响**
- 线上无法发现 RAG 故障；用户得到无依据回答；评测也无法定位。
- 这是“Demo 与生产”的分水岭：**可降级，但必须可观测、可区分**。

**修复方案**
1. 上传：embedding 失败 → `status=failed` + 错误信息写入 `extra_meta`；响应明确“向量生成失败”。
2. 检索：区分“无结果”和“检索失败”；失败抛 `AppException` 或返回结构化错误，SSE 推 `event: error`。
3. 指标：`rag_retrieval_total{status}`、`embedding_fail_total`、耗时直方图。
4. 缓存/限流可静默降级；**核心检索不允许静默**。

**验收**
- 断 embedding key 上传 → 文档 `failed`，前端可见。
- 停 PG 后问答 → 明确错误事件，不是“未找到”。
- 日志/指标能看到失败次数。

**对应周**：W1-D2（最小闭环）、W5-D25（指标）。

---

### GAP-004 没有 ANN 索引：全表扫描

**证据**
- `backend/app/repositories/document_repo.py:164-170`：`order_by(embedding.cosine_distance(query)) + limit(top_k)`。
- `pg_indexes` 只有主键和 `document_id` btree；全仓无 `CREATE INDEX ... hnsw/ivfflat`。
- `backend/scripts/init_db.py:41-48` 只 `create_all`，不建索引。
- `alembic/versions/` 为空。

**影响**
- 切片上万后每次检索逐行算余弦，延迟线性增长。
- `WHERE document_id IN (...)` 过滤与向量排序组合时，索引选择更差。

**修复方案**
1. 数据量 > 1 万后建 HNSW：
   ```sql
   CREATE INDEX idx_chunks_embedding_hnsw
     ON document_chunks USING hnsw (embedding vector_cosine_ops)
     WITH (m = 16, ef_construction = 64);
   ```
2. 检索时设置 `hnsw.ef_search`（按召回/延迟调）。
3. 讲清 IVFFlat（需训练、`lists`、数据量大才划算）vs HNSW（图索引、召回高、内存大）的取舍。
4. 后续把 `knowledge_base_id` 冗余到 chunks，支持单条 SQL 限定 KB。

**验收**
- `EXPLAIN (ANALYZE, BUFFERS)` 显示走 `idx_chunks_embedding_hnsw`。
- 1 万条切片下 p95 检索延迟有对比数据（建索引前/后）。

**对应周**：W2-D9。

---

### GAP-005 当前问题在 prompt 中重复注入

**证据**
- `backend/app/services/chat_service.py:306-310` 先保存用户消息。
- `:313` 调 `_get_context_messages(session_id)`，`:404-420` 读取最近 20 条（**已包含刚保存的当前消息**）。
- `:316` `build_messages(content, history, effective_system_prompt)` 又 append 一次当前 `content`。
- `agent_service.py:168-188` 同构。

**影响**
- 模型看到两遍同一问题；浪费 token；可能诱导重复回答或改变语气。
- 长会话下与“20 条截断”叠加，挤掉更早的上下文。

**修复方案**
- 先读历史（不含当前），再保存当前消息；或保存后读历史时排除最后一条 user。
- 统一封装 `build_context(session_id, current_content)`，chat 与 agent 复用。
- 加单测：历史中当前问题只出现一次。

**验收**
- 单测断言 messages 中当前内容出现次数 = 1。
- 抓包/日志显示 token 数下降。

**对应周**：W1-D5。

---

### GAP-006 Agent 检索忽略选中的知识库

**证据**
- `backend/app/services/agent_service.py:345-349`：`context["retriever"]` + `context["kb_ids"] = knowledge_base_ids`。
- `backend/app/agent/tools.py:339-348`：只读 `context.get("document_ids")`，**从未使用 `kb_ids`**。
- `agent_service.py:404-438` 的 `_retrieve_rag_context` 只用于 system prompt 注入，不约束工具调用。

**影响**
- 用户只选 A 库，Agent 调 `knowledge_retrieval` 时仍检索全库 → 跨库内容泄露/答非所问。
- 多租户场景是安全问题，不只是体验问题。

**修复方案**
1. 工具上下文增加 `kb_ids`，检索时把 kb 转成 `document_ids` 下推。
2. 更彻底：chunks 表冗余 `knowledge_base_id`，检索 SQL 直接 `WHERE knowledge_base_id IN (...)`。
3. 校验 KB 归属：属于当前用户才可检索；不属于则显式 403/跳过并记录。

**验收**
- 两个库分别放不同文档，选 A 问 B 的内容 → 检索结果只来自 A。
- 单测覆盖“选 A 不返回 B 的 chunk”。

**对应周**：W3-D16。

---

### GAP-007 Agent 达到迭代上限返回空回答

**证据**
- `backend/app/agent/graph.py:181-189`：`tool_calls` 存在但 `iteration >= max_iterations` → 返回 `end`。
- `:347-390` `_extract_result` 只找最后一条有 `content` 的 assistant 消息；最后一条是带 `tool_calls`、`content=None` 的 assistant → 最终 `result=""`。
- `agent_service.py:313-381` 的流式循环同样可能在 `max_iterations` 后没有最终文本。

**影响**
- 复杂问题达到上限时用户收到空回复；日志只有一句 warning。
- 评测会把这类样本算作失败但无法解释。

**修复方案**
1. 达到上限时显式返回：“已达最大工具调用轮数，以下是已获得的信息……”。
2. 或在结束前强制一次“不带 tools 的总结调用”。
3. `max_iterations` 读配置，不硬编码 10。
4. 加回归测试：模拟 10 轮 tool_calls → 有非空兜底文案。

**验收**
- 构造超限场景，最终回答非空且包含上限说明。
- 配置改 3 能生效。

**对应周**：W3-D16。

---

### GAP-008 AgentChat 流式结束后答案消失；无会话连续性

**证据**
- `frontend/src/pages/AgentChat.tsx:106`：URL 只拼 `content` 与 `kb_ids`，**没有 `session_id`**；每次发送都可能新建会话。
- `:127-140`：`onDone` 回调里使用闭包捕获的 `streamContent` 与 `currentToolCalls`（连接建立时是空值），然后 `setMessages` 追加空内容，并 `setStreamContent("")`。
- `backend/app/services/agent_service.py:313-395`：流式阶段一次性 `yield` 完整 token 事件，不是真流式；前端仍按流式展示。

**影响**
- 用户看到流式输出，结束后消息变空；工具调用记录丢失。
- 每次提问一个新会话，历史无法延续；会话列表被污染。

**修复方案**
1. `useRef` 保存最新 `streamContent`/`toolCalls`，`onDone` 读取 ref，而不是闭包 state。
2. 首次 `event: session` 记录 `session_id`，后续请求带上；或改为 POST 创建会话。
3. 后端 Agent 流式改为真正的 `chat_stream` + 工具阶段事件。
4. 前端从会话详情恢复历史。

**验收**
- 连续追问 3 轮，消息不消失、历史在、会话只有一个。
- 工具卡片在结束后仍可展开。

**对应周**：W4-D23（前端）、W3-D17（后端流式）。

---

### GAP-009 密钥与令牌安全

**证据**
- `backend/app/core/config.py:75` 默认 `JWT_SECRET_KEY="your-secret-key-change-in-production"`；`backend/.env` 仍是该占位符（实测 `settings.JWT_SECRET_KEY == 默认值`）。
- `backend/app/main.py:18-22` 非 DEBUG 才拒绝启动；DEBUG 只打印警告。
- `backend/test_token.txt` 存在（已 gitignore，但仍在工作区）。
- `backend/.env` 有真实 embedding key（本轮不打印）；`.env` 已 gitignore。
- Docker PG 使用 `POSTGRES_PASSWORD=your_pg_password`。

**影响**
- 知道默认密钥即可伪造任意用户/管理员的 access token。
- 密钥泄露会带来账单与数据风险。

**修复方案**
1. 生成随机 64 字节 secret 写入 `.env`；生产用密钥管理，不入库。
2. 删除 `test_token.txt`；清理历史（如曾提交）。
3. 轮换 embedding key；`.env.example` 只留占位。
4. 启动强校验：非 DEBUG 且默认值 → 拒绝启动；DEBUG 也建议警告+显眼日志。
5. CI 加 gitleaks。

**验收**
- 默认 secret 启动失败（或强告警）。
- 旧 token 无法再通过校验。
- 仓库无明文密钥。

**对应周**：W1-D1。

---

### GAP-010 环境不可复现

**证据**
- `backend/requirements.txt`：`fastapi==0.115.0`、`openai==1.50.0`、`langchain==0.3.0`、`langchain-community==0.3.0`、`langgraph==0.2.0`、`pgvector==0.4.2`。
- 实际 `.venv`：fastapi 0.136.3、openai 2.41.1、langchain 1.3.7、langgraph 1.2.4；`pgvector`、`cryptography`、`tiktoken` 缺失；`pytest`/`pytest-asyncio` 也未安装（`tests/` 里的 5 个测试当前跑不起来）；uvicorn 实际 0.49.0。
- `backend/app/rag/text_splitter.py:23-28` 仍 `from langchain.text_splitter import ...`；LangChain 1.x 已拆分到 `langchain-text-splitters`，实测 `_HAS_LANGCHAIN=False`，静默走简易切分。
- `requirements.txt` 中 `httpx` 重复两行；`langchain-community` 未被业务代码使用。
- Python 3.13 能跑，但 requirements 未声明版本。

**影响**
- 新机器 `pip install -r requirements.txt` 装不出当前可用环境。
- 同一份代码在不同机器行为不同（切片、向量、LLM 调用）。
- 面试被问“怎么保证环境一致”会答不上来。

**修复方案**
1. 以当前可用环境重新生成锁定依赖（`requirements.txt` + `constraints.txt`/`requirements.lock`）。
2. 补 `pgvector`、`cryptography`；`tiktoken` 按需；`tenacity` 显式声明（已装但未写）。
3. 移除未使用的 `langchain`/`langchain-community`，改用 `langchain-text-splitters>=1.1,<2`。
4. 增加 `pyproject.toml` + `ruff/mypy/pytest-cov`（W6）。
5. CI 中用 clean venv 执行 `pip install -r` + 启动导入检查。

**验收**
- 全新 venv 安装后 `python -c "import app.main"` 成功。
- `pip check` 无冲突。
- 切片走 `langchain_text_splitters`，不再降级。

**对应周**：W1-D3。

---

### GAP-011 没有数据库迁移

**证据**
- `backend/alembic/versions/` 为空。
- `backend/alembic/env.py:21-33` 只导入 `MySQLBase`；`engine_from_config` 是同步引擎；没有 PostgreSQL 的 `target_metadata`。
- 实际建表依赖 `backend/scripts/init_db.py:31-48` 的 `metadata.create_all`（只建不改）。
- `backend/reset_pg_table.py` 用 `DROP TABLE` 重建，属于开发脚本。

**影响**
- 线上无法安全演进 schema（加索引、改维度、加字段）。
- 双库中只有 MySQL 被 Alembic 看见，PG 变更无版本记录。
- 新人无法从零复现数据库结构。

**修复方案**
1. 给 MySQL 生成 baseline 迁移；给 PG 单独配置 `target_metadata=PostgreSQLBase.metadata` 或使用多 bind。
2. 把“维度 1536→1024”“HNSW 索引”写成迁移，而不是手写 SQL/reset 脚本。
3. 启动流程：`alembic upgrade head` → `seed`，禁止生产 `create_all`。
4. 保留 `init_db.py` 仅作本地开发。

**验收**
- 空 MySQL/PG 执行 `alembic upgrade head` 后表结构与模型一致。
- 维度/索引变更可通过迁移回滚。

**对应周**：W4-D20。

---

### GAP-012 没有任何评测

**证据**
- `backend/tests/` 仅 5 个文件：`test_agent_tools.py`、`test_agent_service.py`、`test_auth_rate_limit.py`、`test_config.py`、`test_exceptions.py`。
- 无 `data/eval_qa.jsonl`、无 `scripts/evaluate.py`、无 recall/MRR/忠实度指标。
- `VECTOR_CHUNK_SIZE=500`、`CHUNK_OVERLAP=50`、`TOP_K=5`、`THRESHOLD=0.7` 均无实验依据。

**影响**
- 无法回答“效果怎么样”；无法判断改动是变好还是变坏。
- 面试只能讲“跑通了”，讲不出数据。

**修复方案**
1. 建 25–30 条真实 QA（问题/期望文档/期望答案），放 `backend/data/eval_qa.jsonl`。
2. `scripts/evaluate.py` 计算 `recall@k`、`MRR`，LLM-as-judge 或人工抽检忠实度。
3. 每次改 chunk/top_k/rerank 跑一次，结果写 `docs/TRACKER.md`。
4. CI 加回归阈值（如 recall@5 不低于 baseline - 0.03）。

**验收**
- 一行命令输出 `recall@5=0.xx`。
- 有 baseline 与至少一次改进对比。
- README 指标区填真实数字。

**对应周**：W2-D11。

---

## 4. P1 问题（17 条，生产可用性）

### GAP-013 LangGraph 异常降级的手写循环会覆盖消息

**证据**
- `backend/app/agent/graph.py:317-344`：`current_state.update(result)`；而 `call_llm_node` 返回 `{"messages": [assistant_msg]}`，`execute_tool_node` 返回 `{"messages": tool_messages}`。
- `AgentState.messages` 的 `operator.add` reducer 只在 LangGraph 图内生效；普通 dict `update` 是**替换**。
- `_run_langgraph` 任意异常都会 `:312-314` 降级到该循环。

**影响**
- 降级后消息历史丢失（tool 消息缺少前置 assistant tool_calls），LLM API 大概率 400。
- 最终回答为空。

**修复方案**
- 抽一个 `append_messages()` 显式合并；或统一走 LangGraph，异常直接报错，不静默降级。
- 为降级路径写测试。

**验收**
- 强制让 LangGraph 抛异常，降级路径仍能得到正确回答/明确错误。

**对应周**：W3-D16。

---

### GAP-014 上传处理：同步阻塞、整文件入内存、路径穿越、无去重

**证据**
- `backend/app/services/document_service.py:89`：`content = await file_obj.read()` 一次读入内存（上限 50MB）。
- `:107-108`：`parser.parse()` 内部是同步 `PyPDF2/python-docx/open`，在 async 函数里直接跑，阻塞事件循环。
- `:319-324`：`unique_name = f"{uuid.uuid4().hex[:12]}_{filename}"`，`filename` 未净化；客户端可传 `..\..\x`，`Path` 拼接可能逃逸 `uploads/`。
- 无 sha256 去重；重复上传产生多份切片与向量。
- `html` 直接按纯文本读，标签会进切片。

**影响**
- 大 PDF 上传时整个服务卡住；并发上传互相拖慢。
- 目录穿越可写任意路径（安全）。
- 重复文档浪费 embedding 成本与存储。

**修复方案**
1. 文件名用 `Path(filename).name` + 白名单字符；保存后校验 resolved path 在 `uploads/` 下。
2. 上传只做“落盘 + 建 pending 记录”；解析/切片/embedding 放后台任务。
3. 计算 sha256，同 KB 重复拒绝或提示覆盖。
4. 分批 embedding（32/64），失败重试。
5. HTML 用解析器抽正文（BeautifulSoup/selectolax）或明确不支持。

**验收**
- 50MB PDF 上传接口 2s 内返回，后台进度可查。
- `..\..\evil.txt` 被拒。
- 同文件二次上传被识别。

**对应周**：W5-D27。

---

### GAP-015 双库一致性：删 KB 不清 PG 切片

**证据**
- `backend/app/services/knowledge_base_service.py:81-88`：只 `repo.delete(kb_id)`，ORM cascade 只删 MySQL 的 `documents`。
- `DocumentChunk` 无 FK（跨库），PG 切片不会被级联。
- `document_service.py:270-275` 删除单文档时会清 PG；但 KB 删除路径没有。

**影响**
- PG 留下孤儿切片，检索仍可能命中已删文档 → 越权/脏数据。
- 存储与向量索引膨胀。

**修复方案**
1. 删除 KB：先查文档 ID 列表 → 删 PG chunks → 删 MySQL（或事务后补偿）。
2. 加孤儿清扫脚本/定时任务（按 `document_id not in (...)`）。
3. 记录删除审计。

**验收**
- 删 KB 后 `document_chunks` 无对应 `document_id`。
- 孤儿清扫脚本可重复执行。

**对应周**：W4-D20。

---

### GAP-016 会话列表 N+1、updated_at 不更新、详情截断

**证据**
- `backend/app/services/chat_service.py:192-204`：每个会话单独 `count_by_session` → N+1。
- `backend/app/repositories/chat_repo.py:39` 按 `updated_at` 倒序；但发送消息只写 `chat_messages`，从不 touch `chat_sessions.updated_at`。
- `chat_repo.py:69-93` 会话详情 `limit=100` 默认，长会话静默截断。

**影响**
- 50 个会话 = 51 次 SQL；会话排序永远不变。
- 长会话历史缺失，前端以为消息丢了。

**修复方案**
1. 一次 `GROUP BY session_id` 聚合 count，或 `selectinload`。
2. 发消息时 `session.updated_at = utc_now()`。
3. 详情分页（`page/page_size`）或游标；明确上限。

**验收**
- 50 会话列表 SQL 数 ≤ 2。
- 发消息后会话排到最前。
- 长会话可翻页。

**对应周**：W4-D20。

---

### GAP-017 上下文固定截 20 条，token 预算未用

**证据**
- `backend/app/services/chat_service.py:404-420`、`agent_service.py:459-467`：`limit=20` 条。
- `backend/app/services/llm_service.py:211-220`：`count_tokens` 存在但全仓无调用。
- `LLM_MAX_TOKENS=4096`，但历史消息未按 token 预算裁剪。

**影响**
- 20 条长消息可能超过上下文窗口；20 条短消息又浪费预算。
- 无法解释“为什么是 20”。

**修复方案**
1. 从新到旧累加 token，保留 ≤ 预算（如模型窗口 60%）。
2. 系统提示 + 当前问题 + 历史 + 预留输出 token 一起算。
3. 超预算时截断最旧消息，并记录指标。

**验收**
- 构造超长历史，请求 tokens 不超预算。
- 单测覆盖预算边界。

**对应周**：W4-D20。

---

### GAP-018 Agent “流式”不是真流式

**证据**
- `backend/app/services/agent_service.py:371-377`：拿到完整 `content` 后一次性 `yield` 一个 `token` 事件。
- 对比 `chat_service.py:379-381`：真正逐 token。
- Agent 异常未统一捕获，SSE 可能直接断流。

**影响**
- 首 token 延迟 = 整段生成时间；用户感知卡顿。
- 断流时前端只看到连接关闭，没有错误事件。

**修复方案**
1. 工具阶段结束后，用 `chat_stream` 流式生成最终回答。
2. 统一 `event: error` + `done`，异常也落库部分回答。
3. 前端展示首 token 时间指标。

**验收**
- Agent 回答首 token 时间明显下降。
- 断网/异常有明确错误事件。

**对应周**：W3-D17。

---

### GAP-019 动态工具只有 schema，没有 executor

**证据**
- `backend/app/agent/tools.py:153-161`：`tool_map` 只含 3 个内建工具。
- `backend/app/repositories/agent_repo.py:84-101` 允许创建任意工具（存 schema）。
- `agent_service.py:81-97` 把数据库工具注册进 `_dynamic_tools`；LLM 调用后 `execute_tool` 返回“未知工具”。
- 前端 `ToolManage.tsx` 只有启用/禁用，没有创建入口。

**影响**
- 管理端“新增工具”是假功能；LLM 可能调用不存在的工具导致答非所问。
- 动态工具注册表是全局变量，多用户/多租户会串。

**修复方案**
1. 明确“仅展示”或实现 `executor` 注册（HTTP/函数映射 + 白名单）。
2. 未实现前，`get_tool_definitions` 过滤掉无 executor 的动态工具。
3. 前端隐藏/标注“仅 schema 演示”。

**验收**
- 无 executor 的工具不会出现在 LLM tools 中，或调用返回明确错误。
- 有 executor 的工具能真正执行。

**对应周**：W3-D15。

---

### GAP-020 SSE 用 GET query、token 存 localStorage、无吊销

**证据**
- `backend/app/routers/v1/chat.py:142-192`、`agent.py:80-136`：消息内容走 `?content=...`。
- `frontend/src/hooks/useSSE.ts:24`：从 `localStorage` 取 token；`client.ts` 同样。
- `backend/app/core/security.py` 无 token 黑名单/版本号；`auth_service.refresh_token` 不旋转 refresh。

**影响**
- 消息内容进 access log/代理日志；URL 长度受限；不适合长 prompt。
- XSS 可窃取 token；登出无法真正吊销；refresh 泄露可长期使用。

**修复方案**
1. 用 POST + `text/event-stream`（或 fetch stream）传消息体。
2. Access token 短、refresh 轮换 + 服务端记录 `jti`/版本；登出吊销。
3. 前端优先 httpOnly cookie（需 CSRF 策略）或至少内存存储 + 刷新恢复。
4. 不在 URL 放敏感内容。

**验收**
- 消息不出现在 URL/访问日志。
- 登出后旧 refresh 失效。
- 刷新一次后旧 refresh 不可复用。

**对应周**：W4-D21。

---

### GAP-021 限流是固定窗口、登录无失败锁定、Redis 故障重连

**证据**
- `backend/app/core/rate_limiter.py:22-25` 注释称“滑动窗口”；`:114-123` 实际是 `INCR` + 固定窗口 key（`int(time.time() // window)`）。
- `:108-110` Redis 不可用直接放行（fail-open）。
- `:42-51` `get_client()` 每次调用；`_connect` 失败后 `_available=False`，下次请求仍会重试连接（3s 超时）。
- `auth_service.login` 无失败计数/锁定。
- `routers/v1/__init__.py:59-69` 每个已认证请求都查 user 限流；中间件又做 IP/全局，存在重复。

**影响**
- 窗口交界可双倍放行；撞库无防护；Redis 故障时请求变慢。
- 面试被问“固定 vs 滑动”会翻车。

**修复方案**
1. 术语改对，或实现真正滑动窗口（ZSET/令牌桶）。
2. 登录失败 `fail:{username}` 计数，5 次锁 15 分钟。
3. Redis 不可用时快速失败/短路，不每次重连。
4. 合并重复限流层。

**验收**
- 压测窗口边界不出现双倍；5 次错误登录触发锁定；Redis 关闭时接口不额外卡 3s。

**对应周**：W4-D21。

---

### GAP-022 LLM 无超时/重试/成本统计；embedding 不分批

**证据**
- `backend/app/services/llm_service.py:24-33`：`AsyncOpenAI` 未传 `timeout`（SDK 默认较长）。
- `chat/chat_with_tools/chat_stream` 三个方法无重试。
- `backend/app/rag/embeddings.py:108-114`：一次 `embeddings.create(input=valid_texts)` 发全部切片。
- 无 usage/token/成本记录；`LLM_MAX_TOKENS` 只限制输出。

**影响**
- 上游 429/5xx/超时会直接失败；大文档 embedding 一次请求可能超限。
- 无法回答“每次问答成本多少”。

**修复方案**
1. `AsyncOpenAI(timeout=...)`；tenacity 重试 429/5xx/连接错误，指数退避+抖动。
2. embedding 分批（如 32/64），批间重试。
3. 记录 `prompt_tokens/completion_tokens/latency/model` 到日志/指标/消息 `extra_meta`。
4. 成本估算按模型单价。

**验收**
- 模拟 500/断网能自动重试成功。
- 100 切片文档不再一次性请求。
- 每次问答有 token/耗时/成本记录。

**对应周**：W5-D25。

---

### GAP-023 无结构化日志、健康检查不探活、DEBUG 输出 SQL

**证据**
- 仓库无 logging 配置；`backend/logs/` 为空；`main.py` 只有 print。
- `main.py:125-128` `/health` 只返回常量，不查 MySQL/PG/Redis。
- `database/session.py:25/42` `echo=settings.DEBUG`，DEBUG=True 时 SQL 与参数全部打印（含用户消息/切片内容）。
- 无 request_id、无耗时、无 LLM 调用埋点。

**影响**
- 线上排障无法把一条请求串起来；健康检查骗过 K8s。
- 日志泄漏用户内容，量大。

**修复方案**
1. `logging.config.dictConfig`：控制台 + 文件 + JSON 格式。
2. request_id 中间件（读/生成 `X-Request-ID`，写日志上下文）。
3. `/health` 探活 DB/Redis，返回分项状态。
4. DEBUG 关闭 SQL echo 或只对本地开启；敏感字段脱敏。

**验收**
- 一条请求的日志可用 request_id 串起。
- 停 PG 后 `/health` 返回 unhealthy。
- 生产日志无完整用户消息。

**对应周**：W5-D25。

---

### GAP-024 CORS 仅 3000、`.env` 依赖 CWD

**证据**
- `backend/app/core/config.py:13-16` 默认只允许 `http://localhost:3000`、`127.0.0.1:3000`；`backend/.env` 未覆盖。
- `frontend/vite.config.ts` 未配端口，Vite 默认 5173。
- `config.py:120-124` `env_file=".env"` 相对进程 CWD；从仓库根启动会读不到 `backend/.env`（实测从根读取时 embedding key 为空、模型变回 ada-002）。

**影响**
- 前端 5173 直接被浏览器 CORS 拦；从根目录启动后端会静默用默认配置。
- 面试问“配置怎么加载”会暴露。

**修复方案**
1. CORS 允许 5173（开发），生产用显式域名。
2. `env_file` 用绝对路径（`Path(__file__).resolve().parents[2] / ".env"`）。
3. README 明确 `cd backend`；加启动自检日志（模型/维度/base，不打印 key）。

**验收**
- 5173 前端可直连；从任意目录启动配置一致。

**对应周**：W1 临时绕行（3000），W4-D21 正式修。

---

### GAP-025 没有容器化/CI/备份

**证据**
- 根目录无 `Dockerfile`、`docker-compose.yml`、`.github/`、`Makefile`。
- 只有 PG/Redis 手工容器；MySQL 是 Windows 服务。
- `database-backups/` 有一个 PG dump，但无恢复脚本/演练。

**影响**
- 换机器部署靠记忆；环境漂移；无自动测试门禁。
- 数据丢失无恢复流程。

**修复方案**
- W7：后端/前端 Dockerfile、Compose、Nginx、CI、迁移、备份/恢复 runbook。
- 保留现有 PG 数据卷/绑定目录，先备份再切换。

**验收**
- fresh clone 一条命令起全栈；3 个故障演练通过。

**对应周**：W7。

---

### GAP-026 前端功能与显示缺陷

**证据**
- `AgentChat.tsx`：见 GAP-008；无 Markdown 渲染、无引用展示、无停止生成/重试。
- `Dashboard.tsx:20,52`：`docCount` 初始化为 0，从未请求 → “文档”卡片永远 0。
- `UserManage.tsx:39`：显示 `email`，但 `User` 模型/`UserResponse` 没有 email 字段。
- `Chat.tsx` 未使用 `updateSession`（API 存在但 UI 无重命名）。
- `useSSE.ts` 只按 `\n` 切分，不支持多行 `data:`；无事件 ID/重连。
- 组件中大量 `any`；无错误边界/加载骨架。

**影响**
- 功能“有 API 没入口”；数据展示错误；流式体验脆弱。

**修复方案**
- 修 Dashboard/UserManage；补会话重命名；Markdown + 引用；停止/重试；SSE 解析器健壮化；类型化。

**验收**
- 页面数据与 DB 一致；Agent 回答不消失；可停止生成。

**对应周**：W4-D23。

---

### GAP-027 测试只有 5 个单测

**证据**
- `backend/tests/` 5 个文件；`test_agent_service.py` 用 `object.__new__` 绕过构造；`test_auth_rate_limit.py` 用 `asyncio.run`。
- 无 `conftest.py`、无 TestClient、无数据库 fixture、无 RAG 评测。
- 根目录 `test_phase6.py`、`test_phase7.py` 是手工脚本，依赖真实 8000 端口。
- 当前 `.venv` 未安装 `pytest` / `pytest-asyncio`，所以这 5 个测试实际上无法执行（`pytest` 命令不存在）。

**影响**
- 改动无回归保护；CI 无法跑；面试说“有测试”会被追问细节。

**修复方案**
- pytest + pytest-asyncio + httpx AsyncClient；mock LLM/embedding；临时 SQLite/测试库；覆盖率 ≥60%（核心链路 ≥80%）。
- 手工脚本迁到 `scripts/` 并标记 integration。

**验收**
- `pytest` 本地/CI 全绿；覆盖率报告。

**对应周**：W5-D28。

---

### GAP-037 passlib 与 bcrypt 版本不兼容

**证据**
- 实测 `hash_password` 可用，但日志出现 `(trapped) error reading bcrypt version ... module 'bcrypt' has no attribute '__about__'`。
- `requirements.txt`：`passlib[bcrypt]==1.7.4`、`bcrypt>=4.1.0,<5.0.0`；实际 bcrypt 4.3.0。

**影响**
- 当前可登录，但 passlib 已停止维护，未来升级会直接坏；日志噪音。
- 面试问“密码哈希怎么选”会暴露依赖风险。

**修复方案**
- 短期：锁 `bcrypt<4.1` 或改用 `pwdlib[bcrypt]`/直接 `bcrypt` API。
- 中期：迁移哈希方案（bcrypt/argon2），保留旧哈希校验兼容。

**验收**
- 无告警；登录/注册测试通过；哈希格式可升级。

**对应周**：W4-D21。

---

### GAP-039 业务异常的 HTTP 状态码与 body code 不一致

**证据**
- `backend/app/core/exceptions.py:20-32`：`AppException` 的 `http_status_code` 默认 **400**。
- `backend/app/services/auth_service.py:48`：`raise AppException(code=401, message="用户名或密码错误")`，没有传 `http_status_code`。
- 实测：`POST /api/v1/auth/login`（不存在的用户）返回 **HTTP 400**，body 为 `{"code":401,...}`。
- 同类：`auth_service.py:54` 账号禁用（code=403）、`chat_service.py:221` 会话不存在（code=404）等也可能返回 400。
- 前端 Axios 拦截器按 HTTP 401 触发 refresh；语义不一致会让客户端/网关/监控误判。

**影响**
- 401/403/404 被统一映射成 400，REST 语义错误；客户端无法按状态码区分“未登录/无权限/不存在”。
- 监控告警、限流、审计按状态码统计会失真。

**修复方案**
1. `AppException` 在未显式传 `http_status_code` 时，默认取 `code`（或维护 `code → HTTP` 映射）。
2. 统一在异常处理器输出 `status_code=exc.http_status_code`，并补测试：登录失败 401、禁用 403、不存在 404、参数错误 422。
3. 前端按 body `code` 兼容一段时间，再切 HTTP 状态码。

**验收**
- 错误登录返回 HTTP 401；无权限 403；资源不存在 404。
- 单测覆盖 4 类异常。

**对应周**：W4-D21（也可在 W1-D4 顺手修）。

---

## 5. P2 问题（11 条，质量与体验）

### GAP-028 根 README 缺失，前端 README 是模板

- 证据：根目录无 `README.md`；`frontend/README.md` 是 Vite React 模板。
- 影响：新人与面试官无法快速理解项目；仓库显得未完成。
- 修复：本批交付根 README + 前端 README。
- 验收：新机器照 README 能起；链接有效。
- 周：本轮。

### GAP-029 根目录散落临时脚本与令牌文件

- 证据：`backend/test_phase6.py`、`test_phase7.py`、`reset_pg_table.py`、`check_pgvector.py`、`check_pg_ext.py`、`test_token.txt`。
- 影响：误执行 `reset_pg_table.py` 会丢切片；令牌文件有泄露风险。
- 修复：迁移到 `scripts/dev/` 并加警示；删除 token；加 README 说明。
- 验收：根目录只保留必要文件；危险脚本有确认提示。
- 周：W8。

### GAP-030 注释与实现不符

- 证据：`rate_limiter.py:22-25` 称滑动窗口，`:114-123` 是固定窗口；`chat_repo.py:25-27` 说“同时返回消息总数”，实际只返回 sessions。
- 影响：误导维护者；面试被追问会失分。
- 修复：改注释或改实现，二者一致。
- 验收：代码审查无“注释撒谎”。
- 周：W4。

### GAP-031 无 API 契约/错误码表/OpenAPI 描述

- 证据：路由有 `response_model`，但 `summary/description/examples` 少；无统一错误码文档；`/docs` 在生产默认开启。
- 影响：前端联调靠猜；对外集成困难。
- 修复：补 OpenAPI 描述/示例；错误码表；生产关闭 docs 或加保护。
- 验收：`/docs` 可读；错误码文档与实现一致。
- 周：W6。

### GAP-032 无软删除/审计日志

- 证据：删除是物理删除；无操作日志表。
- 影响：误删不可恢复；企业合规缺失。
- 修复：`deleted_at` 软删除或审计表（who/what/when/before）。
- 验收：删除可追溯/可恢复（按需求）。
- 周：W6。

### GAP-033 `model_name` 只记录不生效；无供应商 fallback

- 证据：`ChatSession.model_name` 存了，但 `LLMService` 始终用 `settings.LLM_MODEL_NAME`；无 fallback。
- 影响：无法按会话切模型；上游故障无备选。
- 修复：按会话/请求传 model；配置 provider 列表 + fallback。
- 验收：两会话可用不同模型；主模型 5xx 时自动切备。
- 周：W3。

### GAP-034 无 prompt 版本管理/注入防护

- 证据：system prompt 硬编码在 `chat_service.py:121-140`、`agent_service.py:440-457`；RAG 文档内容直接拼进 prompt。
- 影响：prompt 改动无法回溯；文档中的恶意指令可能被模型执行。
- 修复：prompt 模板文件/版本号；明确“文档是数据不是指令”；输出过滤。
- 验收：prompt 可版本化；注入样例不能越权。
- 周：W2。

### GAP-035 前端无 i18n/a11y/错误边界/前端测试

- 证据：中文硬编码；无 ErrorBoundary；无 vitest/Playwright；`any` 多。
- 影响：体验与可维护性；面试全栈岗位会问。
- 修复：常量抽离；ErrorBoundary；关键组件测试；渐进类型化。
- 验收：关键页面有测试；错误不白屏。
- 周：W6。

### GAP-036 无压测/性能基线、无反馈闭环、无 License

- 证据：无 locust/k6；无点赞/纠错；无 LICENSE。
- 影响：无法证明性能；无产品迭代信号；开源不合规。
- 修复：压测脚本 + 基线；反馈表/接口；License（待定）。
- 验收：有 p95/吞吐报告；反馈可入库。
- 周：W6/W8。

### GAP-038 Docker PG 默认口令、数据绑定主机目录、缺备份演练

- 证据：容器 env `POSTGRES_PASSWORD=your_pg_password`；bind `D:/PostgreSQL`；`database-backups/` 有 dump 但无恢复脚本。
- 影响：口令弱；数据与主机耦合；迁移/恢复无流程。
- 修复：强口令 + 密钥管理；Compose 命名卷或明确 bind；备份定时 + 恢复演练。
- 验收：恢复演练成功；口令非默认。
- 周：W7。

### GAP-040 启动日志 emoji 编码导致 Redis 误报“未连接”

- 证据：`backend/app/main.py:38-46` 把“连接 Redis”和“打印成功日志”放在同一个 `try` 里；成功分支 `:42` 打印 `✅`。Windows 控制台默认 GBK/cp936 无法编码 emoji，`print` 抛 `UnicodeEncodeError`，被 `:45-46` 的 `except Exception` 捕获，于是打印“未连接（缓存/限流降级）”。
- 实测：后端启动日志显示 Redis 未连接，但后端进程与 `127.0.0.1:6379` 存在 Established 连接；同参数直接 `ping` 成功；`lifespan` 在 UTF-8 输出下打印 `localhost:6379 ✅`。
- 影响：误报依赖故障，误导排障；缓存/限流实际上可用却被认为降级。
- 修复：日志改用 ASCII/无 emoji；连接检查与日志打印分开 try；统一 UTF-8 日志编码（W5 结构化日志一起做）。
- 验收：Windows 控制台启动日志正确显示 Redis 状态；断 Redis 时才是“未连接”。
- 周：W5（也可 W1 顺手修）。

---

## 6. 修复批次与依赖

| 批次 | 周 | 关闭的 GAP | 前置 |
|---|---|---|---|
| B0.5 基线门 | D1–D3 | 001/002/003/009/010（部分） | 无 |
| B1 核心正确性 | W1 | 005/006/007/008（部分）/024（绕行） | B0.5 |
| B2 RAG 质量 | W2 | 004/012/034 | B0.5 |
| B3 Agent | W3 | 013/018/019/033 | B1 |
| B4 工程化/前端 | W4 | 011/015/016/017/020/021/024/026/037/039 | B1 |
| B5 可靠性/测试 | W5 | 014/022/023/027/040 | B4 |
| B6 安全/性能/质量 | W6 | 030/031/032/035/036 | B5 |
| B7 部署 | W7 | 025/038 | B6 |
| B8 收尾 | W8 | 028（已在本轮）/029/036 | B7 |

**规则**：P0 未清零不加新功能；每个修复带测试/证据；README/TRACKER/架构图同步更新。

---

## 7. 暂不修复/延后项（明确取舍）

| 项 | 原因 | 何时做 |
|---|---|---|
| K8s/多区域/自动扩缩容 | 超出个人项目与当前岗位范围 | 工作后按需 |
| 微服务拆分 | 模块化单体更适合当前规模 | 数据/团队规模上来后 |
| 模型微调 | 成本高，RAG 尚未评测 | 有稳定数据后 |
| 多租户/SSO/计费 | 企业版能力，非面试主线 | 有余力 |
| GraphRAG/知识图谱 | 先做好向量+关键词混合 | W2 评估后 |
| 重写前端 UI | 当前够用，优先修正确性 | 不排期 |

---

## 8. 验收 checklist（修复完成后逐项勾）

- [ ] `DocumentChunk.embedding` 是 `VECTOR(1024)`，DB 列一致。
- [ ] `document_chunks` 向量数 = 切片数（新上传 + 存量补齐）。
- [ ] `prove_rag.py` 输出非空 top-k，含维度/模型/耗时。
- [ ] 知识库问答带引用；库外问题不硬答。
- [ ] HNSW 索引生效（EXPLAIN 证据）。
- [ ] 25+ QA 评测，recall@5 有 baseline 与改进数字。
- [ ] Agent 只检索选中 KB；上限有兜底；降级不丢消息。
- [ ] AgentChat 连续对话不丢答案、不新建会话。
- [ ] 当前问题只注入一次。
- [ ] 默认 JWT secret 已替换；`test_token.txt` 已删；key 已轮换。
- [ ] 空库 `alembic upgrade head` 可建 MySQL+PG。
- [ ] 删 KB 后 PG 无孤儿。
- [ ] 50 会话列表 SQL ≤ 2；updated_at 正确。
- [ ] 上下文按 token 预算裁剪。
- [ ] 上传异步/路径安全/去重。
- [ ] 日志有 request_id；/health 探活真实；DEBUG 不外泄 SQL。
- [ ] 测试 ≥30，覆盖率达标；CI 全绿。
- [ ] Docker Compose 一键起；3 个故障演练通过。
- [ ] README 状态表与真实一致；无假指标。

---

## 附录 A：关键代码锚点

| 主题 | 文件 |
|---|---|
| 配置/默认值 | `backend/app/core/config.py` |
| 双库引擎/会话/pgvector 注册 | `backend/app/database/session.py` |
| 文档模型/向量列 | `backend/app/models/document.py` |
| 上传/解析/切片/embedding | `backend/app/services/document_service.py` |
| 切片实现 | `backend/app/rag/text_splitter.py` |
| Embedding 调用 | `backend/app/rag/embeddings.py` |
| 向量检索 | `backend/app/repositories/document_repo.py:143-181` |
| Retriever | `backend/app/rag/retriever.py` |
| 聊天/SSE/上下文 | `backend/app/services/chat_service.py` |
| Agent 编排/流式 | `backend/app/services/agent_service.py` |
| LangGraph 图/降级 | `backend/app/agent/graph.py` |
| 工具定义/执行 | `backend/app/agent/tools.py` |
| 限流/缓存/安全 | `backend/app/core/{rate_limiter,cache,security}.py` |
| 路由 | `backend/app/routers/v1/*.py` |
| 前端 SSE/页面 | `frontend/src/hooks/useSSE.ts`、`frontend/src/pages/*.tsx` |

## 附录 B：本次审计用到的只读命令

```powershell
# Docker 与 PG
docker ps -a
docker exec kb-postgres-published psql -U postgres -d ai_kb_vector -c "select extname, extversion from pg_extension;"
docker exec kb-postgres-published psql -U postgres -d ai_kb_vector -c "select count(*), count(embedding) from document_chunks;"
docker exec kb-postgres-published psql -U postgres -d ai_kb_vector -c "select format_type(atttypid, atttypmod) from pg_attribute where attrelid='document_chunks'::regclass and attname='embedding';"

# Python 环境
cd backend
..\.venv\Scripts\python.exe -c "from app.models.document import DocumentChunk; print(DocumentChunk.__table__.c.embedding.type)"
..\.venv\Scripts\python.exe -c "import langchain_text_splitters; print('ok')"

# MySQL（只读）
mysql -N -e "select count(*) from users; select count(*) from documents;"
```

> 所有命令均为只读；生产/真实数据上执行前请先备份。
