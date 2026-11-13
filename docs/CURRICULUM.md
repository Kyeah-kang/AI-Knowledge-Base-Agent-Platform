# CURRICULUM.md — 48 天逐日课程（基线门 + 边学边修）

> 配套：[README](../README.md) · [架构](ARCHITECTURE.md) · [差距审计](GAP_ANALYSIS.md) · [企业级复核](ENTERPRISE_GAP_REVIEW.md) · [修复清单](FIX_PLAN.md) · [面试题库](INTERVIEW.md) · [进度台账](TRACKER.md)
> 节奏：每天 2.5–3h，周四休息；每周第 6 天为 Gate（90 分钟验收）。
> 原则：**你写代码，我出题/Review/测试；卡住 30 分钟才给最小示例。**
> 记号：【读】阅读 ·【手】动手 ·【讲】能讲清/能画 ·【面】面试题 ·【证】证据。

---

## 0. 怎么用这份课程

1. 每天开始：看当天“目标/产出”，在 `TRACKER.md` 建一行。
2. 按【读】→【手】→【讲】顺序；卡住先记录，30 分钟后再求助。
3. 每天结束：写“我改了什么/为什么/证据/卡点/面试题答案”。
4. 每周 Gate：按当天清单验收；不过则顺延，不跳。
5. 诊断测（D1）得分 ≥80% 的模块，可只做“代码走查 + 面试追问”，省时间给 RAG/部署。

**每日时间盒**：10′ 计划 + 40′ 读 + 25′ 画/讲 + 70′ 动手 + 20′ 测试/证据 + 20′ 面试/记录。

---

## 第 1 周：基线门 + 修复即课程

### D1 全栈跑通（非 RAG）

**目标**：浏览器完成“注册/登录 → 建知识库 → 上传 → 普通聊天 → Agent 计算器”，并记录基线。

【读】
- `backend/app/main.py`：lifespan、CORS、限流、路由注册。
- `backend/app/core/config.py`：配置从哪来、默认值。
- `backend/app/core/deps.py`、`backend/app/database/session.py`：双库会话。
- `frontend/src/App.tsx`、`src/api/client.ts`、`src/hooks/useSSE.ts`：路由/请求/流式。

【手】
1. 确认 MySQL82、`kb-postgres-published`、`kb-redis` 运行。
2. 从 `backend/` 启动：`..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`。
3. 打开 `/docs`，确认 34 路由。
4. 前端：`cd frontend` → `npm run dev -- --port 3000`（临时绕 CORS）。
5. 冒烟：注册/登录 → 建库 → 上传 txt → 普通聊天 → Agent 计算器。
6. 记录：命令、截图、异常、耗时；RAG 失败属预期。

【讲】
- 为什么前端 3000 能通、5173 不通？（CORS）
- 后端为什么必须从 `backend/` 启动？（`.env` 相对 CWD）
- 一次聊天请求经过哪些层？

【面】
- 你项目怎么启动？依赖哪些外部服务？
- 前后端分离怎么解决跨域？预检请求是什么？

【证】`TRACKER.md` D1 冒烟表；6 步截图。
**时间**：3h（允许 3.5h）。

---

### D2 RAG 最小闭环（第一次边修边讲）

**目标**：知识库问答真正检索到内容；讲清“为什么之前是假工作”。

【读】
- `backend/app/models/document.py:18-26,117-129`：pgvector import 与 Text 降级。
- `backend/app/database/session.py:52-71`：asyncpg 注册 Vector。
- `backend/app/services/document_service.py:136-156`：embedding 与状态。
- `backend/app/rag/embeddings.py`、`vector_store.py`、`retriever.py`。
- `backend/app/repositories/document_repo.py:143-181`：余弦 SQL 与静默异常。
- `backend/app/core/config.py:88-104`、`backend/.env`：模型/维度/切片。

【手】
1. `pip install pgvector`（写入 requirements）。
2. 验证 `DocumentChunk.__table__.c.embedding.type` → `VECTOR(1024)`。
3. 统一 1024：`.env`、`config.py` 默认值、DB 列。
4. 备份后迁移列：
   `ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024);`
5. 给已有 6 条切片补 embedding（脚本 `scripts/reindex_documents.py`）。
6. 写 `scripts/prove_rag.py`：模型/维度/切片数/向量数/top-k/耗时。
7. 断 embedding key 演示“必须失败”，不是 completed。

【讲】
- 扩展 vs 客户端分别负责什么？
- 维度不一致会发生什么？为什么错误被吞？
- 余弦距离/相似度怎么算？`<=>` 是什么？

【面】
- 你的向量检索怎么保证和 embedding 模型一致？
- 怎么证明 RAG 真的在工作？
- 线上 embedding 失败你怎么发现？

【证】`prove_rag` 输出；`select count(*),count(embedding)` 6/6；迁移前后对比。
**时间**：3.5h（本日可延长）。

---

### D3 切片现代化 + 架构地图

**目标**：用 LangChain 1.x 正确切片；建立系统地图。

【读】
- `backend/app/rag/text_splitter.py`：旧 import、降级、简易切分。
- `backend/app/rag/document_parser.py`：PDF/DOCX/MD/TXT 解析与页标记。
- `backend/app/services/document_service.py:107-134`：切片与入库。
- `docs/ARCHITECTURE.md` 第 4–6 节。

【手】
1. 改为 `from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter`。
2. 中文分隔符：`["\n\n","\n","。","！","？","；","，"," ",""]`；`length_function=len`；`keep_separator=True`。
3. Markdown：先按标题切，再递归；标题写入 `extra_meta`。
4. 用同一文档对比旧/新切片：块数、平均长度、边界、可读性。
5. 重切一个文档并重新 embedding。
6. 画：组件图、上传时序、双库边界。

【讲】
- `chunk_size=500` 是字符还是 token？中文/英文差异？
- 为什么要 overlap？过大会怎样？
- LangChain 1.x 为什么拆包？旧代码为什么静默降级？

【面】
- 你的 chunk 参数怎么定的？有实验吗？
- 依赖升级怎么治理？怎么防止静默降级？

【证】新旧切片对比表；三张图；`pip check` 通过。
**时间**：3h。

---

### D4 认证链路：注册/登录/刷新/鉴权/越权

**目标**：能画认证时序，讲清 JWT/bcrypt/依赖注入。

【读】
- `backend/app/routers/v1/auth.py`、`services/auth_service.py`、`core/security.py`。
- `backend/app/routers/v1/__init__.py`：`get_current_user` / `get_current_admin`。
- `backend/app/repositories/user_repo.py`、`schemas/user.py`、`models/user.py`。
- `frontend/src/pages/Login.tsx`、`Register.tsx`、`store/authStore.ts`、`api/client.ts`。

【手】
1. 画注册/登录/刷新/受保护请求四条时序。
2. 手动构造过期 access → 观察 401 → refresh 流程。
3. 用普通用户 token 访问管理员接口 → 验证 403。
4. 修一个安全问题（如默认 secret 强校验 / 登录错误信息统一）。
5. 加一个认证单测（过期/类型混用/禁用用户）。

【讲】
- JWT 三段、HS256、`exp`、`type` 作用。
- 为什么 access 短、refresh 长？refresh 泄露怎么办？
- bcrypt 为什么加盐？彩虹表是什么？

【面】
- 你的认证怎么做的？token 放哪？XSS/CSRF 怎么防？
- 用户被禁用后旧 token 还能用吗？怎么吊销？

【证】时序图；401/403 截图；单测通过。
**时间**：2.5h。

---

### D5 聊天/SSE 链路 + 重复注入 + 上下文

**目标**：讲清普通聊天与流式；修 GAP-005。

【读】
- `backend/app/routers/v1/chat.py`、`services/chat_service.py:268-425`。
- `backend/app/services/llm_service.py`：`build_messages`、`chat_stream`、`count_tokens`。
- `backend/app/repositories/chat_repo.py`：历史/排序/限制。
- `frontend/src/hooks/useSSE.ts`、`pages/Chat.tsx`。

【手】
1. 用 `curl -N` 观察 SSE 原始字节，记录事件格式。
2. 复现“当前问题出现两次”：打印 `messages`。
3. 修：先读历史再保存，或读历史时排除当前；chat/agent 统一封装。
4. 加单测：当前内容只出现一次。
5. 记录一次请求的 token 估算。

【讲】
- SSE 与 WebSocket、轮询的区别；为什么选 SSE？
- 流式怎么判断结束？中断怎么处理？
- 上下文怎么拼？system/user/assistant 顺序？

【面】
- 你的流式怎么实现？首 token 延迟怎么优化？
- 多轮上下文怎么管理？超长怎么办？

【证】修复 diff；messages 打印；单测。
**时间**：3h。

---

### D6 Gate 1：三条链路 + 六个 P0

**目标**：验收 W1，形成第一版面试叙事。

【讲/证】
1. 默画：组件图、上传时序、聊天 SSE 时序。
2. 口述：认证、聊天、上传三条链路各 5 分钟。
3. 代码定位：随机 15 个符号，60 秒内找到。
4. 跑证据：`prove_rag`、`pytest`、冒烟 6 步。
5. 我按题库追问 8–10 题。

【验收】
- GAP-001/002/003/005/009/010 关闭（或明确剩余）。
- 能解释“为什么之前 RAG 是假的”。
- `TRACKER` W1 复盘完成。

**时间**：1.5h。

---

## 第 2 周：RAG 质量与评测

### D7 切片参数实验

【读】`text_splitter.py`、`config.py:98-104`、`document_service.py:113-134`。
【手】同一批文档用 300/500/800 切，记录块数/平均长度/检索命中；把结果写 `TRACKER`。
【讲】块大小与召回/上下文/成本的关系；overlap 的边界。
【面】你怎么定 chunk_size？做过什么实验？
【证】对比表；至少 3 组数据。

### D8 Embedding：模型、批量、成本、失败

【读】`embeddings.py`、`document_service.py:136-156`、`config.py:88-91`。
【手】批量 32/64；加维度校验；断 key 演示 failed；记录单文档成本。
【讲】bge-m3 特点；维度/归一化；批量上限；重试。
【面】为什么选 bge-m3？换模型要做什么？
【证】分批日志；失败状态；成本估算。

### D9 pgvector 与 ANN 索引

【读】`document_repo.py:143-181`、`vector_store.py`、`scripts/init_db.py`。
【手】建 HNSW（`vector_cosine_ops`，m/ef_construction）；`EXPLAIN ANALYZE` 对比；调 `hnsw.ef_search`。
【讲】HNSW vs IVFFlat；近似检索“只影响快不影响对”；过滤与索引。
【面】为什么建 HNSW？参数怎么定？数据量多大时建？
【证】执行计划；延迟对比。

### D10 检索、阈值、引用、防注入

【读】`retriever.py:52-198`、`chat_service.py:121-140`、prompt 拼接处。
【手】主链路统一阈值；低于阈值显式“未找到”；prompt 加引用编号/文件名；文档内容标记为“数据非指令”。
【讲】召回 vs 排序；阈值为什么不能拍 0.7；引用怎么溯源。
【面】怎么减少幻觉？怎么让回答可溯源？
【证】库外问题不硬答；引用可定位。

### D11 评测集与脚本

【读】`tests/`、`scripts/`、检索入口。
【手】25–30 条 `data/eval_qa.jsonl`（Q/期望文档/期望答案）；`scripts/evaluate.py` 算 recall@k/MRR；抽 10 条人工评分或 LLM judge。
【讲】recall@k、MRR、忠实度；评测集怎么防泄漏。
【面】你怎么证明 RAG 有效？指标怎么算？
【证】`recall@5=0.xx`；baseline 记录。

### D12 Gate 2：参数与指标复盘

【讲/证】指标表；chunk/top_k/阈值对比；RAG 10 连问；README 指标区更新。
【验收】GAP-004/012（+034 部分）关闭；有 baseline 与一次改进。
**时间**：1.5h。

---

## 第 3 周：Agent 与 LangGraph

### D13 Agent 概念与现状审计

【读】`agent_service.py`、`agent/graph.py`、`agent/tools.py`、`agent/state.py`。
【手】列出三套循环（graph、manual、agent_service 流式）差异；标出重复与风险。
【讲】ReAct/工具调用协议；LLM 怎么决定调工具；观察结果怎么回填。
【面】Agent 与普通聊天区别？工具调用协议是什么？
【证】审计清单。

### D14 LangGraph：状态、节点、边、checkpoint

【读】`graph.py:197-238`、`state.py`、LangGraph 文档。
【手】进程级单例编译；`MemorySaver` 最小示例；讨论 `pg_db` 不可序列化问题。
【讲】State/Node/Edge/Reducer/Checkpoint；图 vs while；断点续跑价值。
【面】为什么用 LangGraph？checkpoint 解决什么？
【证】只编译一次；中断恢复 demo 或方案讲清。

### D15 工具系统：注册、执行、权限、失败

【读】`tools.py`、`agent_repo.py`、`ToolManage.tsx`。
【手】无 executor 的工具不下发；连续失败计数停用；超时/结果截断；mock 结果加⚠或不注册。
【讲】工具 schema 与实现分离；权限边界；失败回退。
【面】怎么防止工具越权/死循环/注入？
【证】未知工具不崩；失败可回退。

### D16 修 Agent 正确性

【读】`tools.py:322-366`、`agent_service.py:313-395`、`graph.py:169-189,317-390`。
【手】修 KB 范围下推、上限兜底、降级循环消息合并、重复注入；加 5 个回归测试。
【讲】为什么 `dict.update` 会覆盖 reducer；上限后怎么给答案。
【面】Agent 选中的知识库怎么保证只检索它？
【证】跨库测试；超限测试；降级测试。

### D17 真流式与事件协议

【读】`agent_service.py:313-395`、`chat_service.py:330-401`、`useSSE.ts`。
【手】工具阶段后接 `chat_stream`；统一 error/done；中断落库；前端显示首 token 时间。
【讲】Agent 流式与普通流式差异；异常位置（响应头已发）。
【面】Agent 流式怎么实现？断流怎么办？
【证】首 token 时间；异常事件。

### D18 Gate 3

【讲/证】Agent 状态机图 + 工具流程图；Agent 8 连问；5 个回归测试。
【验收】GAP-006/007/013/018/019（部分）关闭。

---

## 第 4 周：后端工程化 + 前端全栈

### D19 FastAPI 进阶

【读】`routers/*`、`core/deps.py`、`schemas/*`、`exceptions.py`。
【手】把一处阻塞调用改线程池/异步；补 OpenAPI 描述/示例；统一错误码。
【讲】Depends/yield 生命周期；Pydantic v2；async 里不能做什么。
【面】FastAPI 依赖注入原理？async 阻塞会怎样？
【证】改前/改后延迟；文档可读。

### D20 SQLAlchemy async + Alembic 双库

【读】`database/*`、`models/*`、`alembic/env.py`、`chat_repo.py`、`knowledge_base_service.py`。
【手】MySQL/PG 两套 baseline 迁移；修 N+1；touch `updated_at`；详情分页；删 KB 清 PG。
【讲】会话/事务/连接池；N+1；双库一致性；迁移回滚。
【面】怎么发现 N+1？双库怎么保证一致？
【证】空库 `alembic upgrade head`；SQL 次数；孤儿检查。

### D21 安全：密钥、token、CORS、上传

【读】`security.py`、`config.py`、`rate_limiter.py`、`document_service.py:305-326`、`client.ts`。
【手】轮换 secret/key；refresh 旋转；登录失败锁定；CORS 5173；路径净化；bcrypt 兼容。
【讲】JWT 风险、XSS/CSRF、路径穿越、越权。
【面】你的 token 怎么存？怎么防越权？上传怎么防穿越？
【证】安全 checklist；攻击用例被拒。

### D22 Redis：缓存、限流、一致性

【读】`cache.py`、`rate_limiter.py`、`redis_client.py`。
【手】修限流术语/算法；缓存键加版本；缓存失效；幂等键。
【讲】缓存穿透/击穿/雪崩；固定 vs 滑动 vs 令牌桶；fail-open/fail-close。
【面】为什么用 Redis？缓存怎么失效？
【证】命中率；限流演示；故障降级。

### D23 前端：组件、状态、流式、错误

【读】`App.tsx`、`client.ts`、`useSSE.ts`、`store/*`、`Chat/AgentChat/Dashboard/UserManage/ToolManage`。
【手】修 AgentChat 闭包/会话连续；Dashboard 文档数；UserManage email；会话重命名；Markdown/引用；错误边界。
【讲】React 闭包陷阱；Zustand；Axios 拦截器；SSE 生命周期。
【面】流式结束答案为什么消失？怎么避免 stale state？
【证】端到端演示；连续 3 轮对话。

### D24 Gate 4

【讲/证】全栈 8 问；空库建表；AgentChat 演示；迁移可复现。
【验收】GAP-008/011/015/016/017/020/021/024/026/037 关闭或明确剩余。

---

## 第 5 周：可靠性与测试

### D25 日志、request_id、成本

【读】`main.py`、`llm_service.py`、`embeddings.py`、`cache.py`。
【手】结构化日志；request_id 中间件；LLM usage/latency/token 埋点；成本估算；关掉生产 SQL echo。
【讲】日志分级/脱敏；可观测三支柱；成本模型。
【面】线上怎么排障？怎么知道一次问答花多少钱？
【证】一条请求日志串起来；成本表。

### D26 超时、重试、熔断、健康检查

【读】`llm_service.py:24-33,151-180`、`redis_client.py`、`deps.py`、`main.py:125-128`。
【手】timeout + tenacity（429/5xx/连接，退避+抖动）；`/health` 探活 DB/Redis；降级策略表。
【讲】重试哪些码；为什么加抖动；fail-open/fail-close。
【面】上游超时怎么办？重试会不会放大故障？
【证】故障注入；健康检查分项。

### D27 异步任务：上传异步化

【读】`document_service.upload`、document router、`embeddings.py`。
【手】上传只入 pending；后台任务解析/切片/embedding；进度查询；stuck 清扫；分批。
【讲】BackgroundTasks vs Celery/Arq；幂等；重试；状态机。
【面】50MB PDF 怎么不阻塞？任务失败怎么重试？
【证】大文件即时返回；进度可查。

### D28 测试金字塔

【读】`tests/*`、`pytest.ini`。
【手】conftest、TestClient、mock LLM/embedding、临时库；单测/集成/e2e；覆盖率。
【讲】测试金字塔；mock 边界；测试隔离。
【面】你怎么测 LLM 应用？怎么保证不真调模型？
【证】≥30 测试；覆盖率报告。

### D29 评测自动化 + CI 门禁

【读】`scripts/evaluate.py`、CI 配置。
【手】评测脚本入 CI；阈值；回归对比；报告 artifact。
【讲】离线评测 vs 线上指标；回归门禁。
【面】怎么防止改动让效果变差？
【证】CI 跑评测；阈值拦截。

### D30 Gate 5

【讲/证】故障 6 问；日志演示；覆盖率；异步上传。
【验收】GAP-014/022/023/027 关闭。

---

## 第 6 周：安全、性能、质量

### D31 安全复审

【读】上传、认证、依赖、Docker。
【手】OWASP 对照；路径/SSRF/注入；`pip-audit`/`npm audit`；密钥扫描。
【讲】常见 Web 漏洞在项目中的对应。
【面】你项目最大的安全风险是什么？
【证】无高危清单。

### D32 API 设计

【读】`routers/*`、`schemas/common.py`。
【手】错误码表、分页规范、幂等键、版本策略、OpenAPI 示例。
【讲】REST 设计；统一响应取舍；幂等。
【面】重复提交怎么防？API 怎么版本化？
【证】契约文档。

### D33 性能

【读】慢 SQL、N+1、索引、连接池。
【手】profiling；补索引；批量；压测（locust/k6）；p95/吞吐。
【讲】瓶颈定位方法；缓存/索引/并发。
【面】QPS 上来先看什么？
【证】压测报告。

### D34 质量门禁

【读】前端/后端现有 lint 配置。
【手】ruff/mypy/pre-commit/oxlint/prettier；CI 全绿；类型逐步收紧。
【讲】静态检查价值；类型边界。
【面】怎么保证代码质量？
【证】CI 全绿。

### D35 文档同步

【读】README/ARCHITECTURE/TRACKER。
【手】更新状态表、图、指标、限制；把本周修复写成“问题→方案→证据”。
【讲】如何用文档讲项目。
【面】给我 5 分钟介绍你的项目。
【证】文档与代码一致。

### D36 Gate 6

【讲/证】架构设计面试；安全/性能追问；CI 演示。
【验收】GAP-030/031/032/035/036 关闭或明确剩余。

---

## 第 7 周：部署（最后）

### D37 后端 Dockerfile

【读】依赖、启动、配置。
【手】多阶段、非 root、healthcheck、`.dockerignore`；镜像瘦身。
【讲】镜像分层；为什么非 root；配置注入。
【面】容器里怎么启动 FastAPI？workers 怎么定？
【证】镜像可跑。

### D38 Compose 全栈

【读】现有 Docker 拓扑。
【手】MySQL/PG/Redis/API/Web/Nginx；卷、healthcheck、depends_on；启动迁移 + seed。
【讲】Compose 网络/卷/依赖；数据持久化。
【面】数据库数据怎么持久化？启动顺序怎么保证？
【证】一键起。

### D39 Nginx、SSE、HTTPS

【读】SSE 头、代理配置。
【手】反代、`proxy_buffering off`、超时、gzip、HTTPS（可选）。
【讲】为什么 SSE 不能被缓冲；Nginx 超时。
【面】流式经过 Nginx 要注意什么？
【证】浏览器流式正常。

### D40 CI/CD

【读】CI 需求。
【手】lint/test/build/push/迁移/回滚；gitleaks。
【讲】流水线阶段；镜像 tag；回滚。
【面】怎么做到一键回滚？
【证】流水线跑通。

### D41 可观测与备份

【读】日志/指标/备份。
【手】日志收集；指标；备份定时；恢复演练；runbook。
【讲】备份 3-2-1；RTO/RPO（概念）。
【面】数据丢了怎么恢复？
【证】恢复演练成功。

### D42 Gate 7

【讲/证】fresh clone 一键起；冒烟；3 故障演练（DB/Redis/LLM）；部署文档。
【验收】GAP-025/038 关闭。

---

## 第 8 周：面试与主权

### D43 叙事、简历、证据链

【手】2 分钟/5 分钟稿；简历 3–4 条 bullet；证据目录；3 分钟 demo 脚本。
【讲】背景→目标→方案→难点→数据→取舍。
【面】自我介绍；项目最大难点；为什么这么做。
【证】两版稿 + demo 跑通。

### D44 八股一轮

【面】Python/async、HTTP、MySQL/索引/事务、Redis、OS/网络各 5–6 题。
【手】错题写回 TRACKER。
【证】30 题自测 ≥80%。

### D45 AI 专项

【面】LLM、token、temperature、function calling、RAG、评测、Agent、安全、成本各 3–5 题。
【手】错题补代码证据。
【证】30 题自测 ≥80%。

### D46 系统设计

【手】设计“企业知识库问答平台”：存储、检索、权限、多租户、成本、扩展、监控。
【讲】白板 20 分钟；取舍。
【面】10 万文档/1000 QPS 怎么办？
【证】设计图 + 追问。

### D47 全真模拟

【手】90 分钟：自我介绍 → 项目深挖 → 故障 → 系统设计 → 反问。
【证】评分表；薄弱项清单。

### D48 终验

【证】ownership checklist 20 项；4 图默画；随机代码定位；遗留项；下一步。
【验收】100% 通过；README/PLAN/TRACKER 定稿。

---

## 附：每周产出清单

| 周 | 代码 | 文档/数据 | 面试 |
|---|---|---|---|
| W1 | pgvector/维度/切片/重复注入/密钥 | 基线表、prove_rag、对比表、3 图 | 2 链路口述 |
| W2 | HNSW/阈值/引用/评测 | eval_qa.jsonl、指标表 | RAG 10 连问 |
| W3 | Agent 范围/上限/降级/真流式 | 状态机图、回归测试 | Agent 8 连问 |
| W4 | 迁移/一致性/N+1/前端 | 迁移脚本、端到端 | 全栈 8 问 |
| W5 | 日志/重试/异步/测试 | runbook、覆盖率 | 故障 6 问 |
| W6 | 安全/性能/质量门禁 | 安全清单、压测报告 | 架构设计 |
| W7 | Docker/Compose/Nginx/CI | 部署文档、演练记录 | 部署题 |
| W8 | 定稿/修遗留 | 简历、证据链 | 3 轮模拟 |

---

## 附：诊断测（D1 用）

**12 道概念题**

1. FastAPI 的 `Depends` 和 `yield` 生命周期？
2. 为什么 MySQL + PostgreSQL 双库？一致性怎么保证？
3. JWT 三段分别是什么？`type` 字段干什么？
4. bcrypt 为什么比 MD5 安全？
5. SSE 和 WebSocket 区别？
6. SQLAlchemy async 会话何时 commit/rollback？
7. 什么是 N+1？怎么发现？
8. pgvector 的 `<=>` 是什么？相似度怎么算？
9. RAG 的召回与排序分别解决什么？
10. LangGraph 的 State/Node/Edge/Reducer 是什么？
11. 工具调用的协议长什么样？怎么防越权？
12. Redis 缓存穿透/击穿/雪崩区别？

**3 张图**：组件图、聊天 SSE 时序、上传流水线。

**15 个符号定位**：`get_current_user`、`verify_owner`、`build_messages`、`similarity_search`、`create_agent_graph`、`execute_tool`、`get_vector_db`、`RateLimiter`、`Response`、`AppException`、`useSSE`、`client`、`authStore`、`DocumentService.upload`、`ChatService.send_message_stream`。

评分：概念 12 + 图 3 + 定位 15 = 30 分；≥24 分（80%）可跳过对应模块的“读代码”，只做追问与改造。
