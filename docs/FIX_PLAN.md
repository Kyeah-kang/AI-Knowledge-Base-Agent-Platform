# 修复执行清单（Fix Plan）

> 配套：[企业级差距复核](ENTERPRISE_GAP_REVIEW.md)（问题定义 / 影响 / 验收标准）· [架构文档](ARCHITECTURE.md) · [进度台账](TRACKER.md)
> 本文只回答三件事：**先改什么、改在哪个文件哪一行、改完怎么验证。**
> 行号基准：**2026-10-28 复核**（P0-1 修复之后）。行号会随改动漂移，请用「锚点」列的关键词重新定位。
> 状态：⬜ 待开始 · 🟨 部分完成 · ✅ 已完成

---

## 0. 现状快照

**已完成**

| 项 | 内容 | 证据 |
|---|---|---|
| P0-1 | 失败静默：上传失败落 `failed`、检索失败抛 503、SSE 必发 `event: error`、失败计数进 `/health` | [修复记录](ENTERPRISE_GAP_REVIEW.md#p0-1-上传检索失败静默文档仍标-completed) + 16 个回归用例 |
| P1-11 | 启动日志 emoji 导致 Redis 误报（随 P0-1 顺手修） | `main.py` 启动日志改为"已连接" |
| **B1 全部 5 项** | P0-2 / P0-4 / P0-5 / P0-6 / P1-8 关闭；期间还修掉 6 个此前无人发现的 bug（工具名重复致 Agent 全挂、非流式 NameError、依赖层吞异常、兜底总结 400、维度探测解码、异常 str 为空） | [B1 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b1-批次修复记录2026-10-28) + 24 个回归用例 |
| **B4 全部 4 项** | P1-9（结构化日志 + request_id）、P1-10（真实探活 + SQL 日志不泄漏）、P1-12（SSE 改 POST + refresh 轮换 + 登出）、P1-13（双窗口限流 + 登录锁定 + Redis 冷却） | [B4 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b4-批次修复记录2026-10-28) + 16 个回归用例 |
| **B3 全部 4 项** | P1-14（超时 + 重试 + embedding 分批）、P1-5（token 预算）、P1-6（Agent 真流式）、P1-7（工具可执行性）；顺带记录 token 用量、首 token 延迟 | [B3 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b3-批次修复记录2026-10-28) + 23 个回归用例 |
| **B7 部分（P2-10/11）** | Markdown 渲染 + 引用卡片 + 停止/重试；SSE 按空行分帧、断流检测、有限重试；前端新增 vitest 19 个用例 | [B7 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b7-批次修复记录2026-11-08) + 8 后端 + 19 前端用例 |
| **B6 部分（P2-4/9 + P2-2 + D-3）** | 模型按请求/会话生效 + 主备切换 + `/chat/models`；`/stats/overview` 真实统计；错误码表 + `/docs` 按环境开关 + 31 个中文 summary；备份/恢复脚本 + 演练 | [B6 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b6-批次修复记录2026-11-08) + 13 个新用例 |
| **B5 全部 4 项** | P1-1/2（双库 Alembic + HNSW）、P2-6（评测集 + recall@k + 阈值扫描）、P2-7（conftest + 集成测试 + 覆盖率门禁），外加 error_message / file_hash 两项遗留 | [B5 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b5-批次修复记录2026-10-28) + 27 个新用例 |
| **B2 全部 6 项** | P0-3 / P0-7 / P0-8 / P0-9 / P1-3 / P1-4 关闭；**P0 清零**。另补了补向量脚本与孤儿清扫脚本，并清掉 4 条历史孤儿切片 | [B2 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b2-批次修复记录2026-10-28) + 19 个回归用例 |
| 环境 | 补装 `cryptography`（否则 MySQL 8 认证失败，后端不可用）、`pytest`/`pytest-asyncio` | `requirements.txt` + `pytest` 29 passed |

**剩余：5 项** = P0 × 0 + P1 × 0 + P2 × 4 + 交付能力 × 1（P0/P1 全清零）
**已按重排顺序推进**：P2-4、P2-9、P2-2、D-3、P2-10、P2-11、D-1、P2-8 已完成；剩 4 个 P2 + CI（D-2）。 P0 已清零：系统不会再"骗人"、不会越权检索、不会把半成品当成功。下一步是 **B3 性能与上下文**。

---

## 1. 批次与依赖顺序

| 批次 | 目标 | 条目 | 依赖 | 预估 |
|---|---|---|---|---|
| **B1 止血** ✅ | 用户不被告知错误结果的场景清零 | P0-2/4/5/6、P1-8 | — | ~~2 天~~ 已完成 |
| **B2 可信** ✅ | 权限、密钥、上传、环境四件事正确 | P0-3/7/8/9、P1-3/4 | B1 | ~~3–4 天~~ 已完成 |
| **B3 性能与上下文** ✅ | 长会话不爆、Agent 真流式、工具能真执行 | P1-5/6/7/14 | B2 | ~~3 天~~ 已完成 |
| **B4 可观测** ✅ | 出问题能被发现，而不是靠用户投诉 | P1-9/10/12/13 | B3 | ~~3 天~~ 已完成 |
| **B5 可评测** ✅ | 效果能被证明 | P1-1/2、P2-6/7 | B4 | ~~5 天~~ 已完成 |
| **B6 可交付** | 别人 clone 下来能跑、能门禁、能恢复 | P2-1/8、D-1/2/3 | B5 | 4 天 |
| **B7 产品化** | 用得下去（引用、Markdown、停止生成） | P2-2/3/9/10/11 | B6 | 4 天 |
| **B8 收尾** | 多模型、prompt 治理、压测与许可 | P2-4/5/12 | B7 | 3 天 |

> 规则：**前一批不全绿，不开下一批**。每条做完 = 一次提交 + 一条验收证据。

---

## 2. B1 止血（5 项）— ✅ 已完成（2026-10-28）

> **实际落地与原计划的差异**（原计划保留在下方，便于对照）
>
> | 原计划 | 实际做法 | 为什么 |
> |---|---|---|
> | 抽 `_build_context()` 私有方法 | 新建 `app/services/message_context.py::load_history()`，chat/agent 共用；仓储侧加 `exclude_id` 参数 | 排除"当前这条"必须在 SQL 层做才精确（按内容排除会误伤重复提问） |
> | 只改 graph.py 的兜底 | 还新增 `_close_pending_tool_calls()` | 达到上限时消息停在 `assistant(tool_calls)`，总结调用会被上游 400 |
> | 只改 exceptions 默认值 | 还修了 `deps.get_vector_db` 的 yield-swallow | 不改它，任何路由的 404/409 都会被吞成 500，P0-6 等于没修 |
> | 未预见 | 修了工具名去重、非流式 NameError、`str(AppException)`、维度探测解码 | 都是端到端验证时才暴露的阻断级问题，详见 [B1 修复记录](ENTERPRISE_GAP_REVIEW.md#b1-批次修复记录2026-10-28) |

### B1-1 · P0-2 当前问题在 prompt 里重复注入 ✅

| 项 | 内容 |
|---|---|
| 现象 | 先存用户消息 → 再读最近 20 条（已含当前）→ 又 append 一次当前内容 |
| 文件与行 | `services/chat_service.py`：`role="user"` @326 → `_get_context_messages` @331 → `build_messages` @334；流式分支 @425 / @430 / @433 |
| 文件与行 | `services/agent_service.py`：@171 / @176 / @189；流式分支 @318 / @323 / @339 |
| 改法 | 抽一个 `_build_context(session_id, content)`：先读历史（排除最后一条 user），再拼当前问题。chat 与 agent 共用，删掉两处重复实现 |
| 验收 | 单测断言：messages 中当前内容出现次数 = 1（chat + agent 各一条） |
| 预估 | 0.5 天 |

### B1-2 · P0-4 Agent 达迭代上限返回空回答 ✅

| 项 | 内容 |
|---|---|
| 现象 | 超限时最后一条 assistant 是 `content=None` 的 tool_calls，`_extract_result` 取不到正文 → 空回复 |
| 文件与行 | `agent/graph.py`：`max_iterations=10` @279、`current_state.update` @333/342、`final_answer` 兜底 @379-383 |
| 文件与行 | `services/agent_service.py`：`max_iterations = 10` @346、一次性 token @411、超限 error @416 |
| 改法 | ① 达到上限时**强制一次不带 tools 的总结调用**；② 兜底文案明确说"已达最大工具轮数，以下是我已获得的信息"；③ `max_iterations` 改读配置（`AGENT_MAX_ITERATIONS`） |
| 验收 | 构造 10 轮 tool_calls 的假 LLM → 最终回答非空且含上限说明；配置改 3 能生效 |
| 预估 | 0.5 天 |

### B1-3 · P0-5 AgentChat 流式结束后答案消失、无会话连续性 ✅

| 项 | 内容 |
|---|---|
| 现象 | `onDone` 用闭包捕获的 `streamContent`（连接时为 `""`）→ 追加空消息；URL 不带 `session_id` → 每问一句新建会话 |
| 文件与行 | `frontend/src/pages/AgentChat.tsx`：URL 拼装 @103-106、`onDone` @127-140（`content: streamContent` @134） |
| 改法 | ① `useRef` 保存最新 `streamContent` / `toolCalls`，`onDone` 读 ref；② 监听 `event: session` 记录 `session_id` 并加入后续请求；③ 进入页面时用 `getSessionDetail` 恢复历史 |
| 验收 | 连续追问 3 轮：消息不消失、历史在、会话只有一个、工具卡片结束后仍可展开 |
| 预估 | 0.5 天 |

### B1-4 · P0-6 业务异常 HTTP 状态码错（401/403/404 全变 400） ✅

| 项 | 内容 |
|---|---|
| 现象 | `AppException` 的 `http_status_code` 默认 400，调用方只传 `code` ⇒ 登录失败返回 HTTP 400 |
| 文件与行 | `core/exceptions.py`：默认值 @26 |
| 文件与行 | `services/auth_service.py`：@48 / @51（401）、@54（403）、@62 / @67（401） |
| 改法 | 未显式传 `http_status_code` 时默认取 `code`（或维护 `code → HTTP` 映射表）；同时给 auth 的 5 处补上显式值。前端拦截器短期继续按 body `code` 兼容 |
| 验收 | 4 个用例：错误登录 401、禁用账号 403、资源不存在 404、参数错误 422 |
| 预估 | 0.5 天 |

### B1-5 · P1-8 LangGraph 降级路径会把消息历史覆盖掉 ✅

| 项 | 内容 |
|---|---|
| 现象 | 降级手写循环用普通 `dict.update()` —— 是**替换**而不是 `operator.add` 追加；tool 消息丢了前置 assistant tool_calls → 上游 LLM 400 |
| 文件与行 | `agent/graph.py`：@333、@342（`current_state.update(...)`） |
| 改法 | 抽 `_merge_state()`：`messages` 追加、其余字段覆盖；或干脆**异常不再静默降级**，抛 `AppException` 让上层看见 |
| 验收 | 强制 `graph.ainvoke` 抛异常 → 降级路径仍能得到正确回答或明确错误（不出现空回答） |
| 预估 | 0.5 天（与 B1-2 同一文件，建议一次改完） |

---

## 3. B2 可信（6 项）— ✅ 已完成（2026-10-28）

### B2-1 · P0-3 Agent 检索忽略选中的知识库（越权） ✅

| 项 | 内容 |
|---|---|
| 现象 | 只选 A 库，Agent 工具仍检索全库 → 跨库内容泄露 |
| 文件与行 | `agent/tools.py`：`kb_ids` 读出**但从未使用** @341，实际只用 `doc_ids` @342 |
| 文件与行 | `services/agent_service.py`：`context["kb_ids"]` @384 |
| 改法 | ① 短期：`agent_service` 里把 `kb_ids → document_ids` 预解析后写进 `context["document_ids"]`；② 彻底：`document_chunks` 加 `knowledge_base_id` 冗余列，检索 SQL 直接 `WHERE knowledge_base_id IN (...)`（与 B5-1/B5-2 的迁移一起做） |
| 验收 | A/B 两库放不同文档，选 A 问 B 的内容 → 结果只来自 A；单测覆盖 |
| 预估 | 0.5 天（短期方案） |

### B2-2 · P0-7 默认 JWT 密钥仍在使用 ✅

| 项 | 内容 |
|---|---|
| 现象 | `.env` 里 `JWT_SECRET_KEY` 长度 36 = 仍是默认占位符原文；`backend/test_token.txt` 还在工作区 |
| 文件与行 | `backend/.env`、`core/config.py` @75、`main.py::_validate_runtime_config`、`backend/test_token.txt` |
| 改法 | `python -c "import secrets;print(secrets.token_hex(32))"` 写入 `.env`；非 DEBUG 且默认值 → 拒绝启动（已有）；DEBUG 下把 warning 提升为 ERROR；删 `test_token.txt`；轮换 LLM/Embedding key |
| 验收 | 用默认 secret 无法启动；旧 token 全部失效 |
| 预估 | 0.5 天 |

### B2-3 · P0-8 上传：路径穿越 / 同步阻塞 / 无去重 ✅（去重待 B5-2）

| 项 | 内容 |
|---|---|
| 现象 | 文件名未净化 —— 实测 `..\..\..\evil.txt` 会落到 `uploads/{uid}/evil.txt`；整文件读入内存；同步解析阻塞事件循环；重复上传产生多份切片 |
| 文件与行 | `services/document_service.py`：`await file_obj.read()` @99、`parser.parse` @136、`_save_file` @358-378（拼接 @372） |
| 改法 | ① `Path(filename).name` + 字符白名单 + `resolve()` 后校验仍在 `uploads/` 下；② 解析/切片/embedding 移入后台任务（`BackgroundTasks` 起步，后续换队列）；③ 计算 sha256，同库重复拒绝或提示覆盖；④ 同步解析用 `run_in_executor` 包一层 |
| 验收 | 恶意文件名被拒；50MB 上传接口 2s 内返回；同文件二次上传被识别 |
| 预估 | 1.5 天 |

### B2-4 · P0-9 环境不可复现（依赖 + 切片降级 + 维度） ✅

| 项 | 内容 |
|---|---|
| 现象 | `requirements.txt` 停在旧版本（fastapi 0.115 vs 实装 0.136）；`text_splitter` 旧导入导致**静默降级**为简易切分；`.env.example` 与 `config.py` 默认 `EMBEDDING_DIMENSION=1536`，而库列是 1024 |
| 文件与行 | `backend/requirements.txt`、`rag/text_splitter.py` @24、`core/config.py` @91、`backend/.env.example` @44 |
| 改法 | ① 以当前可用环境重锁依赖（`pip freeze` + 手工分组）；② 改 `from langchain_text_splitters import RecursiveCharacterTextSplitter`，装 `langchain-text-splitters>=1.1,<2`；③ 三处维度统一 1024；④ 加 `pyproject.toml`（与 B6-2 合并） |
| 验收 | 全新 venv `pip install -r` 后 `import app.main` 成功，`_HAS_LANGCHAIN=True`，`pip check` 干净 |
| 预估 | 1 天 |

### B2-5 · P1-3 删除知识库不清 PG 切片（孤儿数据） ✅

| 项 | 内容 |
|---|---|
| 现象 | 只删 MySQL，PG 里 `document_chunks` 残留 → 检索仍可能命中已删文档 |
| 文件与行 | `services/knowledge_base_service.py`：`delete()` @81-88（@88 只删 MySQL） |
| 改法 | 先查该库全部 `document_id` → 删 PG chunks → 再删 MySQL；失败时补偿；另加 `scripts/cleanup_orphan_chunks.py` 可重复执行的清扫脚本 |
| 验收 | 删 KB 后 `document_chunks` 无对应 `document_id`；清扫脚本可重复跑 |
| 预估 | 0.5 天 |

### B2-6 · P1-4 会话列表 N+1、`updated_at` 不更新、详情截断 ✅

| 项 | 内容 |
|---|---|
| 现象 | 每个会话单独 count（50 会话 = 51 次 SQL）；发消息不 touch `updated_at`（排序永远不变）；详情默认 `limit=100` 静默截断 |
| 文件与行 | `services/chat_service.py`：@211（循环 count）；`repositories/chat_repo.py`：注释撒谎 @26、`limit: int = 100` @70 |
| 改法 | ① 一次 `GROUP BY session_id` 聚合 count；② 发消息后 `session.updated_at = utc_now()`；③ 详情分页参数化并支持游标 |
| 验收 | 50 会话列表 SQL ≤ 2；发消息后会话排到最前；长会话可翻页 |
| 预估 | 0.5 天 |

---

## 4. B3 性能与上下文（4 项）— ✅ 已完成（2026-10-28）

### B3-1 · P1-5 上下文固定 20 条，token 预算未使用 ✅
- 文件与行：`services/chat_service.py` @463（`limit: int = 20`）、`agent_service.py::_get_context_messages`；`services/llm_service.py::count_tokens` @212（**全仓无调用**）
- 改法：从新到旧累加 token，保留 ≤ 模型窗口 60%（含 system + 输出预留）；超预算记指标
- 验收：构造超长历史，请求 tokens 不超预算；单测覆盖预算边界

### B3-2 · P1-14 LLM 无超时/重试；Embedding 不分批 ✅
- 文件与行：`services/llm_service.py` `AsyncOpenAI(...)` @26（未传 timeout）；`rag/embeddings.py::embed_batch` @119-144（一次发全部切片）
- 改法：`timeout=` + tenacity 指数退避（仅重试 429/5xx/连接错误）；embedding 按 32/64 分批 + 批间重试；记录 `prompt/completion_tokens` 与耗时
- 验收：模拟 500/断网能自动重试成功；100 切片文档不再一次性请求

### B3-3 · P1-6 Agent「流式」不是真流式 ✅
- 文件与行：`services/agent_service.py` @411（拿到完整 `reply_text` 后一次性 yield）
- 改法：工具阶段结束后改用 `llm.chat_stream()` 逐 token 推送；前端展示首 token 时间
- 验收：Agent 首 token 时间明显下降；断流有明确 error 事件（已完成部分见 P0-1）

### B3-4 · P1-7 动态工具只有 schema，没有 executor ✅（过滤方案；executor 注册待 P2 之后）
- 文件与行：`agent/tools.py` `tool_map` @153（只有 3 个内建）；`repositories/agent_repo.py::create_tool`（只存 schema）；`frontend/src/pages/admin/ToolManage.tsx`（只有启停）
- 改法：① 实现 executor 注册（HTTP 白名单 / 函数映射）；② 未实现前，`get_tool_definitions()` 过滤掉无 executor 的动态工具；③ 注册表按租户隔离（现在是模块级全局变量）
- 验收：无 executor 的工具不会出现在 LLM tools 里；有 executor 的能真正执行

---

## 5. B4 可观测（4 项）— ✅ 已完成（2026-10-28）

### B4-1 · P1-9 无结构化日志 / request_id / 成本统计 ✅
- 文件与行：全仓无 `logging.config`（`app/core/` 下无 logging 模块）、`main.py` 只有 print、`services/llm_service.py` 不记录 usage
- 改法：新增 `app/core/logging.py`（dictConfig + JSON）、request_id 中间件（读写 `X-Request-ID`，注入日志上下文）、LLM 调用记录 `model/tokens/latency`
- 验收：一条请求的日志可用 request_id 串起；每次问答有 token 与耗时记录

### B4-2 · P1-10 健康检查假探针；DEBUG 打印全部 SQL ✅
- 文件与行：`main.py::health_check` @198（返回常量）；`database/session.py` `echo=settings.DEBUG` @25、@42
- 改法：`/health` 分项探活 MySQL/PG/Redis 并返回 503；生产关闭 echo；敏感字段脱敏
- 验收：停 PG 后 `/health` 返回 unhealthy；生产日志无完整用户消息

### B4-3 · P1-12 SSE 用 GET query、token 在 localStorage、无吊销 ✅（token 移出 localStorage 未做）
- 文件与行：`routers/v1/chat.py` @142-148、`routers/v1/agent.py` @80-82（`content` 走 Query）；`frontend/src/hooks/useSSE.ts` @24（localStorage）；`core/security.py` @71/@86（无 jti / 黑名单）
- 改法：改 `POST + text/event-stream`；refresh 轮换 + 服务端记录 `jti`；登出吊销；token 移出 localStorage（内存或 httpOnly cookie）
- 验收：消息不出现在 URL/访问日志；登出后旧 refresh 失效；刷新一次旧 refresh 不可复用

### B4-4 · P1-13 限流固定窗口、fail-open、双层重复、登录无锁定 ✅
- 文件与行：`core/rate_limiter.py` 注释撒谎 @22-25、fail-open @108、固定窗口 @114；`routers/v1/__init__.py::get_current_user` @60（第二层）
- 改法：真滑动窗口（ZSET）或令牌桶；`auth_service.login` 加失败计数（5 次锁 15 分钟）；Redis 不可用快速失败而非每请求重连；合并重复限流层
- 验收：窗口边界不双倍放行；5 次错误登录触发锁定；关 Redis 后接口不额外卡 3s

---

## 6. B5 可评测（4 项）— ✅ 已完成（2026-10-28）

### B5-1 · P1-1 无 ANN 索引，检索全表扫描 ✅
- 文件与行：`scripts/init_db.py` @37/@47 只 `create_all`；全仓无 `hnsw/ivfflat`
- 改法：`CREATE INDEX idx_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`；检索时设 `hnsw.ef_search`；写成迁移（与 B5-2 合并）
- 验收：`EXPLAIN (ANALYZE, BUFFERS)` 走 HNSW；1 万切片前后 p95 对比

### B5-2 · P1-2 `alembic/versions/` 为空，schema 无法演进 ✅
- 文件与行：`alembic/env.py` @33（`target_metadata = MySQLBase.metadata`，只看得见 MySQL）；`alembic/versions/` 空目录
- 改法：MySQL 生成 baseline；PG 单独 bind 或第二套 env（`target_metadata=PostgreSQLBase.metadata`）；把「维度 1536→1024」「HNSW 索引」「`documents.error_message`（P0-1 遗留）」都写成迁移；生产禁用 `create_all`
- 验收：空库 `alembic upgrade head` 建出与模型一致的两套表；变更可回滚

### B5-3 · P2-6 没有任何评测（四个 RAG 参数零依据） ⬜
- 文件与行：`backend/data/` 不存在；`scripts/` 无 `evaluate.py`；参数在 `core/config.py` @99-104
- 改法：25–30 条真实 QA → `backend/data/eval_qa.jsonl`；`scripts/evaluate.py` 算 `recall@k` / `MRR`；对 `chunk_size ∈ {300,500,800} × overlap ∈ {0,50,100}` 做网格实验；结果写 TRACKER
- 验收：一条命令输出 `recall@5=0.xx`；有 baseline 与至少一次改进对比

### B5-4 · P2-7 测试体系（已有 29 个用例，仍缺接口级） 🟨
- 文件与行：`backend/tests/`（无 `conftest.py`、无 `TestClient`、无 DB fixture）
- 改法：`conftest.py` + `httpx.AsyncClient` fixture；mock LLM/Embedding；覆盖率门槛（整体 ≥60%，核心链路 ≥80%）
- 验收：`pytest --cov` 出报告；CI 里全绿

---

## 7. B6 可交付（5 项）

### B6-1 · P2-1 根目录散落临时脚本与令牌文件 ⬜
- 文件与行：`backend/check_pgvector.py`、`check_pg_ext.py`、`reset_pg_table.py`、`test_phase6.py`、`test_phase7.py`、`test_token.txt`
- 改法：迁到 `scripts/dev/`，危险脚本（`reset_pg_table.py`）加二次确认；删除 `test_token.txt`
- 验收：`backend/` 根目录只留 `main` 相关文件

### B6-2 · P2-8 后端无 lint / type 门禁 ✅（2026-11-09）
- 文件与行：无 `pyproject.toml`（含 `ruff.toml` / `mypy.ini`）
- 改法：`pyproject.toml` + ruff + mypy + pre-commit；与 B2-4 的依赖锁定合并做
- 验收：`ruff check .` 与 `mypy app` 在本机与 CI 通过

### D-1 · 容器化：Dockerfile + docker-compose ✅（2026-11-09）
- 现状：根目录无 `Dockerfile` / `docker-compose.yml`；MySQL 是 Windows 服务、PG/Redis 是手工 `docker run`
- 改法：后端（uvicorn）+ 前端（Nginx 静态）+ MySQL/PG(pgvector)/Redis 五件套；`docker compose up` 一键起
- 验收：新机器 clone 后一条命令可访问登录页

### D-2 · CI 门禁 ⬜
- 现状：无 `.github/workflows`
- 改法：干净 venv 安装 + `import app.main` + `ruff` + `pytest` + 前端 `lint && build`
- 验收：PR 有检查项，红灯不能合

### D-3 · 备份与恢复演练 ✅（2026-11-08）
- 现状：`database-backups/` 只有一份 dump，无恢复脚本、无演练记录
- 改法：MySQL + PG 定时备份脚本 + 恢复 runbook；做一次真实恢复演练并记录耗时
- 验收：能从备份恢复出完整环境并跑通冒烟清单

---

## 8. B7 产品化（5 项）

### B7-1 · P2-9 前端显示错误数据 ✅（2026-11-08，提前完成）
- `frontend/src/pages/Dashboard.tsx`：「文档」卡片 `docCount` 恒为 0（@20 初始化、@52 展示，从未请求）
- `frontend/src/pages/admin/UserManage.tsx`：@39 展示后端不存在的 `email` 字段
- 改法：补真实统计（可加 `GET /documents/stats`）；移除或补 email
- 验收：页面数字与数据库一致

### B7-2 · P2-10 无 Markdown / 引用 / 停止生成 / 重试 ✅（2026-11-08）
- `frontend/src/pages/Chat.tsx`、`AgentChat.tsx`（纯文本 `pre-wrap`）；`frontend/package.json` 无 markdown 依赖
- 改法：`react-markdown` + 引用卡片（后端需回传 chunk 元数据）+ `AbortController` 停止 + 重试
- 验收：回答带可点击引用；生成中可停止；失败可重试

### B7-3 · P2-11 `useSSE` 解析健壮性 ✅（2026-11-08）
- 已修：`error` / `done` 事件（P0-1 期间）
- 仍缺：多行 `data:` 拼接、事件 ID、断线重连 —— `frontend/src/hooks/useSSE.ts`
- 验收：断网后被调用方收到明确错误；支持多行 data

### B7-4 · P2-2 无 API 契约 / 错误码表；生产默认开 `/docs` ✅（2026-11-08，提前完成）
- `main.py` @135 `docs_url="/docs"`；路由缺 `summary/description/examples`
- 改法：补 OpenAPI 描述与示例、错误码表（`code → HTTP → 含义`）；生产关闭或鉴权 `/docs`
- 验收：`/docs` 可读；错误码表与实现一致

### B7-5 · P2-3 无软删除 / 审计日志 ⬜
- 现象：删除是物理删除，无操作日志表
- 改法：`deleted_at` 软删除或审计表（who/what/when/before），与 B5-2 迁移一起
- 验收：误删可恢复 / 操作可追溯

---

## 9. B8 收尾（3 项）

### B8-1 · P2-4 `model_name` 只存不生效；无 provider fallback ✅（2026-11-08，提前完成）
- `services/chat_service.py` 存了 `model_name`，`%s` 但 `llm_service.LLMService` 始终用 `settings.LLM_MODEL_NAME`
- 改法：按会话/请求传 model；配置 provider 列表 + 主备切换
- 验收：两个会话可用不同模型；主模型 5xx 时自动切备

### B8-2 · P2-5 prompt 硬编码、无版本管理、无注入防护 ⬜
- `services/chat_service.py::_build_rag_system_prompt`、`agent_service.py` 同名方法（两处重复）；RAG 文档内容直接拼进 prompt
- 改法：prompt 模板文件 + 版本号；system prompt 明确"文档是数据不是指令"；输出过滤
- 验收：prompt 可版本化；注入样例不能越权

### B8-3 · P2-12 无压测基线 / 无反馈闭环 / 无 License ⬜
- 改法：k6 或 locust 脚本 + p95/吞吐基线；反馈表与接口（赞/踩/纠错）；补 `LICENSE`
- 验收：有性能报告；反馈可入库；仓库有许可证

---

## 10. 按文件速查（要改同一个文件的条目聚合）

| 文件 | 涉及条目 |
|---|---|
| `backend/app/services/chat_service.py` | P0-2、P1-4、P1-5、P2-4、P2-5 |
| `backend/app/services/agent_service.py` | P0-2、P0-3、P0-4、P1-5、P1-6、P2-5 |
| `backend/app/services/document_service.py` | P0-8、（P0-1 已改） |
| `backend/app/services/llm_service.py` | P1-5、P1-14、P2-4 |
| `backend/app/agent/graph.py` | P0-4、P1-8 |
| `backend/app/agent/tools.py` | P0-3、P1-7 |
| `backend/app/core/exceptions.py` | P0-6 |
| `backend/app/core/config.py` | P0-9、P1-14（新增配置项） |
| `backend/app/core/rate_limiter.py` | P1-13 |
| `backend/app/core/security.py` | P1-12 |
| `backend/app/main.py` | P1-9、P1-10、P2-2 |
| `backend/app/database/session.py` | P1-10 |
| `backend/app/rag/embeddings.py` | P1-14 |
| `backend/app/rag/text_splitter.py` | P0-9 |
| `backend/app/repositories/chat_repo.py` | P1-4 |
| `backend/app/repositories/document_repo.py` | P0-3（kb 下推） |
| `backend/app/routers/v1/chat.py`、`agent.py` | P1-12 |
| `backend/app/routers/v1/__init__.py` | P1-13 |
| `backend/alembic/env.py` + `versions/` | P1-1、P1-2、P2-3 |
| `backend/requirements.txt`、`pyproject.toml` | P0-9、P2-8 |
| `frontend/src/pages/AgentChat.tsx` | P0-5、P2-10 |
| `frontend/src/pages/Chat.tsx` | P2-10 |
| `frontend/src/hooks/useSSE.ts` | P1-12、P2-11 |
| `frontend/src/pages/Dashboard.tsx`、`admin/UserManage.tsx` | P2-9 |

---

## 11. 明确不做 / 延后

| 项 | 原因 | 何时 |
|---|---|---|
| K8s / 多区域 / 自动扩缩容 | 超出个人项目与岗位范围 | 工作后按需 |
| 微服务拆分 | 模块化单体更适合当前规模 | 数据/团队上来后 |
| 模型微调 | RAG 还没评测，谈不上微调 | 有稳定数据与 baseline 后 |
| 多租户 / SSO / 计费 | 企业版能力，非当前主线 | 有余力 |
| GraphRAG / 知识图谱 | 先把向量 + 关键词混合做扎实 | B5 之后评估 |
| 重写前端 UI | 现有够用，优先修正确性 | 不排期 |
