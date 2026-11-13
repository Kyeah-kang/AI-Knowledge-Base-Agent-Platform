# TRACKER.md — 进度、证据与复盘台账

> 配套：[README](../README.md) · [架构](ARCHITECTURE.md) · [课程](CURRICULUM.md) · [差距审计](GAP_ANALYSIS.md) · [企业级复核](ENTERPRISE_GAP_REVIEW.md) · [面试题库](INTERVIEW.md)
> 规则：**没有证据 = 没完成。** 每天结束更新本文件；每周 Gate 后做一次复盘。
> 状态：⬜ 未开始 · 🟨 进行中 · ✅ 完成 · ⛔ 阻塞

---

## 1. 基线快照（2026-10-23，只读审计）

| 项 | 实测 | 备注 |
|---|---|---|
| MySQL | Windows 服务 `MySQL82`，3306 | 4 用户 / 5 知识库 / 4 文档 / 1 会话 / 4 消息 / 3 工具 |
| PostgreSQL | Docker `kb-postgres-published`，pgvector 0.8.3，5432 | `document_chunks` 6 行，**0 行有 embedding**；列 `vector(1536)` |
| Redis | Docker `kb-redis`，6379 | 可用 |
| 后端 | 未启动 | `app.main` 可导入，34 路由 |
| 前端 | 依赖已装 | Vite 默认 5173；CORS 仅 3000 |
| Python | 3.13 | fastapi 0.136.3 / sqlalchemy 2.0.50 / openai 2.41.1 / langgraph 1.2.4 / langchain 1.3.7 / langchain-text-splitters 1.1.2 |
| 缺失 | `pgvector`、`tiktoken`、`cryptography` | `pgvector` 是 P0 |
| 切片 | 旧 `langchain.text_splitter` 失效 | 静默降级为简易切分 |
| 测试 | 5 个单测文件 | 当前 venv 未装 pytest/pytest-asyncio，暂不可执行 |
| 文档 | 无根 README；前端 README 是模板 | 本轮补齐 |

---

## 2. Stage 0 冒烟表（D1–D3）

### D1 非 RAG 冒烟

| # | 步骤 | 命令/操作 | 期望 | 实际 | 证据 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 数据服务 | `docker ps` + `Get-Service MySQL82` | 三个服务可用 | MySQL82 Running；`kb-postgres-published`、`kb-redis` 均 `Up 2 hours` | `Get-Service` + `docker ps`（见注 ①） | ✅ |
| 2 | 后端启动 | `cd backend; ..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000` | 8000 可访问 | pid 195304 监听 8000；`/health` → `{"status":"healthy","version":"0.1.0"}`。**偏差：实际未带 `--reload`** | `Get-CimInstance Win32_Process` 命令行 + `/health` | ✅ |
| 3 | OpenAPI | 打开 `http://localhost:8000/docs` | 34 路由 | `/docs` 200；`len(app.routes)=34`（与基线一致），`/openapi.json` 30 个操作 | `python -c "from app.main import app; print(len(app.routes))"` → 34 | ✅ |
| 4 | 前端启动 | `cd frontend; npm run dev -- --port 3000` | 页面可打开 | pid 179052 `vite --port 3000`；`GET /` 200；/login、/register、/dashboard、/chat、/agent、/knowledge-bases、/profile 均正常渲染 | `Get-NetTCPConnection -LocalPort 3000` + 截图 a~g | ✅ |
| 5 | 注册/登录 | 新用户名注册并登录 | 拿到 token、进入 dashboard | 注册 `kangkang` → register **200/1050ms** → 自动登录 → `/dashboard`（user id=7，提示“登录成功”）；既有用户登录 **200/545ms** | 截图 `d1-05-a`~`d1-05-i`、[d1-05-timing.txt](evidence/w1-smoke/d1-05-timing.txt) | ✅ |
| 6 | 知识库 | 新建一个 KB | 列表出现 | 创建成功：`POST /knowledge-bases` **200/109ms**，紧接着自动 `GET` 列表 **200/69ms**；列表出现 ID=8、文档数 0、提示“创建成功”、共 1 个 | 截图 `d1-06-a`、`d1-06-b`、[d1-06-kb.txt](evidence/w1-smoke/d1-06-kb.txt) | ✅ |
| 7 | 上传 | 上传一个 txt | 文档 completed、切片数 >0 | **500 / 0 B**（两次）。已实测定位：解析 OK(1807 字) → 切片 OK(5 块) → MySQL 建记录 OK → **PG 写切片炸**：`column "embedding" is of type vector but expression is of type character varying`。根因=未装 pgvector 客户端导致 ORM 把 embedding 降级为 Text，与 DB 的 `vector(1536)` 不兼容（即 B-001/B-002） | 截图 `d1-07-a-upload-500.png`、[d1-07-upload.txt](evidence/w1-smoke/d1-07-upload.txt) | ⛔ |
| 8 | 普通聊天 | 发“你好” | 流式返回 | 通过：`POST /chat/sessions` **200/1.86s** → 会话 #8 → `GET /sessions/8` 200 → `messages/stream` **200 / 1.0 kB / 2.69s**，AI 回复“你好！很高兴见到你……”**逐字输出且未消失**；过程中触发 `401 → refresh 200/15ms → 重试 200` 的自动续期链路 | 截图 `d1-08-a-chat-stream.png` | ✅ |
| 9 | Agent 计算器 | 问“计算 1024*768” | 返回 786432，有工具卡片 | **异常**：/agent 发“你好” → `stream?content=...` **200 但仅 428 B / 4.89s**，页面**完全没有回复**；重试一次 200/428B/2.19s。尚未发“计算 1024*768” | 截图 `d1-09-a-agent-no-reply.png`；SSE 响应原文待补 | ⛔ |
| 10 | 记录异常 | 记录所有报错/耗时 | 写入本表 | 完成：证据 15 张图 + 4 个 txt 落在 `docs/evidence/w1-smoke/`；新增缺陷 B-011~B-016；客观耗时全部入账 | 本表 + 遗留问题池 | ✅ |

> 注 ①（2026-10-23 实测）：`MySQL82` Running；`docker ps` → `kb-redis`、`kb-postgres-published` 均 `Up 2 hours`，6379/5432 已发布。
> 注 ②：第 5 行是**两段链路分开验**——“注册即登录”（register 直接返回 token）与“既有用户登录”各一次，Network 各出现一次 200。
> 注 ③：D1 只做非 RAG 冒烟；上传后检索不到内容属 D2 范围，不算本表失败。
> 注 ④：证据目录 [docs/evidence/w1-smoke/](evidence/w1-smoke/)；客观耗时见 `d1-05-timing.txt`，主观秒表数字与 F5 刷新实测待补。

### D2 RAG 闭环

| # | 步骤 | 期望 | 实际 | 证据 | 状态 |
|---|---|---|---|---|---|
| 1 | 装 `pgvector` | `DocumentChunk.__table__.c.embedding.type` = `VECTOR(1024)` | **✅ 完成**：`pip install --isolated pgvector==0.4.2` → 落在 `.venv\Lib\site-packages`；`_HAS_PGVECTOR=True`、`embedding.type=VECTOR(1024)`、`register_vector` 可导入、`pip check` 干净。踩坑：用户级 `pip.ini` 的 `target` 把包送到 `D:\pip_global_libs`（不在 sys.path），首装"成功"但 import 失败 → 加 `--isolated` 解决（遗留 #13） | `python -c "from importlib.metadata import version; print(version('pgvector'))"` → 0.4.2；`embedding.type` → VECTOR(1024) | ✅ |
| 2 | 迁移列 | DB 列 `vector(1024)` | **✅ 完成**：`ALTER TABLE ... ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024)` → `ALTER TABLE`；迁移前 `format_type` 为 `vector(1536)`、`count(*)=6 / count(embedding)=0`；迁移后 `vector(1024)`、`6 rows / 0 with_vec`、`ORM = VECTOR(1024)`。备份：[d2/document_chunks_before_migration.sql](evidence/d2/document_chunks_before_migration.sql)；重启后 `pgvector.asyncpg 未安装` 警告消失 | psql 输出 + `DocumentChunk.__table__.c.embedding.type` | ✅ |
| 3 | 补向量 | `count(*)=count(embedding)` 且 >0 | | | ⬜ |
| 4 | `prove_rag` | 输出模型/维度/top-k/耗时 | | | ⬜ |
| 5 | 知识库问答 | 返回内容且带上下文 | | | ⬜ |
| 6 | 失败演示 | 断 key 上传 → `failed` | | | ⬜ |

### D3 切片与架构

| # | 步骤 | 期望 | 实际 | 证据 | 状态 |
|---|---|---|---|---|---|
| 1 | 换 `langchain-text-splitters` | `_HAS_LANGCHAIN=True` 或不再降级 | | | ⬜ |
| 2 | 中文分隔符 | 切片边界合理 | | | ⬜ |
| 3 | Markdown 标题 | 元数据含标题 | | | ⬜ |
| 4 | 新旧对比 | 块数/长度/边界表 | | | ⬜ |
| 5 | 三张图 | 组件/上传时序/双库 | | | ⬜ |

---

## 3. 每日记录

> 每天一行；详细笔记可链到 `docs/notes/Dxx.md`（可选）。

| 天 | 日期 | 主题 | 状态 | 我改了什么 | 为什么 | 证据 | 卡点/遗留 | 面试题 |
|---|---|---|---|---|---|---|---|---|
| D1 | 2026-10-23 | 基线冒烟 | 🟨 | 未改任何业务代码（只做观测、定位与记录） | Stage 0 纪律：只修阻断、不重构；用户明确选择“不装 pgvector、上传转 D2” | `docs/evidence/w1-smoke/`（15 张截图 + `d1-05-timing.txt`/`d1-06-kb.txt`/`d1-07-upload.txt`/`d1-smoke.txt`）；`/health` 200；`len(app.routes)=34`；register 200/1050ms；login 200/545ms；建库 200/109ms；chat stream 200/1.0kB/2.69s | 第 7 行上传 ⛔（B-013，转 D2）；第 9 行 Agent ⛔（B-015，转 W3）；F5 实测未截；`sessions`/`tools` 接口 1.7~2.1s 偏慢 | 注册即登录的失败面？CORS 预检怎么过？401→refresh→retry 链路？ |
| D2 | | RAG 闭环 | ⬜ | | | | | |
| D3 | | 切片+架构 | ⬜ | | | | | |
| D4 | | 认证 | ⬜ | | | | | |
| D5 | | 聊天/SSE | ⬜ | | | | | |
| D6 | | Gate 1 | ⬜ | | | | | |
| D7 | | 切片实验 | ⬜ | | | | | |
| D8 | | Embedding | ⬜ | | | | | |
| D9 | | pgvector/HNSW | ⬜ | | | | | |
| D10 | | 检索/引用 | ⬜ | | | | | |
| D11 | | 评测集 | ⬜ | | | | | |
| D12 | | Gate 2 | ⬜ | | | | | |
| D13 | | Agent 审计 | ⬜ | | | | | |
| D14 | | LangGraph | ⬜ | | | | | |
| D15 | | 工具系统 | ⬜ | | | | | |
| D16 | | Agent 修复 | ⬜ | | | | | |
| D17 | | 真流式 | ⬜ | | | | | |
| D18 | | Gate 3 | ⬜ | | | | | |
| D19 | | FastAPI | ⬜ | | | | | |
| D20 | | SQLAlchemy/迁移 | ⬜ | | | | | |
| D21 | | 安全 | ⬜ | | | | | |
| D22 | | Redis | ⬜ | | | | | |
| D23 | | 前端 | ⬜ | | | | | |
| D24 | | Gate 4 | ⬜ | | | | | |
| D25 | | 日志/成本 | ⬜ | | | | | |
| D26 | | 韧性 | ⬜ | | | | | |
| D27 | | 异步上传 | ⬜ | | | | | |
| D28 | | 测试 | ⬜ | | | | | |
| D29 | | 评测/CI | ⬜ | | | | | |
| D30 | | Gate 5 | ⬜ | | | | | |
| D31 | | 安全复审 | ⬜ | | | | | |
| D32 | | API 设计 | ⬜ | | | | | |
| D33 | | 性能 | ⬜ | | | | | |
| D34 | | 质量门禁 | ⬜ | | | | | |
| D35 | | 文档同步 | ⬜ | | | | | |
| D36 | | Gate 6 | ⬜ | | | | | |
| D37 | | Dockerfile | ⬜ | | | | | |
| D38 | | Compose | ⬜ | | | | | |
| D39 | | Nginx/SSE | ⬜ | | | | | |
| D40 | | CI/CD | ⬜ | | | | | |
| D41 | | 可观测/备份 | ⬜ | | | | | |
| D42 | | Gate 7 | ⬜ | | | | | |
| D43 | | 叙事/简历 | ⬜ | | | | | |
| D44 | | 八股一 | ⬜ | | | | | |
| D45 | | AI 专项 | ⬜ | | | | | |
| D46 | | 系统设计 | ⬜ | | | | | |
| D47 | | 全真模拟 | ⬜ | | | | | |
| D48 | | 终验 | ⬜ | | | | | |

---

### D1 会话复盘（2026-10-23）

**完成**
- 全栈基线建立：数据服务 / 后端 34 路由 / 前端 7 页 / 注册 / 登录 / 建库 / 普通聊天 全部跑通并有证据。
- 冒烟表 10 行中 **8 行通过（1~6、8、10）**，2 行明确阻塞并定性（7 上传、9 Agent）。
- 新增缺陷 6 条（B-011~B-016），全部带 `file:line`；新增遗留 7 条（#6~#12）。

**证据**
- 目录：[docs/evidence/w1-smoke/](evidence/w1-smoke/)（15 张截图 + 4 份记录）
- 命令：`Get-Service MySQL82`、`docker ps`、`GET /health`、`len(app.routes)=34`、`python -c` 复现解析/切片/写库
- 关键数字：register 200/1050ms、login 200/545ms、建库 200/109ms、chat stream 200/1.0kB/2.69s、refresh 200/15ms

**未完成/卡点**
- 上传 500（B-013）：根因=未装 pgvector 客户端导致 ORM 将 embedding 降级为 Text，与 DB `vector(1536)` 冲突 → D2 首步修。
- Agent 无回复（B-015）：SSE 只到 `event: session` 就断，无 token/error/done → W3 修。
- F5 刷新后仍登录：只有代码证据（localStorage + `authStore.init()`），缺实测截图。

**能讲的 3 个点**
1. 为什么前端只能 3000 不能 5173（CORS 白名单 + 预检），以及后端为什么必须从 `backend/` 启动（`.env` 与 `uploads/` 都按 CWD 解析——今天用孤儿文件证明了 CWD）。
2. `401 → refresh → 重试原请求` 的拦截器链：`client.ts:24-56` 写、`client.ts:37` 发刷新、`client.ts:44` 重放请求，今天在 Network 里一次性观测到。
3. 同一个流式需求两种前端写法：`Chat.tsx:139-151` 用 `appendToLastMessage`（通），`AgentChat.tsx:127-140` 在 `onDone` 里读闭包 `streamContent`（答案会丢，B-007）。

**下次第一件事**
- D2：`pip install pgvector` → 校验 `DocumentChunk.__table__.c.embedding.type` 为 `VECTOR(1024)` → 迁移列（`vector(1536)`→`vector(1024)`，先备份）→ 给 6 条切片补向量 → 写 `scripts/prove_rag.py` → 回填 D1 第 7 行。

---

## 4. 每周 Gate 记录

| 周 | 日期 | 三图 | 口述 | 代码定位 | 证据 | 追问得分 | 结论 | 下周风险 |
|---|---|---|---|---|---|---|---|---|
| W1 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W2 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W3 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W4 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W5 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W6 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W7 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |
| W8 | | ⬜ | ⬜ | ⬜ | ⬜ | /10 | | |

---

## 5. 评测指标（W2 起填）

### 5.1 检索

| 日期 | 数据集 | chunk | top_k | 阈值 | HNSW | recall@5 | MRR | 备注 |
|---|---|---|---|---|---|---|---|---|
| baseline | 25 条 | 500/50 | 5 | 0.7 | 否 | | | 修复前 |
| | | | | | | | | |

### 5.2 回答质量

| 日期 | 样本 | 忠实度 | 相关性 | 引用覆盖 | 评分方式 | 备注 |
|---|---|---|---|---|---|---|
| | 10 | | | | 人工/LLM judge | |

### 5.3 性能/成本

| 场景 | 首 token | p95 | 平均 tokens | 单次成本 | 备注 |
|---|---|---|---|---|---|
| 普通聊天 | | | | | |
| RAG 问答 | | | | | |
| Agent 1 工具 | | | | | |

---

## 6. Bug 板

| ID | 现象 | 影响 | 定位（file:line） | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| B-001 | RAG 0 向量 | 知识库问答无效 | `document_service.py:136-156` | D2：pgvector + 列迁移；B2：`scripts/backfill_embeddings.py`（幂等/分批/维度校验） | D2 表；B2 E2E `count(*)=2, count(embedding)=2` | ✅ |
| B-002 | 维度 1536 vs 1024 | 写入失败 | `config.py:91` / DB | D2：`ALTER COLUMN embedding TYPE vector(1024)`；B2：`.env.example` 与 config 默认值统一 1024 | D2 迁移记录；`test_embedding_dimension_matches_orm_column` | ✅ |
| B-003 | 检索异常静默 | 无法发现故障 | `document_repo.py:179-181` | P0-1：`retriever._search` 失败抛 `RetrievalError(503)`；空结果正常返回 | `test_p0_1_failure_visibility.py`（16 条） | ✅ |
| B-004 | 当前问题重复 | token 浪费/答偏 | `chat_service.py:305-316` | B1：`message_context.load_history(exclude_id=)` 单一入口（chat/agent 共用） | `test_b1_agent_and_context.py` 4 条（chat/stream/agent/load_history） | ✅ |
| B-005 | Agent 越库检索 | 范围失效 | `tools.py:339-348` | B2：`_resolve_document_ids()` 把知识库展开为文档 ID；拿不到范围不提供 retriever | `test_resolve_document_ids_*`、`test_knowledge_retrieval_tool_refuses_without_scope` + E2E（ZZZ-42 有 / YYY-99 无） | ✅ |
| B-006 | 迭代上限空答 | 用户体验差 | `graph.py:181-189` | B1：`_ensure_final_answer` + 强制无工具总结 + 兜底文案 + 补齐悬空 tool_calls | `test_manual_loop_falls_back_when_iterations_exhausted`、`test_summarize_returns_readable_fallback_when_llm_fails` | ✅ |
| B-007 | Agent 答案消失 | 功能不可用 | `AgentChat.tsx:127-140` | B1：`useRef` 保存流式缓冲 + URL 带 `session_id` + `?session_id=` 恢复历史 + 中断保留部分输出 | E2E：两轮同会话、角色 `user/assistant/user/assistant`；`build` + `oxlint` 通过 | ✅ |
| B-008 | 无迁移 | 无法演进 | `alembic/versions` | | | ⬜ |
| B-009 | 401/403/404 被映射成 400 | 客户端/监控误判 | `exceptions.py:20-32` | B1：未传 `http_status_code` 时默认取 `code`；auth 5 处补显式值；**同时修 N-3**（依赖层吞异常） | 9 个参数化用例 + E2E（401/404/400） | ✅ |
| B-010 | Redis 实际已连但日志误报 | 排障误导 | `main.py:38-46` | 随 P0-1：启动日志去 emoji（Windows cp936 编码不再抛异常） | `main.py:119` 注释 + 启动日志实测 | ✅ |
| B-011 | Agent 发消息后页面无任何回复（D1 实测：`stream` 200/428B，无内容渲染） | 功能不可用/静默失败 | **已进一步定位见 B-015**：SSE 只到 `event: session` 就断，`AgentChat.tsx:141-144` 的 onError 也未被触发（因为没有 error 帧） | B1：根因=N-1（工具重名→上游 400）+ P0-1 的 `event: error` 帧 + 前端 onError 接线 | E2E：Agent 流式收到 token 并落库；`d1-09-*` 不复现 | ✅ |
| B-012 | SSE 解析 `currentEvent` 在 `while` 内重置（跨 chunk 会丢事件名） | 弱网/慢流下丢 token | `useSSE.ts:47`（应为函数级状态） | | 待补 | ⬜ |
| B-013 | 上传必 500：ORM embedding 降级为 Text 与 DB `vector(1536)` 冲突 | 上传功能完全不可用 | `models/document.py:120-129` + `document_repo.py:106`；报错 `DatatypeMismatchError` | D2 第 1-2 步已完成（装 pgvector + 迁移 1024 维） | D2 表：`embedding.type=VECTOR(1024)`、`pip check` 干净、迁移前备份 [d1-07-upload.txt](evidence/w1-smoke/d1-07-upload.txt) | ✅ |
| B-014 | 上传失败后文件已落盘但 DB 回滚，产生孤儿文件；且 500 响应体在浏览器为 0 B（用户看不到原因） | 磁盘泄漏 + 静默失败 | `document_service.py:94`（先存盘）与事务提交顺序；`exceptions.py:101-111` 未生效待查 | | 待补 | ⬜ |
| B-015 | Agent SSE 只收到 `event: session` 一帧就结束（无 token / 无 error / 无 done） | 功能不可用且无报错 | 候选：`agent_service.py:236-393` 的生成器在流式响应已开始后抛异常，全局处理器管不到 | B1：实际根因是 N-1 工具重名（上游全量 400）+ N-3 依赖吞异常；SSE 外层包装保证任何异常都发 `error` 帧 | E2E：P0-5 两轮流式均收到 token 帧，会话 2/2 | ✅ |
| B-016 | 会话列表 message_count 不更新（聊天后仍显示 0 条消息） | 信息不准/误导 | 前端已重拉（`Chat.tsx:149`）→ 疑后端计数未维护 | B2：`count_by_sessions()` 一条 `GROUP BY` + 发消息 `touch(updated_at)` | `test_list_sessions_uses_one_batch_count` + E2E（发消息后排序与计数正确） | ✅ |
| B-017 | `EmbeddingService.is_available` 只判断 API Key 非空，不探测有效性；实际调用 402 余额不足 → 上传仍报 succeeded、向量为 0 | RAG 静默失效，"看似成功" | `embeddings.py:41-42`；失败被 `document_service.py:150-151` 吞成 warning | 应改为启动/首次调用做健康探测并显式置 failed | 探测输出：`402 - Sorry, your account balance is insufficient` | ⬜ |
| B-018 | SiliconFlow 账户余额不足（402）→ embedding 完全不可用 | D2 第 3 步阻塞 | 外部账务 | 待定：充值 / 本地 bge-m3 / 换 provider | 见探测输出 | ⛔ |

> **2026-10-29 校正**：B-001/002/003/004/005/006/007/009/010/011/013/015/016 已关闭（D2、P0-1、B1、B2 各批）；剩余 B-008（迁移）、B-012（SSE 解析）、B-014（孤儿文件/500 空响应体待复核）、B-017（embedding 可用性探测）、B-018（外部余额）。逐项 before/after 与学习路线见 [B1 阶段总结报告](B1_STAGE_REPORT.md)。
>
> 新增 bug 用 B-0xx 编号；修复后把“测试”列填上测试名/命令。

---

## 7. 面试题掌握度

| 主题 | 题数 | 已能讲 | 需复习 | 备注 |
|---|---|---|---|---|
| Python/async | 8 | | | |
| FastAPI/HTTP | 8 | | | |
| MySQL/SQLAlchemy | 8 | | | |
| Redis/限流 | 7 | | | |
| LLM 基础 | 8 | | | |
| RAG | 14 | | | |
| Agent/LangGraph | 9 | | | |
| 安全 | 8 | | | |
| 部署/运维 | 8 | | | |
| 项目/行为 | 10 | | | |

标准：能不看稿讲 3 分钟 + 能指代码 + 能答 2 层追问 = 已掌握。

---

## 8. 遗留问题池

| # | 问题 | 来源 | 优先级 | 计划解决 | 状态 |
|---|---|---|---|---|---|
| 1 | 混合检索/rerank 是否值得做 | W2 | P2 | W2 评估 | ⬜ |
| 2 | 多租户/共享 KB 要不要做 | 设计 | P2 | 待定 | ⬜ |
| 3 | Agent 是否要 checkpointer | W3 | P1 | W3 | ⬜ |
| 4 | 前端是否换 Markdown 渲染库 | W4 | P2 | W4 | ⬜ |
| 5 | License 选什么 | 收尾 | P2 | W8 | ⬜ |
| 6 | `chat/sessions` 空用户即 2.14s、`agent/tools` 1.77s（D1 基线） | D1 冒烟 | P1 | W4（N+1/串行查询） | ⬜ |
| 7 | antd `Space`/`List` 弃用告警（`Login.tsx:44`、`Dashboard.tsx:68`） | D1 Console | P2 | 前端改造时随版本升级处理 | ⬜ |
| 8 | 刷新后保持登录只有代码证据，缺实测截图 | D1 | P2 | 下次会话补 1 张 F5 截图 | ⬜ |
| 9 | 后端当前以 `--log-level debug` 且未带 `--reload` 运行（与 PLAN 命令不一致） | D1 启动 | P2 | 下次重启按 PLAN 命令执行。**CWD 已确认=backend/**（上传文件落到 `backend/uploads/7/8/`） | 🟨 |
| 10 | 创建时间显示比本地早 8 小时（存 UTC、前端按本地解析） | D1-06 | P2 | W4 时区统一时修：`KnowledgeBaseList.tsx:83` + `knowledge_base.py:36` | ⬜ 已坐实 |
| 11 | 聊天会话侧栏一直显示「0 条消息」，聊天结束后不更新 | D1-08 | P2 | 查后端 message_count 维护时机（前端 `Chat.tsx:149` 已在 onDone 重拉列表） | ⬜ 待验证 |
| 12 | 未选会话时输入框禁用，但空状态提示太弱，用户以为坏了 | D1-08 | P2 | W4 前端改造（空状态加主按钮引导） | ⬜ |
| 13 | 用户级 `C:\Users\10767\AppData\Roaming\pip\pip.ini` 设了 `target=D:\pip_global_libs`，导致所有 `pip install` 都不进 venv 的 site-packages（该目录不在 `sys.path`）→ 安装"成功"但 import 失败 | D2-01 | P1 | 短期每条命令加 `--isolated`；长期删掉该 `target`，并在 W7 用干净环境验证部署 | 🟨 |

---

## 9. 决策记录（追加式）

| 日期 | 决策 | 原因 | 影响 |
|---|---|---|---|
| 2026-10-23 | 采用“基线门 + 边学边修” | 既保证可运行，又保留真实修复价值 | 全程 |
| 2026-10-23 | embedding 统一 1024 | 与 bge-m3 一致 | W1 |
| 2026-10-23 | 切片改用 `langchain-text-splitters` | 旧 import 已移除 | W1 |
| 2026-10-23 | D1 第 7 行（上传 500）当天不修，转 D2 首步 | 根因 B-013 是结构性缺陷（未装 pgvector 客户端 + 列 `vector(1536)`），现场修等于提前做 D2、破坏 D1 边界；用户选择守住“今天不修 RAG” | D2 必须先装 `pgvector` 并迁移到 1024 维，否则上传永远 500 |
| | | | |

---

## 10. 每周复盘模板

```markdown
### W? 复盘（日期）

**本周完成**
- 

**证据**
- 命令/截图/测试/指标：

**没完成的与原因**
- 

**我学会的 3 件事**
1. 
2. 
3. 

**还讲不清的 3 个点**
1. 
2. 
3. 

**下周调整**
- 

**需要教练帮忙**
- 
```

---

## 11. 证据目录建议

```
docs/evidence/
├── w1-prove-rag.txt
├── w1-smoke/
├── w2-eval.md
├── w2-hnsw-explain.txt
├── w3-agent-tests.txt
├── w4-migration/
├── w5-loadtest/
├── w6-security.md
├── w7-deploy/
└── w8-interview/
```

> 截图/日志文件可以不入库（按需），但 `TRACKER` 要写清路径或命令，保证可复现。
