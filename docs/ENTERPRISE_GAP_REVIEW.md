# 企业级差距复核报告 — AI 知识库 Agent 平台

> 复核时间：2026-10-28
> 复核对象：`D:\python\AI Knowledge Base Agent Platform`（backend + frontend + docs）
> 复核方式：**只读**。逐文件阅读 `backend/app/`（60+ 文件）、`backend/tests/`、`frontend/src/`；用 `.venv` 实测依赖版本、ORM 列类型、路由表、路径拼接行为；未修改业务代码、未写入数据库。
> 与旧版关系：本报告是 [GAP_ANALYSIS.md](GAP_ANALYSIS.md)（2026-10-23，40 条）的**重新核实与升级**。已修复项标注「已关闭」，未被旧版覆盖的新发现标注「新增」。
> 执行清单：[FIX_PLAN.md](FIX_PLAN.md)（按批次排序的"改哪个文件哪一行、怎么验收"）。
> 一句话结论：**架构分层是合格的，功能骨架是完整的，但"正确性兜底 + 工程化交付 + 评测闭环"三件事缺位，当前定位是「可演示的 Demo」，不是「可交付的企业级系统」。**

---

## 0. 一页结论

### 0.1 定位判断

| 问题 | 结论 |
|---|---|
| 现在是什么 | 全栈可跑通的学习级工程：分层清晰、AI 链路齐全、能演示登录→建库→上传→问答→Agent 工具调用 |
| 企业级要什么 | **可交付**（一键起、有文档、有迁移）、**可复现**（依赖锁定、环境一致）、**可观测**（日志/指标/成本/request_id）、**可回滚**（迁移/备份/演练）、**可评测**（数据集 + 指标 + 回归门槛）、**可信**（失败可见、不静默） |
| 差距本质 | 不是"功能太少"，而是 **① 关键链路失败被静默吞掉 ② 工程化交付物几乎为零 ③ 没有任何效果度量**。这三点决定了它现在是 Demo |
| 最大的单点风险 | 向量检索/上传失败仍会把文档标成 `completed`，并在检索失败时返回空上下文继续用通用知识回答。**用户和运维都无法发现 RAG 已经坏了** |

### 0.2 与 2026-10-23 审计相比的变化（本次实测确认）

| 项 | 旧结论 | 本次实测 | 状态 |
|---|---|---|---|
| Python 端 `pgvector` | 缺失，`embedding` 退化为 `TEXT` | `pgvector 0.4.2` 已装；`_HAS_PGVECTOR=True` | ✅ 已关闭 |
| ORM 向量列类型 | `TEXT`（与 DB `vector` 冲突） | `VECTOR(1024)` | ✅ 已关闭 |
| DB 列维度 | `vector(1536)`，与模型 1024 冲突 | 已迁移为 `vector(1024)` | ✅ 已关闭（见 [evidence/d2](evidence/d2/document_chunks_before_migration.sql)） |
| 存量切片是否有向量 | 6 行 / 0 有向量 | 未复核（Docker/PG 当前未启动），代码层面仍无补向量脚本 | 🟨 待验证 |
| `langchain.text_splitter` 旧导入 | 静默降级 | `_HAS_LANGCHAIN = False`（实测） | ❌ 仍在 |
| 默认 JWT 密钥 | 占位符 | `.env` 中 `JWT_SECRET_KEY` 长度 36 = 仍是默认占位符 | ❌ 仍在 |
| `pytest` 可执行性 | 未安装，测试跑不起来 | `pytest` / `pytest-asyncio` **均 MISSING** | ❌ 仍在 |
| 根 README | 缺失 | 缺失（本次补齐） | ✅ 本次关闭 |
| 新增发现 | — | **`.env.example` 仍是 `EMBEDDING_DIMENSION=1536`**，而库列已是 1024 → 新人照 example 配置必然写入失败 | 🆕 新增 |
| **P0-1 失败静默** | 上传 embedding 失败仍标 `completed`；检索异常 `return []` / `return ""` | **已修复**：上传失败落 `failed` + 原因，检索失败抛 `RetrievalError(503)`，SSE 必发 `event: error`；16 个回归用例 + E2E 验证通过 | ✅ 已关闭（2026-10-28） |
| **B6 批次（P2-4/9 + P2-2 + D-3）** | 模型选项存了不生效、Dashboard 数字是假的、无错误码表且生产开着 /docs、备份只有一份 dump | **已修复**：模型按「请求 > 会话 > 配置」生效并支持主备切换 + `/chat/models` + 前端下拉；新增 `/stats/overview` 真实统计（含失败文档数）；`/docs` 按环境开关 + 8 个标签 + 全部接口中文 summary + 统一错误响应，错误码表落 [API_ERRORS.md](API_ERRORS.md)；备份/恢复脚本 + **演练通过**（7 张表行数一致） | ✅ 已关闭（2026-11-08） |
| **B5 批次（P1-1/2 + 两项遗留）** | 无向量索引、无数据库迁移、失败原因不落库、上传无内容去重 | **已修复**：双库 Alembic + HNSW、评测集 + recall@k/MRR + 阈值扫描、conftest/集成测试/覆盖率门禁、失败原因持久化、sha256 内容去重；期间修掉「yield 依赖在响应后才 commit」与「404 不走统一信封」 | ✅ 已关闭（2026-10-28） |
| **B4 批次（P1-9/10/12/13）** | 无结构化日志、/health 假探针、SSE 把消息放 URL、限流语义错 | **已修复**：JSON 日志 + request_id 贯穿、真实探活、SSE 改 POST、双窗口限流 + 登录锁定；期间还抓到并修掉「SQL 日志泄漏用户消息」 | ✅ 已关闭（2026-10-28） |
| **B2 批次（P0-3/7/8/9、P1-3/4）** | Agent 忽略选中库、默认 JWT 密钥、上传穿越/阻塞、依赖脱节、删库留孤儿、会话 N+1 | **已修复**：见 [B2 批次修复记录](#b2-批次修复记录2026-10-28)；19 个回归用例 + E2E 验证。**到此 P0 全部清零** | ✅ 已关闭（2026-10-28） |
| **B1 批次（P0-2/4/5/6、P1-8）** | 问题重复注入、Agent 超限空答、AgentChat 答案消失、错误码语义错、降级覆盖消息 | **已修复**：见 [B1 批次修复记录](#b1-批次修复记录2026-10-28)；24 个回归用例 + E2E 验证通过。期间还挖出 4 个此前无人发现的阻断级 bug | ✅ 已关闭（2026-10-28） |
| **`cryptography` 缺失** | 旧审计仅列为"缺失依赖" | 实测发现它会**阻断全部数据库连接**：MySQL 8 `caching_sha2_password` 认证抛 `RuntimeError`，任何认证请求直接 500，后端等同不可用 | ✅ 已安装并写入 requirements（2026-10-28） |

### 0.3 五维评分（1–5，5 = 企业级基线）

| 维度 | 分数 | 判断依据 |
|---|---|---|
| 架构与分层 | **4.0** | `router → service → repository → model` + `schemas` + `core` 横切；依赖注入规范；越权校验统一。已是企业级写法 |
| 功能完整度 | **3.5** | 认证/权限、KB/文档、聊天、RAG、Agent 工具、管理端、SSE 都在。缺引用、反馈、停止生成、重试 |
| 正确性 | **2.0** | 当前问题重复注入、Agent 忽略选中 KB、达上限返回空、前端流式后答案消失、失败静默 |
| 工程化交付 | **1.5** | 无 README（本次补）、无 Dockerfile/Compose/CI、无 `pyproject`、无迁移、依赖版本停在一年前 |
| 可靠性/可观测 | **1.5** | 无结构化日志、无 request_id、无指标、无成本统计、`/health` 是假探针、emoji 导致 Redis 误报 |
| 安全 | **2.0** | 默认 JWT 密钥、消息走 GET query、token 在 localStorage、无吊销/轮换、路径穿越、限流 fail-open |
| 质量保障 | **1.5** | 5 个单测且当前跑不起来；无评测集、无覆盖率、无回归门槛；后端无 lint/type check |

**综合：约 2.3 / 5。** 架构已经是企业级；**其余五项是企业级门槛**。

### 0.4 问题数量

| 级别 | 数量 | 含义 |
|---|---|---|
| P0 | 9（**全部关闭**） | 阻断"可用/可信"，必须最先修 |
| P1 | 14（**全部关闭**） | 阻断"生产可用" |
| P2 | 12（已关闭 8） | 质量与体验 |
| 合计 | **35** | 逐条见 §2–§4 |

---

## 1. 企业级项目 vs 本项目：七个维度的差别

> 判断标准：一个企业项目交给同事接手时，**他能不能在不问你的前提下把系统跑起来、改对、发布、出问题定位、证明效果**。

### 1.1 可交付性（最直观的差距）

| 企业级做法 | 本项目现状 |
|---|---|
| 根 README：定位、架构图、快速开始、配置表、API、状态、Roadmap | 无（本次补齐） |
| `Dockerfile` + `docker-compose.yml`，`docker compose up` 一键起全栈 | 无；MySQL 是 Windows 服务、PG/Redis 是手工 `docker run`，换机器靠记忆 |
| `.github/workflows`：lint + test + build 门禁 | 无 |
| `LICENSE`、`CHANGELOG.md`、`CONTRIBUTING.md` | 均无 |
| 版本号语义化并对外可见（`APP_VERSION` 已在配置里，但无发布记录） | 有字段，无发布流程 |
| 空库可建表：`alembic upgrade head` | **`alembic/versions/` 为空**；实际靠 `scripts/init_db.py` 的 `create_all`（只建不改） |

**后果**：别人 clone 下来大概率起不来；面试官无法判断"这是能跑的系统还是半成品"。

### 1.2 可复现性

| 企业级做法 | 本项目现状 |
|---|---|
| 依赖锁定（`requirements.txt` + `constraints.txt` 或 `uv.lock`/`poetry.lock`），CI 用干净环境验证 | `requirements.txt` 停在旧版本：`fastapi==0.115.0`（实装 0.136.3）、`openai==1.50.0`（实装 2.41.1）、`langchain==0.3.0`（实装 1.3.7）、`langgraph==0.2.0`（实装 1.2.4）；`httpx` 重复两行；`pytest` 声明了但没装进 venv |
| `pyproject.toml` 统一管理依赖、Python 版本、lint/format/test 配置 | 无；Python 3.13 能跑但未声明 |
| 配置从绝对路径加载，任意目录启动行为一致 | `config.py:123` `env_file=".env"` 相对 **CWD**；从仓库根启动会静默用默认配置（本地实测过模型变回 `text-embedding-ada-002`） |
| 启动自检：缺依赖/配置错误直接 fail fast | 缺 `pgvector` 时只是 `logger.warning` + 类型降级；缺 Embedding key 时整条 RAG 静默跳过 |

**后果**：同一份代码在不同机器行为不同；升级依赖时"为什么昨天好的今天坏了"无法回答。

### 1.3 正确性与一致性

| 企业级做法 | 本项目现状 |
|---|---|
| 上下文组装有唯一入口，并有单测断言"当前问题只出现一次" | 先写库再读历史再拼当前消息 ⇒ **同一问题进 prompt 两次**（`chat_service.py:306/313/316`、`agent_service.py:168/175/188`） |
| 检索范围是硬约束（多租户下是安全问题） | Agent 工具把 `kb_ids` 放进 context 后 **从未使用**（`tools.py:341-348`），选 A 库仍检索全库 |
| 达到迭代上限有兜底文案 | 超限时 `_extract_result` 取不到 assistant 正文 ⇒ **空回答**（`graph.py:379-383`、`agent_service.py:379-381`） |
| 上下文按 token 预算裁剪 | 固定 `limit=20` 条；`LLMService.count_tokens` 写了但**全仓无调用** |
| 跨库删除有补偿/清理 | 删 KB 只删 MySQL，**PG 切片变孤儿**（`knowledge_base_service.py:81-88`），检索仍可能命中已删文档 |
| 状态码语义正确 | `AppException(http_status_code=400)` 默认值 + `auth_service.py:48` 只传 `code=401` ⇒ **登录失败返回 HTTP 400**（body 里才是 401） |
| 失败必须可见 | 上传 embedding 失败仅 `logger.warning` 后仍标 `completed`；检索异常 `return []` / `return ""` |

**后果**：这是"Demo 与生产"的真正分水岭——**用户可以正常提问，系统可以正常回答，但回答里没有任何知识库内容，且没有任何人知道**。

### 1.4 性能与容量

| 企业级做法 | 本项目现状 |
|---|---|
| 向量列建 ANN 索引（HNSW/IVFFlat），有 `EXPLAIN` 证据 | **无任何向量索引**，仅 pkey + `document_id` btree；上万切片后全表扫描 + 逐行余弦 |
| 列表接口避免 N+1 | 会话列表每个会话单独 `count`（`chat_service.py:192-204`）⇒ 50 会话 = 51 次 SQL；KB 列表同样 N+1 |
| 重活异步化（上传只落盘 + 建任务，解析/切片/embedding 进后台队列） | 上传在请求内**同步**完成：整文件 `await file.read()` 入内存、同步解析阻塞事件循环、同步写盘 |
| Embedding 分批 + 重试 | 一次 `embeddings.create(input=全部切片)`（`embeddings.py:108-114`），无分批、无重试、无并发控制 |
| 会话 `updated_at` 随发消息更新 | 从不更新 ⇒ 会话列表排序永远不变 |

### 1.5 可观测性与运维

| 企业级做法 | 本项目现状 |
|---|---|
| `logging.config.dictConfig`：JSON 结构化日志、按级别分流、文件轮转 | 全仓无 logging 配置；`backend/logs/` 为空；启动只有 `print` |
| request_id 贯穿一次请求（含 LLM 调用） | 无 |
| 指标：QPS/延迟直方图、`rag_retrieval_total{status}`、`embedding_fail_total`、token/成本 | 无 |
| `/health` 真实探活 DB/Redis 分项状态 | 返回常量 `{"status":"healthy"}`，停库也 healthy |
| 生产关闭 SQL echo、敏感字段脱敏 | `echo=settings.DEBUG` 且 `DEBUG=True` ⇒ **SQL 与参数（含用户消息、切片正文）全量打印** |
| 备份有恢复脚本与演练 | 仅一份 `database-backups/*.dump`，无恢复脚本、无演练记录 |

**另有新增 bug（P1）**：`main.py:38-46` 把"连上 Redis"和"打印成功日志"放同一个 `try`，成功分支打印 `✅`。Windows 控制台 cp936 无法编码 emoji ⇒ `UnicodeEncodeError` 被 `except Exception` 捕获 ⇒ **启动日志误报"Redis 未连接（降级）"，而实际连接是好的**。

### 1.6 安全与合规

| 企业级做法 | 本项目现状 |
|---|---|
| 密钥必填、无默认值，缺失即拒绝启动 | `JWT_SECRET_KEY` 仍是 `your-secret-key-change-in-production`（实测长度 36）；`main.py:19-22` 只在非 DEBUG 时拒绝启动 |
| 短 access + refresh 轮换 + 服务端吊销（jti/版本号） | 无黑名单/版本号；`refresh` 不轮换，泄露可长期复用；登出无法真正吊销 |
| 敏感内容不走 URL | 聊天与 Agent 流式都是 **GET + `?content=...`**（`routers/v1/chat.py:148`、`agent.py:82`）⇒ 用户消息进 access log/代理日志，长度受限 |
| token 存 httpOnly cookie 或内存 | `useSSE.ts:24` 与 `client.ts` 从 **localStorage** 取 token（XSS 直接窃取） |
| 上传文件名净化 + resolved path 校验 | 未净化：实测 `..\..\..\evil.txt` 落到 `uploads/3/evil.txt`（逃逸出 `kb_id` 目录） |
| 登录失败计数与锁定 | 无 |
| 限流语义准确、故障快速失败 | 注释写"滑动窗口"，实现是固定窗口（`INCR` + `time//window`）；Redis 不可用时 **fail-open 放行**且每次请求重试连接；同一请求同时受中间件与依赖两层限流 |

### 1.7 质量保障与评测（最容易被面试追问的地方）

| 企业级做法 | 本项目现状 |
|---|---|
| 测试金字塔：单元 + 集成（`TestClient`/`AsyncClient`）+ 少量 e2e，覆盖率门槛 | `backend/tests/` 仅 5 个文件、**7 个测试函数**（含 1 个参数化用例）；**无 `conftest.py`、无数据库 fixture、无 TestClient**；当前 venv 没装 pytest ⇒ 实际不可执行 |
| 后端 lint/type：ruff + mypy | 无（前端有 oxlint） |
| RAG 评测：QA 数据集 + `recall@k`/`MRR` + LLM-as-judge，改动前后对比 | **完全没有**。`chunk_size=500`、`overlap=50`、`top_k=5`、`threshold=0.7` 四个关键参数**没有任何实验依据** |
| 回归门槛：CI 里 recall 不低于 baseline | 无 |
| 手工脚本与产品代码分离 | 根目录散落 `test_phase6.py`、`test_phase7.py`、`reset_pg_table.py`、`check_pgvector.py`、`check_pg_ext.py`、`test_token.txt` |

**后果**：无法回答"改完之后效果变好了吗"——这恰恰是 AI 应用最核心的工程问题。

### 1.8 产品化

| 企业级做法 | 本项目现状 |
|---|---|
| 回答带引用（点击跳到原文片段）、可反馈（赞/踩/纠错） | 无引用展示、无反馈闭环 |
| Markdown 渲染、代码高亮、流式可停止/重试 | 纯文本 `pre-wrap`；无停止生成、无重试 |
| 会话连续性（追问基于同一会话） | AgentChat URL 不带 `session_id` ⇒ 每问一句新建一个会话；`onDone` 用闭包旧值 ⇒ **回答结束后消息变空** |
| 空态/骨架屏/错误边界/i18n | 大量 `any`、无 ErrorBoundary、中文硬编码 |
| 页面数据与库一致 | Dashboard「文档」恒为 0（`docCount` 从未请求）；用户管理显示后端不存在的 `email` 字段 |

---

## 2. P0 缺陷（9 条，必须先修）

> 统一验收口径：**能复现、能观测、有回归测试**。

### P0-1 上传/检索失败静默，文档仍标 `completed`

**状态：✅ 已关闭（2026-10-28）** — 修复记录见本节末尾。

- **证据**：`document_service.py:150-151` embedding 异常 → `logger.warning` → `:156` 仍 `update_status(..., "completed")`；`document_repo.py:179-181` 向量搜索异常 → `return []`；`retriever.py:97-99` → `return ""`；`deps.py:19-32` PG 不可用静默 `yield None`。
- **影响**：RAG 已坏但系统"正常"回答；无法区分"没有相关内容"与"检索挂了"。
- **修复**：上传 embedding 失败 ⇒ `status=failed` + 错误写入 `extra_meta`；检索区分「无结果」与「检索失败」（失败抛 `AppException` 或 SSE `event: error`）；缓存/限流可降级，**核心检索禁止静默**；启动时校验 `len(vector) == EMBEDDING_DIMENSION`。
- **验收**：断掉 Embedding key 上传 → 文档 `failed` 且前端可见；停 PG 后问答 → 明确错误事件；日志/指标有失败计数。

#### 修复记录（2026-10-28）

**行为契约的变化**

| 原来的行为 | 现在的行为 |
|---|---|
| embedding 失败 → `logger.warning` → 文档 `completed` | 文档落库 `failed`，响应 `message` 带具体原因，前端弹 warning + 列表里红色 `failed` 可悬停看说明 |
| 向量库未连接 → 上传照常"成功"、切片 0 条 | 前置检查直接 503，不写文件、不建记录（不留半成品） |
| 检索报错 → `return []` → 空上下文照样回答 | 抛 `RetrievalError(503)`；SSE 必发 `event: error` + 结束事件，不会静默断流 |
| 前端只处理 token，忽略后端已发出的 `data: {"error":...}` | `useSSE` 处理 `error` / `done`：聊天出错不再"毫无反应" |
| 无任何计数 | 每类失败都有计数器 + 耗时统计，`/health` 可直接读 |
| 维度不一致要到写库才报数据库错 | 写库前按 `EMBEDDING_DIMENSION` 校验向量长度；启动时探测 DB 列维度 |

**改动文件**

| 文件 | 改动 |
|---|---|
| `app/core/metrics.py` | 新增：进程内计数器 + 耗时统计（零依赖） |
| `app/core/exceptions.py` | 新增 `RetrievalError(AppException, 503)` |
| `app/rag/embeddings.py` | 写库前校验向量维度；embedding 成败计数与耗时 |
| `app/repositories/document_repo.py` | 检索失败不再吞异常；`document_ids=[]` 等价于"查不到"而非"查全库" |
| `app/rag/retriever.py` | 抽出 `_search()` 统一内核：失败抛 `RetrievalError`，空结果正常返回 |
| `app/services/document_service.py` | 上传流程重构：前置 503、失败落 `failed`、PG 会话回滚、分步失败原因 |
| `app/services/chat_service.py` | RAG 不可用即报错；SSE 外层包装把异常翻译成 `event: error` |
| `app/services/agent_service.py` | 同上（Agent SSE） |
| `app/core/deps.py` | PG 会话失败改为计数 + 明确日志 |
| `app/main.py` | 启动校验 pgvector 与列维度；`/health` 暴露指标；移除误导性 emoji 日志 |
| `frontend/src/hooks/useSSE.ts` | 处理 `error` / `done` |
| `frontend/src/pages/Chat.tsx` | 错误写进气泡，不只弹 toast |
| `frontend/src/pages/DocumentList.tsx` | 依据 `status=failed` 提示失败原因；failed 标签带说明 |
| `frontend/src/api/document.ts` | 上传响应类型化 |

**验收证据**（真实运行，PostgreSQL 未启动）

```
=== upload (PG down) http 200 ===
"status": "failed",
"message": "文档已接收，但处理失败：切片写入向量库失败：[WinError 1225] 远程计算机拒绝网络连接。"
=== document list === [(12, 'p0_smoke.txt', 'failed', 0)]
=== SSE with kb selected (PG down) ===
event: error
data: {"message": "知识库检索失败：向量检索出错", "code": 503}
data: {"token": "", "done": true}
=== metrics ===
document_upload_total{status=failed}: 1
vector_search_total{status=error}: 1
rag_retrieval_total{status=error}: 1
chat_stream_total{status=error}: 1
```

回归测试：`backend/tests/test_p0_1_failure_visibility.py`（16 个用例，全部不依赖 DB/网络）；全套 `pytest` 29 passed。

**遗留（属于后续条目，不在 P0-1 范围）**：失败原因只出现在响应与日志里，没有持久化字段（需给 `documents` 加 `error_message` 列 + 迁移，见 P1-2）；上传仍是同步处理（P0-8）。

### P0-2 当前问题在 prompt 中重复注入

**状态：✅ 已关闭（2026-10-28）** — 见 [B1 批次修复记录](#b1-批次修复记录2026-10-28)。

- **证据**：`chat_service.py:306` 先存用户消息 → `:313` 读最近 20 条（已含当前）→ `:316` `build_messages(content, history, ...)` 再 append 一次。Agent 侧 `agent_service.py:168/175/188` 同构。
- **影响**：模型看到两遍同一问题；浪费 token；长会话下挤掉更早上下文；可能诱导重复回答。
- **修复**：先读历史（排除当前）再保存，或统一封装 `build_context(session_id, current)` 由 chat/agent 复用。
- **验收**：单测断言 messages 中当前内容出现次数 = 1。

### P0-3 Agent 检索忽略选中的知识库（越权风险）

**状态：✅ 已关闭（2026-10-28）** — 见 [B2 批次修复记录](#b2-批次修复记录2026-10-28)。

- **证据**：`agent_service.py:346-348` 把 `context["kb_ids"]` 传下去；`tools.py:339-348` 只读 `document_ids`，**`kb_ids` 从未使用**。
- **影响**：只选 A 库，工具仍检索全库 ⇒ 跨库内容泄露/答非所问。多租户下是安全问题。
- **修复**：工具层把 `kb_ids` → `document_ids` 下推；更彻底的做法是 chunks 表冗余 `knowledge_base_id`，SQL 直接 `WHERE knowledge_base_id IN (...)`；归属校验失败显式 403。
- **验收**：两库放不同文档，选 A 问 B 内容 ⇒ 结果只来自 A；单测覆盖。

### P0-4 Agent 达到迭代上限返回空回答

**状态：✅ 已关闭（2026-10-28）** — 见 [B1 批次修复记录](#b1-批次修复记录2026-10-28)。

- **证据**：`agent_service.py:379-381` 超限只推 error 事件、`full_reply` 为空；`graph.py:379-383` 反向找"有 content 的 assistant"，超限时最后一条是 `content=None` 的 tool_calls 消息 ⇒ `result=""`；`max_iterations` 硬编码 10（`graph.py:279`、`agent_service.py:310`）。
- **修复**：超限时强制一次"不带 tools 的总结调用"，或返回明确兜底文案；`max_iterations` 走配置。
- **验收**：构造超限场景，回答非空且含上限说明；改配置能生效。

### P0-5 AgentChat 流式结束后答案消失、无会话连续性

**状态：✅ 已关闭（2026-10-28）** — 见 [B1 批次修复记录](#b1-批次修复记录2026-10-28)。

- **证据**：`AgentChat.tsx:106` URL 只有 `content` 与 `kb_ids`，**无 `session_id`**；`:127-140` `onDone` 用闭包捕获的 `streamContent`（连接建立时为 `""`），随后 `setMessages` 追加空内容并清空。
- **影响**：用户看到流式输出，结束瞬间消息变空；每问一句新建会话，会话列表被污染。
- **修复**：`useRef` 保存最新 `streamContent`/`toolCalls`，`onDone` 读 ref；记录首个 `event: session` 的 `session_id` 并在后续请求带上；从会话详情恢复历史。
- **验收**：连续追问 3 轮，消息不消失、历史在、只产生一个会话；工具卡片结束后仍可展开。

### P0-6 登录失败返回 HTTP 400（状态码语义错误）

**状态：✅ 已关闭（2026-10-28）** — 见 [B1 批次修复记录](#b1-批次修复记录2026-10-28)。

- **证据**：`exceptions.py:26` `http_status_code` 默认 400；`auth_service.py:48/51` 只传 `code=401`。同类：`:54` 禁用（code=403）、`chat_service.py:221` 会话不存在（code=404）也会变 400。
- **影响**：前端拦截器按 401 触发 refresh、网关/监控按状态码统计，全部失真；REST 语义错误。
- **修复**：未显式传 `http_status_code` 时默认取 `code`（或维护 `code → HTTP` 映射）；补测试覆盖 401/403/404/422。
- **验收**：错误登录 401、无权限 403、不存在 404。

### P0-7 默认 JWT 密钥仍在使用

**状态：✅ 已关闭（2026-10-28）** — 见 [B2 批次修复记录](#b2-批次修复记录2026-10-28)。

- **证据**：`.env` 中 `JWT_SECRET_KEY` 长度 36（= 默认占位符原文）；`main.py:19-22` 在 DEBUG=True 时只打印警告；`backend/test_token.txt` 仍在工作区。
- **影响**：知道默认值即可伪造任意用户/管理员 token；一旦泄露是账单与数据双重风险。
- **修复**：生成 64 字节随机 secret；删除 `test_token.txt`；非 DEBUG 且为默认值 ⇒ **拒绝启动**；轮换 LLM/Embedding key；CI 加 gitleaks。
- **验收**：默认 secret 无法启动；旧 token 全部失效；仓库无明文密钥。

### P0-8 上传路径穿越 + 同步阻塞 + 无去重

**状态：✅ 已关闭（2026-10-28）** — 见 [B2 批次修复记录](#b2-批次修复记录2026-10-28)。

- **证据**：`document_service.py:319-320` `f"{uuid}_{filename}"` 未净化文件名——**实测 `filename='..\..\..\evil.txt'` 解析为 `uploads/3/evil.txt`**（逃逸出 `kb_id` 目录）；`:89` 整文件读入内存（上限 50MB）；`:108` 同步解析在 async 上下文执行，阻塞事件循环；`:323` 同步写盘；无 sha256 去重；`html` 按纯文本读，标签进切片。
- **影响**：可写任意路径（安全）、大 PDF 上传时整个服务卡住、重复上传浪费 embedding 成本。
- **修复**：`Path(filename).name` + 字符白名单 + `resolve()` 后校验仍在 `uploads/` 下；上传只落盘建 `pending`，解析/切片/embedding 交后台任务；sha256 同库去重；embedding 分批 32/64 + 重试；HTML 用解析器抽正文。
- **验收**：`..\..\evil.txt` 被拒；50MB 上传接口 2s 内返回且进度可查；同文件二次上传被识别。

### P0-9 环境不可复现（依赖与切片路径）

**状态：✅ 已关闭（2026-10-28）** — 见 [B2 批次修复记录](#b2-批次修复记录2026-10-28)。

- **证据**：`requirements.txt` 全线旧版本（见 §1.2）；`pgvector` 已装但 `requirements` 写 0.4.2 而实际链路依赖 `pgvector.asyncpg` 注册；`pytest`/`pytest-asyncio` **未装进 venv**；`text_splitter.py:24` 仍 `from langchain.text_splitter import ...`，LangChain 1.x 已拆到 `langchain-text-splitters`，实测 `_HAS_LANGCHAIN=False` ⇒ **静默走简易切分**；`.env.example` 的 `EMBEDDING_DIMENSION=1536` 与库列 1024 冲突。
- **影响**：新机器照 `requirements.txt` 装不出现有环境；切片行为在不同机器不同；新人照 example 配置必然写库失败。
- **修复**：以可用环境重新锁定依赖（`requirements.txt` + `requirements.lock`），补 `cryptography`、按需 `tiktoken`；改用 `langchain-text-splitters>=1.1,<2`；`.env.example` 与 `config.py` 默认值统一为 1024；启动时校验维度。
- **验收**：全新 venv `pip install -r` 后 `import app.main` 成功且 `_HAS_LANGCHAIN=True`；`pip check` 干净。

---

### B1 批次修复记录（2026-10-28）

本批次关闭 5 项：**P0-2 / P0-4 / P0-5 / P0-6 / P1-8**。每项的状态行已标在对应小节标题下。

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P0-2 | 先存消息 → 读最近 20 条（含当前）→ 再拼一次当前问题 | 抽出 `services/message_context.py::load_history(..., current_message_id=...)`，查询侧用 `get_recent_history(exclude_id=)` 排除当前这条；chat 与 agent 共用同一入口 |
| P0-4 | 超限时最后一条 assistant 是 `content=None` 的 tool_calls → 空回复 | ① `max_iterations` 走配置 `AGENT_MAX_ITERATIONS`；② 超限后强制一次不带 tools 的总结调用；③ 总结也失败则返回可读兜底文案；④ 补齐"悬空的 tool_calls"（见下方 N-4） |
| P0-5 | `onDone` 读闭包旧值 → 答案变空；URL 不带 `session_id` → 每问新建会话 | 前端用 `useRef` 保存最新 `streamContent`/`toolCalls`；监听 `event: session` 记住会话；URL 带上 `session_id`；支持从 `?session_id=` 恢复历史 |
| P0-6 | `AppException` 的 `http_status_code` 默认 400，401/403/404 全变 400 | 未显式传时默认取 `code`（非合法 HTTP 码则退回 400）；auth 的 5 处补显式值。**关键前提是修掉 N-3**，否则异常会被依赖层吞成 500 |
| P1-8 | 降级循环用 `dict.update()` 替换消息历史 | 抽 `_merge_state()`：`messages` 追加、其余字段覆盖；降级路径补测试 |

**本批次新发现（此前两轮审计都没抓到）**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-1 | **工具名重复导致 Agent 全挂**：`seed_data.py` 把 3 个内建工具写进 `agent_tools`，注册成"动态工具"后与 `_SYSTEM_TOOLS` 同名 → 上游返回 `400 Tool names must be unique`。**每一个 Agent 请求都失败**（降级路径同样失败），这解释了旧冒烟记录里"Agent 发消息 200 但完全没有回复" | 🔴 阻断级 | ✅ 已修：`get_tool_definitions()` 按名去重，系统工具优先 |
| N-2 | **非流式 Agent 变量名拼错**：`len(tool_calls_infos)`（正确名 `tool_call_infos`）→ 每次成功调用都 `NameError` → 500 | 🔴 阻断级 | ✅ 已修 |
| N-3 | **依赖层把路由异常吞成 500**：`get_vector_db` 把 `yield session` 包在 `try/except Exception` 里，路由抛出的 `AppException` 被 catch 后又 yield 一次 → `RuntimeError: generator didn't stop after athrow()` → 500。**所有 chat/document/agent 路由的业务状态码都被它吃掉** | 🔴 阻断级 | ✅ 已修：只把"创建会话对象失败"降级为 `None`，路由异常原样上抛 |
| N-4 | **兜底总结必然失败**：达到上限时消息停在 `assistant(tool_calls)` 而没有 tool 回复，上游 400（insufficient tool messages）→ 总结永远走模板 | 🟠 中 | ✅ 已修：`_close_pending_tool_calls()` 补占位 tool 消息 |
| N-5 | **启动维度探测解码错误**：按 `atttypmod - 4` 解码，而 pgvector 的 `atttypmod` 直接等于维度 → 实测把 `vector(1024)` 误报成 `vector(1020)` 并打印"维度不一致" | 🟡 低 | ✅ 已修 |
| N-6 | **`AppException` 不调用父类构造** → `str(exc)` 为空，日志只剩类名、用户文案变成"Agent 执行出错：" | 🟠 中 | ✅ 已修：`super().__init__(message)` |
| N-7 | **`register_vector` 协程未 await**：`session.py:62` 在同步 connect 事件里调用 async 函数 → `RuntimeWarning: coroutine was never awaited`，Vector codec 实际未注册 | 🟡 低 | ⬜ 未修：实测 ORM 向量读写仍可用（pgvector 的 SQLAlchemy 类型自带 bind/result 处理），但这是明显的错误代码，应删掉这段事件或改成正确的注册方式 |

**验收证据（真实运行）**

```
[P0-6] 错误密码登录        HTTP 401   body.code 401
[P0-6] 不存在的会话         HTTP 404
[P0-6] 重复用户名注册       HTTP 400

[P0-4] POST /agent/chat（服务端 AGENT_MAX_ITERATIONS=1）
       HTTP 200  iterations=1
       reply: "1024 × 768 = 786,432（说明：上面的工具调用实际未执行成功，这个结果是我直接计算的。）"

[P0-5] 流式两轮均带 session_id：token 事件各 1 条；第二轮无 event: session
       会话总数 before/after = 2 / 2（没有新建）
       会话消息角色序列 = ['user','assistant','user','assistant']
```

回归测试：`backend/tests/test_b1_agent_and_context.py`（24 个用例，全部不依赖 DB/网络）；全套 `pytest` **53 passed**。
前端 `npm run build` 与 `npx oxlint` 通过。

**B1 未覆盖（属于后续批次）**：Agent 仍会检索未选中的知识库（P0-3，B2-1）；Agent 仍不是真流式（P1-6，B3-3）；失败原因未持久化（需 `documents.error_message` + 迁移，B5-2）。

---

### B2 批次修复记录（2026-10-28）

本批次关闭 6 项：**P0-3 / P0-7 / P0-8 / P0-9 / P1-3 / P1-4**。**至此 P0 全部清零。**

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P0-3 | Agent 工具拿到 `kb_ids` 却从不使用 → 选 A 库也能检索到 B 库 | 新增 `AgentService._resolve_document_ids()`：校验归属后把"知识库"展开成"文档 ID 列表"，同时用于 ① system prompt 的 RAG 上下文 ② 工具调用的检索范围。**拿不到范围就不提供 retriever**（工具直接回"没有可检索的文档范围"），而不是退化成全库检索 |
| P0-7 | `.env` 里 `JWT_SECRET_KEY` 仍是 36 字符的默认占位符 | 轮换为 64 字符随机密钥；删除 `test_token.txt`；`_validate_runtime_config()` 把 DEBUG 下的 `print("Warning")` 升级为 `logger.error`，非 DEBUG 且默认值/过短则拒绝启动 |
| P0-8 | 上传整文件读入内存、同步解析阻塞事件循环、文件名未净化 | ① 文件名净化（`\` 与 `/` 都当分隔符 + 白名单 + 长度截断）且**落库也存净化后的名字** ② 流式落盘、边写边计数、超限即中断并删除半截文件（HTTP 413）③ 解析走 `asyncio.to_thread` ④ `resolve()` 后校验落盘路径仍在本次上传目录内 |
| P0-9 | 依赖版本停在一年前；切片器旧导入静默降级；`.env.example` 维度与库列冲突 | ① `requirements.txt` 按实装版本重锁 ② 改用 `langchain_text_splitters`（实测 `_HAS_LANGCHAIN=True`）③ `EMBEDDING_DIMENSION` 默认与 example 统一为 1024，`.env.example` 补齐新增配置项 |
| P1-3 | 删知识库只删 MySQL，PG 切片变孤儿 | 删除顺序改为「查 document_id → 批量删 PG 切片 → 删 MySQL」；PG 会话缺失时**拒绝删除**（503），不再制造脏数据；新增 `scripts/cleanup_orphan_chunks.py`（可重复执行） |
| P1-4 | 会话列表 N+1、`updated_at` 从不更新、详情静默截断 100 条 | ① `count_by_sessions()` 一条 `GROUP BY` 拿全 ② 发消息时 `session_repo.touch()` ③ 详情上限提到 `SESSION_DETAIL_MAX_MESSAGES=500` 并返回 `message_total`，被截断时打 warning |

**本批次新发现**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-8 | 文件名净化只作用于磁盘路径，`documents.filename` 仍存原始值（`..\..\evil.txt` 原样入库、原样回显给前端） | 🟠 中 | ✅ 已修：落库也用净化后的 basename（E2E 抓到） |
| N-9 | **存量切片没有补向量脚本**：审计基线里 6 条切片 embedding 为 NULL，文档"存在却永远检索不到" | 🟠 中 | ✅ 已修：新增 `scripts/backfill_embeddings.py`（幂等、分批、维度校验），并已在本机执行 |
| N-10 | 历史删除路径留下的真实孤儿：PG 里 document_id=7/8 共 4 条切片，对应的 MySQL 文档早已不存在 | 🟠 中 | ✅ 已清：`cleanup_orphan_chunks.py --apply` 删除 4 条，二次执行报"没有孤儿"（幂等） |
| N-11 | 前端 `SessionDetail` 类型没有 `message_total` 字段 | 🟡 低 | ⬜ 未修：属于 B7-2 前端改造范围，当前前端不读该字段，不影响功能 |

**验收证据（真实运行，MySQL + PostgreSQL + Redis 全部在线）**

```
[P0-9] 上传 A 库文档 → HTTP 200 / status=completed / chunks=1
       PG: count(*)=1, count(embedding)=1        ← 首次端到端跑通"上传→切片→向量"
[P0-8] 上传文件名 ..\..\..\evil.txt → 落库文件名 = evil.txt
[P0-3] Agent 只选 A 库，问"代号是什么"
       tool_result=1 / token=1 / 出现 ZZZ-42=True / 出现 YYY-99=False   ← 无越权
[P1-4] 发消息前排序：['会话二','会话一']
       给会话一发消息后：[('会话一',2),('会话二',0)]      ← updated_at 生效 + message_count 正确
       详情 message_total=2 / 实际 2 条                   ← 不再静默截断
[P1-3] 删除 A 库 → A 残留切片=0，B 残留切片=1（未误删）
       DELETE HTTP 200，A 库文档接口 404
[数据修复] backfill_embeddings.py --apply → 补 2 条
           全库校验：count(*)=2, count(embedding)=2, vector_dims ∈ {1024}
```

回归测试：`backend/tests/test_b2_security_and_consistency.py`（19 个用例，不依赖 DB/网络）；全套 `pytest` **72 passed**。

**B2 未覆盖**：上传仍是同步处理（`P0-8` 只做到了"不阻塞事件循环 + 不爆内存"，真正的异步任务队列在 B6/B7 之后）；内容级去重需要 `documents.file_hash` 列 + 迁移（B5-2）；CORS 仍只放行 3000（P1-24 类问题，随 B4 一起改）。

---

## 3. P1 完善清单（14 条）

| ID | 问题 | 证据 | 影响 | 修复要点 |
|---|---|---|---|---|
| P1-1 | 无 ANN 索引，检索全表扫描 | `pg_indexes` 仅 pkey + `document_id`；全仓无 `hnsw/ivfflat` | 上万切片后延迟线性增长 | `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`；调 `hnsw.ef_search`；`EXPLAIN` 留证 |
| P1-2 | `alembic/versions/` 为空 | 目录 0 文件；`alembic/env.py` 只见 MySQL，无 PG metadata | schema 无法安全演进，新人无法从零重建 | MySQL + PG 双 `target_metadata`；维度迁移/HNSW 写成迁移；禁止生产 `create_all` |
| P1-3 | 删 KB 不清 PG 切片 | `knowledge_base_service.py:81-88` 只删 MySQL | 孤儿切片导致检索命中已删内容、越权 | 先删 PG chunks 再删 MySQL（或补偿）；加孤儿清扫脚本 |
| P1-4 | 会话列表 N+1、`updated_at` 不更新、详情截断 100 条 | `chat_service.py:192-204`；`chat_repo.py:25-26`（注释说返回总数，实际只返回 sessions）；`get_by_session` 默认 `limit=100` | 50 会话 51 次 SQL；排序永远不变；长会话静默丢消息 | `GROUP BY` 聚合 count；发消息时 touch `updated_at`；详情分页 |
| P1-5 | 上下文固定 20 条，token 预算未用 | `chat_service.py:404-420`、`agent_service.py:459-467`；`count_tokens` 无调用 | 20 条长消息可能超窗；20 条短消息浪费预算 | 由新到旧累加 token，保留 ≤ 窗口 60%（含 system + 输出预留） |
| P1-6 | Agent「流式」不是真流式 | `agent_service.py:375` 一次性 yield 完整 `reply_text` | 首 token 延迟 = 整段生成时间 | 工具阶段结束后用 `chat_stream` 逐 token；统一 `error`/`done`；落库部分回答 |
| P1-7 | 动态工具只有 schema 没有 executor | `tools.py:153-161` `tool_map` 仅 3 个内建；`agent_repo` 允许建任意工具；`_dynamic_tools` 是**全局变量** | 管理端"新增工具"是假功能；LLM 调用返回"未知工具"；多租户串数据 | 实现 executor 注册（HTTP/白名单），或过滤掉无 executor 的工具；按租户隔离注册表 |
| P1-8 | LangGraph 降级路径会覆盖消息 | `graph.py:327-344` 普通 dict `update` 是**替换**而非 `operator.add` | 降级后 tool 消息缺前置 assistant tool_calls ⇒ LLM 400、回答为空 | 抽 `append_messages()` 显式合并；或异常直接报错不静默降级；为降级路径补测试 |
| P1-9 | 无结构化日志 / request_id / 指标 / 成本 | 全仓无 logging 配置；`logs/` 为空；`main.py` 只有 print | 排障无法串联一次请求；无法回答"每次问答多少钱" | `dictConfig` + JSON；request_id 中间件；记录 `prompt/completion_tokens`、latency、model、cost |
| P1-10 | `/health` 是假探针；DEBUG 打印全部 SQL | `main.py:125-128` 返回常量；`session.py:25/42` `echo=settings.DEBUG` | K8s/负载均衡被骗；日志泄漏用户消息与切片正文 | 分项探活 MySQL/PG/Redis 并返回 503；生产关闭 echo；敏感字段脱敏 |
| P1-11 | 启动日志 emoji 导致 Redis 误报（新增） | `main.py:38-46` 成功分支打印 `✅`，Windows cp936 抛 `UnicodeEncodeError` 被 `except Exception` 吃掉 | 明明连上了却显示"未连接（降级）"，误导排障 | 日志去 emoji 或统一 UTF-8；连接检查与日志打印分开 try |
| P1-12 | SSE 走 GET query、token 在 localStorage、无吊销 | `routers/v1/chat.py:148`、`agent.py:82`；`useSSE.ts:24`；`security.py` 无 jti | 消息进访问日志/代理日志；XSS 可窃 token；登出无效 | 改 POST + `text/event-stream`；refresh 轮换 + jti 吊销；token 移出 localStorage |
| P1-13 | 限流实现与注释不符、fail-open、双层重复 | `rate_limiter.py:22-25` 称滑动窗口，`:114` 是固定窗口；`:108-110` fail-open；`routers/v1/__init__.py:59-69` 又做一层 | 窗口交界双倍放行；撞库无防护；Redis 故障时每请求卡 3s | 真滑动窗口（ZSET/令牌桶）；登录失败锁定（5 次/15 分钟）；故障短路；合并限流层 |
| P1-14 | LLM 无超时/重试、Embedding 不分批 | `llm_service.py:26-29` 未传 `timeout`；无重试；`embeddings.py:108-114` 一次发全部切片 | 上游 429/5xx 直接失败；大文档 embedding 超限 | `timeout` + tenacity 指数退避重试；embedding 分批；usage 落库 |

> **状态（2026-10-28）**：P1-1 / P1-2 已关闭（B5，见 [B5 批次修复记录](#b5-批次修复记录2026-10-28)）；P1-9 / P1-10 / P1-12 / P1-13 已关闭（B4，见 [B4 批次修复记录](#b4-批次修复记录2026-10-28)）；P1-5 / P1-6 / P1-7 / P1-14 已关闭（B3：token 预算、Agent 真流式、工具可执行性、上游超时与重试，见 [B3 批次修复记录](#b3-批次修复记录2026-10-28)）；P1-3 / P1-4 已关闭（B2：删库先清 PG 切片 + 孤儿清扫脚本；会话列表批量 count + 发消息刷新 `updated_at` + 详情不再静默截断）；P1-8 已关闭（B1）；P1-11 已关闭（P0-1 顺手）。其余 P1 待处理，执行顺序见 [FIX_PLAN.md](FIX_PLAN.md)。

### B3 批次修复记录（2026-10-28）

**本批次关闭 4 项**：P1-14（先行）、P1-5、P1-6、P1-7。

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P1-14 | 无超时、无重试；embedding 一次提交全部切片 | 超时 + 指数退避（只重试超时/429/5xx）+ embedding 按 32 条分批；见下方细节 |
| P1-5 | 上下文固定 20 条；`count_tokens` 写了没人用 | `load_history()` 先按条数取候选，再按 `CONTEXT_MAX_TOKENS=3000` 从最旧的丢弃；保留至少 1 条；裁剪记 `context_trim_total`。`count_tokens` 改为 CJK≈1 字/token（旧实现 `len//4` 把中文低估到 25%，预算形同虚设） |
| P1-6 | Agent 把完整回答攒好再一次性推（首 token 延迟 = 整段生成时间） | 新增 `LLMService.chat_with_tools_stream()`：一次流式调用同时拿"回答片段"和"工具调用"；文本边生成边推 `event: token`，工具参数按 `index` 分片拼装。**只重试建流**，读流不重试（否则前端会收到重复片段） |
| P1-7 | 数据库工具只有 schema 没有 executor，却被交给 LLM | 新增 `_TOOL_EXECUTORS` 注册表；`get_tool_definitions()` 只暴露有实现的工具；管理端加"仅展示"标签与说明，避免让模型调一个必然失败的工具 |

**P1-14 细节**：P0 清零后，唯一还会让用户直接看到失败的就是"上游抖一下"——429/5xx/超时。
原来既没有超时（请求会一直挂着），也没有重试（一次抖动 = 一次用户可见的 502）。

| 项 | 原来 | 现在 |
|---|---|---|
| 超时 | `AsyncOpenAI(...)` 未传 `timeout`，用 SDK 默认值 | `LLM_TIMEOUT_SECONDS=60` / `EMBEDDING_TIMEOUT_SECONDS=30` |
| 重试 | 无 | 新增 `app/core/retry.py::call_with_retry`：指数退避 + ±30% 抖动，**只重试**连接失败/超时/429/5xx，4xx 立即失败 |
| SDK 重试 | SDK 默认重试 2 次 | 显式 `max_retries=0`，避免与自研重试**相乘** |
| Embedding 分批 | 一次提交全部切片（172 个切片一次请求） | 按 `EMBEDDING_BATCH_SIZE=32` 分批，每批独立重试，顺序按原位置回填 |
| 流式重试 | 无 | **只重试"建流"**，读流中途失败不重试（吐出去的内容无法回滚，重试会产生重复片段） |
| 可观测 | 无 | `external_retry_total{operation}`、`external_call_total{status}`、`llm_tokens_total{kind}`、`llm_latency{operation}`、`llm_first_token_latency`、`embedding_batches_total` |

**验收证据（真实调用）**

```text
[P1-14] 上传 78,088 字文档 → 172 个切片 → embedding 分 6 批完成（172/32 → 6 批）
        status=completed / 耗时 5.0s
        一次真实问答 → /health: llm_tokens_total{prompt}=23, {completion}=1
                                 llm_latency{chat}=1129.73ms

[P1-6]  Agent 真流式：token 事件数 = 83（修复前恒为 1）
        tool_call / tool_result 各 1，无 error，有 done
        llm_first_token_latency ≈ 491ms
        流式路径下工具参数分片拼装正确（calculator 拿到 {"expression":"1024*768"}）
```

回归测试：`test_p1_14_reliability.py`（11 个用例，用真实 openai 异常对象 + httpx.Response 构造 429/500/400）
与 `test_b3_context_streaming_tools.py`（12 个用例）；全套 `pytest` **94 passed**。

**没做的**：熔断/降级到备用 provider 属于 P2-4（模型切换与 fallback）；结构化日志里带 request_id 属于 B4-1。


---

### B4 批次修复记录（2026-10-28）

**本批次关闭 4 项**：P1-9（结构化日志）、P1-10（真实探活）、P1-12（SSE 安全 + refresh 轮换）、P1-13（限流与登录锁定）。

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P1-9 | 全仓无 logging 配置，启动靠 print；日志没有 request_id，一次请求跨 5 层无法串联 | 新增 `app/core/logging.py`（dictConfig + 人读/JSON 双格式 + 10MB×5 轮转）、`request_context.py`（ContextVar）、`middleware.py`（纯 ASGI：透传/生成 `X-Request-ID`、写响应头、记 method/path/status/duration）。启动日志全部改 logger；LLM 调用的 token 用量与延迟进指标 |
| P1-10 | `/health` 返回常量，数据库挂了也 healthy；`echo=DEBUG` 会把 SQL 参数打出来 | `app/core/health.py` 并行探活 MySQL/PG/Redis（1.5s 超时、分项耗时）：硬依赖 down → 503，Redis down → degraded 仍 200（缓存/限流可降级，不该摘实例）；SQL echo 与 DEBUG 解耦为 `DB_ECHO_SQL=False` |
| P1-12 | 聊天/Agent 的 SSE 走 GET+query（消息进访问日志、受 URL 长度限制）；refresh 不轮换，登出无效 | 两个流式接口改为 **POST + JSON body**（前端 `useSSE` 支持 POST、Chat/AgentChat 同步改造）；refresh 带 `jti` 并在服务端登记，**用一次即轮换**，重放旧票 401；新增 `POST /auth/logout` 吊销 refresh |
| P1-13 | 注释称滑动窗口实际是固定窗口（交界处双倍放行）；Redis 故障时每个请求白等 3s；登录无失败锁定 | 改成**双窗口加权**滑动窗口（当前 + 上一窗口×剩余权重）；Redis 失败后进入 30s 冷却（不再每请求重连）；登录连续失败 5 次锁 15 分钟（计数在 Redis，降级时 fail-open），并用假哈希对齐"用户不存在"的耗时防枚举 |

**本批次新发现**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-12 | **SQL 日志泄漏用户消息**：即使 `echo=False`，`sqlalchemy.engine` logger 在 INFO 级别仍会打印带参数的 SQL —— 实测把用户提问原文写进了日志文件 | 🔴 高 | ✅ 已修：logger 默认 WARNING，仅 `DB_ECHO_SQL=true` 时降到 INFO；E2E 用标记串复查为 0 处泄漏 |
| N-13 | 前端 `SessionDetail` / token 存储仍是 localStorage | 🟡 中 | ⬜ 未修：access token 移出 localStorage 需要配合 refresh-on-boot 与 CSRF 策略，属独立改造（已记入 FIX_PLAN 的 B7） |

**验收证据（真实运行）**

```text
[P1-10] /health → 200 / healthy
        mysql up 24.9ms | postgres up 33.9ms | redis up 3.3ms

[P1-9]  请求头 X-Request-ID: trace-b4-001 → 响应头原样返回
        日志中可按 request_id 串起 7 行（含 middleware 访问日志 + SQL + 业务日志）

[P1-12] POST /chat/sessions/{id}/messages/stream → 200，SSE 有 done
        POST /agent/chat/stream → 200，无 error
        refresh：第一次 200（新票≠旧票）→ 重放旧票 401「刷新令牌已失效」
        logout 200 → 再用该 refresh 401
        日志中检索消息标记串（B4-POST-SSE-MARKER）：0 处泄漏

[P1-13] 连续 5 次错误密码 → 第 6 次 429「登录失败次数过多，请 15 分钟后再试」
        锁定期内用正确密码 → 429（锁定优先于校验）
        metrics: login_failed_total=5, login_locked_total=2,
                 refresh_token_store_total{rotated}=2, {revoked}=1
```

回归测试：`backend/tests/test_b4_observability_and_security.py`（16 个用例，不依赖 DB/Redis/网络）；
全套 `pytest` **110 passed**。

**没做的**：access token 黑名单（登出后 30 分钟内仍有效，已在 FIX_PLAN 记录）；SSE 多行 data 与断线重连属 P2-11。

---

### B5 批次修复记录（2026-10-28）

**本批次关闭 2 个 P1 + 2 个长期遗留**：P1-1（HNSW 索引）、P1-2（数据库迁移）、
P0-1 遗留（失败原因持久化）、P0-8 遗留（内容级去重）。

| 项 | 原问题 | 修复后的行为 |
|---|---|---|
| P1-2 | `alembic/versions/` 为空，schema 靠 `create_all`（只建不改）；一个 env.py 只看得到 MySQL | `alembic.ini` 拆成两段（默认 MySQL / `-n postgres`），`env.py` 按段选择 metadata 与 URL（支持 `ALEMBIC_DATABASE_URL` 覆盖）；基线迁移用**临时空库**自动生成（MySQL 6 张表 + PG `document_chunks`），对已有库改为 `stamp`；之后所有变更走 revision |
| P1-1 | 无向量索引，检索全表扫描 + 逐行余弦 | PG 迁移建 `HNSW(embedding vector_cosine_ops, m=16, ef_construction=64)`；检索前 `SET LOCAL hnsw.ef_search`（默认 40，可配 `HNSW_EF_SEARCH`） |
| P0-1 遗留 | 失败原因只在响应和日志里，过几天回看只知 `failed` 不知原因 | `documents.error_message` 列 + 迁移；`_mark_failed` 落库、成功时 `clear_error` 清空；`DocumentResponse` 暴露该字段，列表接口也能读到 |
| P0-8 遗留 | 同一文件重复上传会重复切片、重复花 embedding 钱 | 流式落盘时顺带算 sha256 存入 `documents.file_hash`；上传前按 `(kb_id, hash)` 查重（忽略 failed 文档），命中直接 409 并删掉刚写的文件 |
| P2-6 | 无评测集与指标，`chunk_size/阈值/top_k` 全是拍脑袋 | `data/eval/`（8 篇语料 + 36 题，含 2 道无答案题）+ `scripts/evaluate_rag.py`：recall@1/3/5、MRR、无答案误召回率、延迟分位，支持 chunk 网格与**阈值扫描** |
| P2-7 | 测试只有零散文件，无夹具、无接口级用例、无覆盖率门禁 | `tests/conftest.py`（ASGI 直连 + 依赖覆盖 + 真实库集成夹具）、`test_api_contract.py`（11 个）、`test_integration_api.py`（4 个，无库自动跳过）、`.coveragerc` 门禁 65%（实测 68%） |

**本批次新发现**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-14 | **写入在响应发出之后才提交**：FastAPI 的 `yield` 依赖要等响应发完才 commit，客户端紧接着的"再传一次同一文件"读到旧快照，去重因此偶发失效（实测两次上传都成功入库） | 🔴 高 | ✅ 已修：上传在返回前显式提交（先 PG 后 MySQL，避免"completed 但没向量"），E2E 复查去重稳定生效 |
| N-16 | **相似度阈值 0.7 把八成正确检索挡在门外**：评测显示纯检索 recall@1 = 94%，套上 0.7 阈值后只剩 **24%** —— 用户提问时模型经常拿不到资料，只能凭训练知识回答（表现为答非所问或“没找到相关内容”），而这在日志里完全看不出来 | 严重度：高 | ✅ 已修：阈值改为**实测**的 0.55（recall@1 85%，无答案题仍不误召回）；`--sweep` 可复现整张表 |
| N-15 | `alembic.ini` 里写中文注释 → Windows 下 configparser 用 GBK 解码直接崩（`UnicodeDecodeError`） | 🟡 低 | ✅ 已修：该文件保持纯 ASCII，中文说明移到 `env.py` 与文档；已在 README 注明这条约束 |

**验收证据（真实运行）**

```text
[迁移] 空库 upgrade head
       MySQL: users / knowledge_bases / documents / chat_sessions / chat_messages / agent_tools
       PG   : document_chunks + alembic_version，embedding 类型 vector(1024)
       已有库：alembic stamp head / -n postgres stamp head 后 current 均为 head

[P1-1] HNSW 索引：CREATE INDEX ix_document_chunks_embedding_hnsw
                   ON document_chunks USING hnsw (embedding vector_cosine_ops)
                   WITH (m='16', ef_construction='64')
       查询计划（enable_seqscan=off）：
         Limit -> Index Scan using ix_document_chunks_embedding_hnsw

[去重] 同一内容上传两次（第二次改名）：第一次 200 / 第二次 409
       「该文件内容已存在于本知识库（dup.txt，状态 completed）」，文档数仍为 1

[P2-6] 评测（8 篇语料 / 36 题）
       纯检索 recall@1 = 94.1%，recall@3 = 100%，MRR = 0.971
       阈值 0.70（原默认）→ recall@1 = 23.5%   ← 原配置是错的
       阈值 0.55（新默认）→ recall@1 = 85.3%，无答案误召回 0%
       阈值 0.50 → recall@1 = 94.1%，但无答案题一半会被塞进上下文
       chunk 300/30 比 500/50 略好（recall@1 94% vs 85%），代价是切片 16 vs 9

[失败原因] 空文件上传 → status=failed，
           document.error_message = "文档解析失败：文件内容为空"
           刷新列表后仍能读到该字段
```

回归测试：`test_b5_migration_hooks.py`（5 个）、`test_api_contract.py`（11 个）、
`test_integration_api.py`（4 个，需真实库）、`test_eval_harness.py`（7 个，含指标算法与数据集完整性）；
全套 `pytest` **137 passed**；`pytest --cov=app` 覆盖率 **68%**（门禁 65%）。

---

### B6 批次修复记录（2026-11-08）

**本批次关闭 3 项**：P2-4（模型不生效 + 无 fallback）、P2-9（前端假数据）、D-3（备份与恢复）。

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P2-4 | `model_name` 存进会话却从不使用 —— `LLMService` 永远读 `settings.LLM_MODEL_NAME`，用户在会话里换模型**完全没效果** | 模型按 **请求 > 会话 > 配置** 生效：请求体新增 `model_name`，四个 LLM 方法都接受 `model` 参数；`resolve_model_name()` 校验白名单（未知模型退回默认 + 记指标，不抛 400）；新增 `LLM_FALLBACK_MODELS` 主备切换（只对超时/429/5xx 切换，4xx 不切）；新增 `GET /chat/models` 与前端下拉；SSE `done` 事件回传实际模型 |
| P2-9 | Dashboard 的"文档"卡片 `const [docCount] = useState(0)` —— 定义了、展示了、从未请求；用户管理展示后端不存在的 `email` 字段 | 新增 `GET /api/v1/stats/overview`（按当前用户：知识库/文档/失败文档/会话/消息）；Dashboard 改用真实数字，失败文档 >0 时飘红提示；`User` 模型本来就没有 email，直接删掉那一列 |
| P2-2 | 没有错误码表、接口没有 summary/description、生产默认开着 `/docs`（等于公开全部接口结构） | `docs/API_ERRORS.md`：code → HTTP → 含义 → 触发场景 → 客户端动作，含 SSE 错误约定；`/docs`、`/redoc`、`/openapi.json` 改为 `DOCS_ENABLED` 控制（None 跟随 DEBUG，生产默认关）；8 个 OpenAPI 标签 + **31 个接口全中文 summary** + 每个业务接口挂统一错误响应（401/403/404/422/429/503） |
| D-3 | `database-backups/` 只有一份 PG dump，**MySQL 一条备份都没有**，无恢复脚本、无演练 | `scripts/backup_all.py`：mysqldump（一致性快照不锁表）+ pg_dump（本机没有则走 `docker exec`）+ `manifest.json`（大小/哈希/**逐表行数**）+ 保留 7 份；`scripts/restore_all.py`：`--drill` 恢复到临时库对数、`--yes` 真恢复；[专项文档](BACKUP_RESTORE.md) |

**本批次新发现**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-17 | 集成测试把自己 429 掉了：整套跑下来几十秒内上百次请求，IP 限流（60/min）触发，`test_logout_revokes_refresh_token` 间歇失败 | 中 | ✅ 已修：新增 `RATE_LIMIT_ENABLED` 开关，`conftest.py` 在导入 app 前置为 false；顺手修掉中间件里 `/openai.json` 拼写错误（应为 `/openapi.json`） |
| N-18 | `pg_dump --clean` 单独使用**不生成 `IF EXISTS`**，恢复到空库报 `index "ix_document_chunks_embedding_hnsw" does not exist` | 中 | ✅ 已修：dump 时加 `--if-exists`，演练通过 |

**验收证据（真实运行）**

```text
[P2-4] GET /chat/models → models=['deepseek-chat','deepseek-reasoner'] default=deepseek-chat
       指定合法模型 → done 事件 {"model":"deepseek-chat"}
       指定 "gpt-9-ultra-not-exist" → HTTP 200，回答正常，done.model 退回 deepseek-chat，
       指标 llm_model_fallback_total{reason=not_allowed}=1
       单测覆盖：503 切换备用模型（calls=[primary, backup]）、400 不切换

[P2-9] GET /stats/overview
       初始：{kb:1, doc:0, session:1, message:4, failed:0}
       上传文档后：doc=1 failed=0
       上传空文件后：doc=2 failed=1   ← 失败可见性与统计串起来了

[P2-2] DEBUG=false（生产模式）：/docs、/redoc、/openapi.json 全部 404 且仍是统一信封
       /health 200，X-Request-ID 照常返回
       DEBUG=true（开发模式）：/docs 200，openapi 含 8 个标签 / 23 条路径，
       每个业务接口都有 401/403/404/422/429/503，全部 summary 为中文

[D-3]  python scripts/restore_all.py --drill
       备份 1.39s / 恢复 1.97s
       users 60/60 · knowledge_bases 6/6 · documents 4/4 · chat_sessions 2/2
       chat_messages 6/6 · agent_tools 3/3 · document_chunks 4/4
       演练通过：行数与源库一致，临时库已清理
```

回归测试：`test_p2_model_and_stats.py`（7 个）、`test_p2_api_contract.py`（6 个：docs 开关三态、标签、每个接口的错误响应、信封字段、404/422 仍是信封）；全套 `pytest` **150 passed**。

---

### B7 批次修复记录（2026-11-08）

**本批次关闭 2 项**：P2-10（Markdown / 引用 / 停止 / 重试）、P2-11（SSE 解析与断流）。

| ID | 原问题 | 修复后的行为 |
|---|---|---|
| P2-11 | `useSSE` 逐行切分：不按空行分帧、多行 `data:` 只取第一行；流断了既没 `done` 也没 `error` 时**安静结束**；无法中断 | 抽出 `lib/sseParser.ts`（按空行分帧、多行 `data:` 用 `\n` 拼接、支持 `\r\n`、忽略心跳注释、`flush()` 吐出残帧）与 `lib/sseClient.ts`（消费流：区分 done / error / aborted / http_error；没收到结束信号 → 报「连接中断」；**仅在还没吐出 token 时**自动重试 1 次，避免重复内容）；hook 只剩翻译层 |
| P2-10 | 回答是纯文本 `pre-wrap`；没有任何引用展示；生成中不能停；失败只能手动重新输入 | `react-markdown` + `remark-gfm` 渲染回答（代码块/表格样式）；后端 `event: rag` 增带 `citations`（文档名 + 段号 + 相关度 + 160 字片段），前端渲染**引用卡片**；生成中显示**停止生成**（保留已收到内容并标注）；失败/停止后显示**重试**（去掉上一轮问答后原样重发） |

**新增的测试基建**

- 前端首次具备单测：`npm test`（vitest），19 个用例
  - `sseParser.test.ts` 11 个：多行 data、跨分片、`\r\n`、心跳、无 data 帧、flush 残帧、非法 JSON 降级
  - `sseClient.test.ts` 8 个：正常结束、断流报错、未吐 token 时重试成功、吐过 token 不重试、HTTP 非 2xx、`event: error`、主动停止、网络异常重试耗尽

**验收证据（真实运行）**

```text
[P2-10] POST /chat/sessions/{id}/messages/stream（带知识库）
        event: rag
        data: {"context_length":135,
               "citations":[{"document_id":7,"document_name":"差旅制度.md",
                             "chunk_index":0,"similarity":0.7655,
                             "snippet":"# 差旅制度\n\n## 住宿标准..."}]}
        最后一帧：{"token":"","done":true,"model":"deepseek-chat"}

[P2-11] 前端 19 个单测（vitest）全部通过；构建 0 error、oxlint 0 error
        其中「断流且未吐 token → 自动重试一次并成功」用假 fetch 验证了 calls==2
        「吐过 token 后断流 → 不重试」验证了 calls==1（防止重复内容）
```

回归测试：后端 `test_p2_citations_and_sse.py`（8 个：引用映射/截断/降级/只查一次库、`rag` 事件带 citations）；
全套后端 **158 passed**；前端 **19 passed**。

**没做的**：`Last-Event-ID` 断点续传（重试是整轮重发）—— 需要后端支持按事件 ID 回放，已记入 README 限制表。

---

### D-1 容器化记录（2026-11-09）

**交付物**：`backend/Dockerfile`、`backend/.dockerignore`、`frontend/Dockerfile`、
`frontend/.dockerignore`、`frontend/nginx.conf`、`docker-compose.yml`、根目录 `.env`（gitignore）、
[docs/DOCKER_DEPLOY.md](DOCKER_DEPLOY.md)。

| 项 | 结果 |
|---|---|
| 后端镜像 | 两阶段；构建上下文 **214.5MB → 918KB**；镜像 CONTENT SIZE **120MB**；非 root（`USER app`）+ `HEALTHCHECK` + uploads/logs 目录 chown |
| 前端镜像 | 两阶段（node 构建 → nginx 托管）；**21.4MB**（node_modules 189MB 完全没进去）；`ARG VITE_API_BASE_URL=/api/v1` 参数化 |
| compose | 5 服务 + healthcheck + `depends_on: service_healthy`；4 个命名卷；**数据库不发布端口**；项目名 `ai-kb` 前缀隔离 |
| 迁移 | backend 启动命令里跑 `alembic upgrade head` + `-n postgres upgrade head`，首次启动自动建表/建 HNSW 索引 |

**验收（真实运行）**

```text
docker compose ps
  backend   Up (healthy)   8000/tcp
  frontend  Up (healthy)   0.0.0.0:80->80/tcp
  mysql     Up (healthy)   3306/tcp, 33060/tcp
  postgres  Up (healthy)   5432/tcp
  redis     Up (healthy)   6379/tcp

backend 日志：
  Running upgrade  -> e24e5d995a17, baseline mysql
  Running upgrade e24e5d995a17 -> b1a2c3d4e5f6, add documents.error_message and documents.file_hash
  Running upgrade  -> a418d6370212, baseline postgres
  Running upgrade a418d6370212 -> c2b3d4e5f6a7, add HNSW index
  向量列维度校验通过 column=vector(1024) / Redis 已连接 / Uvicorn running

容器内 /docs -> 404（DEBUG=false，P2-2 生效）

全链路冒烟（经 nginx:80）：
  认证 OK → /users/me 200 → 建库 id=1 → 上传 completed/1 chunk
  → 流式问答 rag=True done=True error=False
  → 回答「根据文档，一线城市住宿上限为每晚 **600 元**。」
  → /stats/overview {kb:1, doc:1, failed:0, session:2, message:2}
```

**踩坑记录（已写入 DOCKER_DEPLOY.md）**

| 坑 | 现象 | 根因 |
|---|---|---|
| N-19 | `docker run` 后 `docker exec` 报 `No such container` | nginx **启动时**解析 `proxy_pass` 主机名，单容器无 `backend` → `[emerg]` 退出 |
| N-20 | 本机 `localhost` 请求返回 **502** | 客户端（httpx/requests）默认读 Windows 系统代理，`localhost` 被走 Clash |
| N-21 | `docker build` 反复 `fetch oauth token: EOF` / 直连污染 IP | 代理刚重启时转发层未就绪；且 DNS 被污染 |

**明确没做（生产部署）**：域名/HTTPS、多副本与负载均衡、镜像 digest 固定与私有 registry、
指标与日志采集、备份异地加密、回滚策略。已在 DOCKER_DEPLOY.md 末尾列成表格，不在简历里宣称"已部署"。

---

### P2-8 代码质量门禁记录（2026-11-09）

| 项 | 修复前 | 修复后 |
|---|---|---|
| `ruff check .` | **88 条**（unsorted-imports 29、unused-import 20、deprecated-import 6、zip-without-strict 5、E402 5 …） | **0 条** |
| `mypy app` | **45 条** | **0 条**（71 个文件；7 个框架噪音模块按白名单冻结并注明理由） |
| 配置 | 无 `pyproject.toml` | `[tool.ruff]` 保守规则集 + `[tool.mypy]` per-module overrides |

**类型检查抓到的真 bug（不是风格问题）**

| # | 问题 | 后果 |
|---|---|---|
| 1 | `chat_service._retrieve_rag_context` 空知识库分支 `return ""` | 选空知识库提问 → 解包崩溃（500） |
| 2 | `POST /agent/chat` 传了 `model_name=` 但 `AgentService.chat()` 没这参数 | 非流式 Agent 调用 **必然 TypeError** |
| 3 | `zip()` 未写 `strict`（embeddings / document_repo / 2 个脚本） | 长度不一致时静默错位，把 A 的向量写给 B |
| 4 | `lambda` 捕获循环变量（主备切换） | 重试时用的是"最后一个模型"，等于备份没生效 |

**明确没做**：`ruff format`（会重排 49 个文件，纯格式 diff 会淹没真实改动，建议单独提交）；
pre-commit（本地钩子可绕过，CI 才是硬约束）。理由写在 [CODE_QUALITY.md](CODE_QUALITY.md)。

---

### D-2 CI 门禁记录（进行中）

**流程**：`.github/workflows/ci.yml`，3 个 job（backend / frontend / docker），推送到 `main` 或 PR 触发。

| 轮次 | 结果 | 失败点 | 根因 |
|---|---|---|---|
| #1 | ❌ | backend「静态检查」0 秒失败 | **ruff 没进依赖清单**：P2-8 那次改 `requirements.txt` 的替换没命中，本地手工装过所以看不出来。CI 里 `ruff` → `command not found` |
| #2 | ❌ | backend「测试 + 覆盖率」 | **N-22** `AsyncOpenAI(api_key="")` 构造即抛 `OpenAIError`，CI 没有 `LLM_API_KEY` → 6 个用例全挂 |
| #3 | 待验证 | — | 已修：拆 `requirements-dev.txt`、LLM key 容错、compose `env_file` 可选 |

**本批次新发现**

| ID | 问题 | 严重度 | 状态 |
|---|---|---|---|
| N-22 | **`LLMService` 在 `LLM_API_KEY` 为空时构造即抛异常**：`AsyncOpenAI` 不接受空 api_key。于是任何 new 一个 `LLMService` 的路径（`ChatService` 构造、Agent 构造、相关测试）**在配置缺失时直接崩**，而不是"调用时返回清晰错误" | 🔴 高（生产隐患：漏配一个环境变量服务就起不来） | ✅ 已修：`api_key=... or "unset"` + `is_available` 标志 + 启动告警；CI 里显式给假 key |
| N-23 | **`docker-compose.yml` 的 `env_file: [.env]` 是必需的**：没有 `.env` 的环境（CI 只做 `config` 校验、或新克隆的仓库）执行 `docker compose config` 直接 `exit 1` | 🟡 中 | ✅ 已修：改为 `path: .env, required: false`（Compose 2.24+），实测无 `.env` 时 `exit 0`、有 `.env` 时变量照常注入 |

**和"遗留 bug"的关系（明确澄清）**

| CI 红灯 | 与剩余 5 项（P2-1/3/5/12、D-2）有无关系 | 说明 |
|---|---|---|
| ruff 未安装 | **无关** | 是 P2-8 改造时的清单疏漏，不是历史遗留 |
| LLM key 空即崩 | **无关**（是新发现的 N-22） | 之前全靠本地 `.env` 兜着，任何新环境都会踩 |
| compose env_file 必需 | 弱相关 | D-1 的编排没考虑"没有 `.env`"的环境 |

反过来也要说清：**CI 全绿 ≠ 没有 bug**。以下已知问题 CI 不会报：

- `P2-1` 根目录散落脚本（ruff 会扫，但"该不该存在"它不管）
- `P2-3` 软删除/审计、`P2-5` prompt 治理、`P2-12` 压测/反馈/License —— **功能缺失，没有测试断言**
- `N-7`（`register_vector` 协程未 await，只产生 RuntimeWarning）、`N-11`、`N-13` —— 已记录、明确暂不修

> 想让它报：修掉 N-7 之后，把 `pytest` 加上 `-W error::RuntimeWarning`，这类"静默的技术债"就会变成红灯。

---

## 4. P2 优化清单（12 条）

| ID | 问题 | 修复要点 |
|---|---|---|
| P2-1 | 根目录散落临时脚本与 token 文件 | 迁到 `scripts/dev/` 并加危险操作确认；删除 `test_token.txt` |
| P2-2 | 无 API 契约文档/错误码表；生产默认开 `/docs` | 补 OpenAPI `summary/description/examples`、错误码表；生产关闭或鉴权 `/docs` |
| P2-3 | 无软删除/审计日志 | `deleted_at` 或审计表（who/what/when/before） |
| P2-4 | `model_name` 只存不生效；无 provider fallback | 按会话/请求传 model；配置 provider 列表 + 故障切换 |
| P2-5 | prompt 硬编码、无版本管理、无注入防护 | prompt 模板文件 + 版本号；明确"文档是数据不是指令"；输出过滤 |
| P2-6 | 无评测集与指标 | 25–30 条 QA → `recall@k`/`MRR` + LLM-as-judge；CI 设回归阈值 |
| P2-7 | 测试只有 5 个文件且跑不起来 | 装 pytest/pytest-asyncio；`conftest.py` + `httpx.AsyncClient`；mock LLM/Embedding；覆盖率 ≥60%（核心链路 ≥80%） |
| P2-8 | 后端无 lint/type 门禁 | `pyproject.toml` + ruff + mypy + pre-commit |
| P2-9 | 前端 Dashboard 文档数恒 0；用户管理显示不存在的 email | 请求真实统计；去掉或补字段 |
| P2-10 | 无 Markdown 渲染、引用、停止生成、重试 | 加 `react-markdown` + 引用卡片 + `AbortController` 停止 + 重试 |
| P2-11 | `useSSE` 只按 `\n` 切分，不支持多行 `data:`/断线重连 | 按 SSE 规范解析（空行分帧、多 `data:` 拼接）；加事件 ID 与重连 |
| P2-12 | 无压测基线、无反馈闭环、无 License | k6/locust 脚本 + p95/吞吐基线；反馈表与接口；确定 License |

> **状态（2026-11-08）**：P2-4 / P2-9 已关闭（模型生效 + 真实统计，见 [B6 批次修复记录](#b6-批次修复记录2026-11-08)）；P2-6 已关闭（评测集 + recall@k/MRR + 阈值扫描）；P2-7 已关闭（conftest + 接口级/集成测试 + 覆盖率门禁 65%，实测 68%）；P2-2 已关闭（错误码表 + 文档开关 + 接口 summary）；P2-10 / P2-11 已关闭（Markdown/引用/停止/重试；SSE 分帧解析 + 断流检测 + 有限重试）；P2-8 已关闭（ruff/mypy 门禁，88+45 → 0）。其余 4 项待处理。

---

## 5. 功能级清单：改什么、补什么、优化什么

### 5.1 需要「修改」（有 bug，现在是错的）

| 功能 | 现状 | 目标 |
|---|---|---|
| 聊天上下文组装 | 当前问题进 prompt 两次 | 只出现一次 |
| Agent 知识库范围 | 选中的库不生效 | 严格限定在选中库 |
| Agent 迭代上限 | 超限返回空 | 有兜底总结 |
| Agent 对话页 | 流式结束答案消失、每问新建会话 | 消息保留、会话连续 |
| 上传处理 | 失败仍 `completed`；文件名可穿越；同步阻塞 | 失败可见；路径安全；异步化 |
| 登录/权限错误码 | 401/403/404 全变 400 | 与语义一致 |
| Redis 启动日志 | 成功也报"未连接" | 真实反映状态 |
| Dashboard 文档数 | 恒为 0 | 真实统计 |
| 用户管理 email | 显示后端不存在的字段 | 移除或补字段 |

### 5.2 需要「完善」（半成品）

| 功能 | 缺口 |
|---|---|
| RAG 检索 | 无 ANN 索引、无 rerank、无引用回传、`threshold=0.7` 无依据、失败静默；**两条检索路径行为不一致**：`retrieve()`（普通聊天）不做阈值过滤，`retrieve_with_details()`（Agent 工具）做过滤 |
| Agent 工具 | 动态工具无 executor；注册表是全局变量；工具结果无超时/截断策略 |
| SSE | GET + query；非真流式；无心跳；异常不断流友好 |
| 会话管理 | `updated_at` 不更新；详情截断 100 条；无重命名入口 |
| 文档处理 | 无去重、无可视化进度、无重试、HTML 未解析、切片无页码/标题元数据 |
| 管理端 | 只有启用/禁用；无审计、无用量统计 |
| 缓存 | 只有文档切片与 LLM 响应；无语义缓存/失效策略说明 |

### 5.3 需要「优化」（性能与体验）

- 检索：HNSW + `ef_search` 调参 + 混合检索（BM25 + 向量）+ rerank。
- 数据库：会话/KB 列表去 N+1；分页改游标；PG 侧按 `knowledge_base_id` 建部分索引。
- 上下文：token 预算裁剪，超预算记指标。
- 上传：后台任务 + 分批 embedding + 断点续传。
- 前端：虚拟滚动、骨架屏、ErrorBoundary、`any` 收敛、Markdown。

### 5.4 建议「新增」（企业级能力，按价值排序）

1. **RAG 评测体系**（数据集 + recall/MRR + 回归门槛）—— 最高价值，直接决定"能不能说清效果"。
2. **可观测性三件套**（结构化日志 + 指标 + 成本统计）。
3. **回答引用与反馈闭环**（点击溯源、赞/踩、纠错入库）。
4. **容器化与 CI**（Compose + GitHub Actions + 迁移 + 备份恢复演练）。
5. **多租户与配额**（租户隔离、按用户计费/限流、用量报表）。
6. **prompt 版本管理与注入防护**。
7. **审计日志与软删除**（合规）。

---

## 6. 建议修复顺序（按收益/成本）

| 批次 | 目标 | 包含 | 预估 |
|---|---|---|---|
| B1 止血 | 让系统"不骗人" | P0-1/2/4/5/6 + P1-11 | 2–3 天 |
| B2 可信 | 让数据与权限正确 | P0-3/7/8/9 + P1-3/4/5/14 | 3–5 天 |
| B3 可观测 | 让问题能被发现 | P1-9/10/12/13 | 2–3 天 |
| B4 可评测 | 让效果能被证明 | P2-6/7 + P1-1/2 | 3–4 天 |
| B5 可交付 | 让别人能跑起来 | README（已完成）+ Dockerfile/Compose/CI/备份演练 | 3–5 天 |
| B6 产品化 | 让用户愿意用 | P2-9/10/11 + 引用/反馈 | 3–4 天 |

> 规则：**P0 未清零不写新功能**；每个修复必须带一条可执行的验收命令或测试。

---

## 7. 企业级验收清单（Definition of Done）

- [x] `DocumentChunk.embedding` 为 `VECTOR(1024)`，DB 列一致，`count(*) = count(embedding)`。（P0-9/存量补齐，2026-10-28：实测 2/2、维度全 1024）
- [x] 断 Embedding key 上传 → 文档 `failed`，前端可见；停 PG 问答 → 明确错误事件。（P0-1，2026-10-28）
- [ ] 一条命令输出 `recall@5 = 0.xx`，有 baseline 与改进对比。
- [x] `EXPLAIN` 显示走 HNSW 索引。（P1-1，2026-10-28：`Index Scan using ix_document_chunks_embedding_hnsw`）
- [x] 断言「当前问题在 prompt 中出现 1 次」的单测通过。（P0-2，2026-10-28）
- [x] 选 A 库提问，检索结果只来自 A（P0-3，2026-10-28：单测 + E2E 各一次）
- [x] Agent 连续追问：消息不丢、会话只有一个。（P0-5，2026-10-28；E2E 验证 2 轮 + 前端构建通过，工具卡片展开属前端行为需人工点一眼）
- [x] 错误登录 HTTP 401、不存在 404（P0-6，2026-10-28；E2E + 9 个参数化单测覆盖 400/401/403/404/422/429/500/502/503 映射）
- [x] 空库 `alembic upgrade head` 可建 MySQL + PG 全表。（P1-2，2026-10-28：临时空库实测）
- [x] 删 KB 后 `document_chunks` 无孤儿记录。（P1-3，2026-10-28：E2E + 孤儿清扫脚本幂等验证）
- [x] 一条请求的日志可用 `request_id` 串起；依赖不可用时 `/health` 返回 503。（P1-9/P1-10，2026-10-28：E2E 验证 request_id 串联；503 由单测覆盖探活失败路径，未真的停容器）
- [ ] `pytest` 全绿，覆盖率 ≥60%（核心链路 ≥80%）。（当前 53 个用例全绿，覆盖率门槛未接）
- [ ] `docker compose up` 从零起全栈；备份恢复演练通过。
- [ ] README 状态表与代码真实一致，无虚假指标。

---

## 附录：本次复核的只读命令

```powershell
# 依赖版本
cd backend
..\.venv\Scripts\python.exe -c "import importlib.metadata as md; print(md.version('pgvector'))"

# ORM 列类型 / pgvector 可用性
..\.venv\Scripts\python.exe -c "from app.models.document import DocumentChunk,_HAS_PGVECTOR; print(_HAS_PGVECTOR, DocumentChunk.__table__.c.embedding.type)"

# 切片器是否降级
..\.venv\Scripts\python.exe -c "from app.rag import text_splitter as t; print(t._HAS_LANGCHAIN)"

# 路由清单
..\.venv\Scripts\python.exe -c "from app.main import app; print([r.path for r in app.routes if hasattr(r,'path') and r.path.startswith('/api')])"

# 文件名穿越验证
..\.venv\Scripts\python.exe -c "from pathlib import Path; print((Path('uploads')/'3'/'4'/('x_'+'..\\..\\..\\evil.txt')).resolve())"
```

> 全部为只读操作；任何写操作前请先备份。
