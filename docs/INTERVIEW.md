# INTERVIEW.md — 项目面试武器库

> 配套：[README](../README.md) · [架构](ARCHITECTURE.md) · [差距审计](GAP_ANALYSIS.md) · [企业级复核](ENTERPRISE_GAP_REVIEW.md) · [修复清单](FIX_PLAN.md) · [课程](CURRICULUM.md)
> 用法：先自己答，再对照“骨架”；每个答案必须能指到本项目代码/数据；答不出就回课程对应天。
> 目标：60+ 核心题能讲，30 道加分题有思路；4 张图能默画；3 分钟 demo 能跑。

---

## 1. 项目叙事模板

### 1.1 两分钟版（电梯陈述）

> 我做的是一个企业级 AI 知识库 Agent 平台：用户可以建知识库、上传 PDF/Word/Markdown，系统解析切片、生成 embedding 存到 PostgreSQL + pgvector；提问时先检索相关片段再交给 DeepSeek 生成，支持 SSE 流式；另外有一个 Agent 模式，能调用联网搜索、计算器、知识库检索三个工具。后端是 FastAPI + SQLAlchemy async + MySQL/PG/Redis，前端 React + AntD。
> 我在做这个项目时重点解决三类问题：一是 RAG 的“假工作”——向量维度、pgvector 客户端、静默失败；二是 Agent 的正确性——知识库范围、迭代上限、流式；三是工程化——评测、迁移、日志、容器化。现在它可以一条命令部署，并且有 recall@5 的评测基线。

**注意**：数字（recall/延迟）要等 W2 真实测完再填；没测完就说“正在建评测基线”，不要编。

### 1.2 五分钟版（STAR）

| 段 | 内容 |
|---|---|
| S 背景 | 企业文档分散在 Wiki/PDF/Word，关键词检索不准；直接用 LLM 会幻觉、无出处；还要权限与成本控制 |
| T 目标 | 做一个可上传、可检索、可溯源、可扩展工具的问答平台；支持流式与 Agent |
| A 行动 | 分层单体：router/service/repo/model；MySQL 业务 + PG 向量；Redis 缓存限流；RAG 五段；LangGraph 工具循环；JWT 鉴权；SSE |
| R 结果 | 核心链路可跑；修复了 RAG 假工作、Agent 范围/上限、前端丢答案等缺陷；建立评测与部署（W7 后填数字） |
| 反思 | 早期重功能轻评测/可观测；现在用“评测先行 + 失败显式 + 小步提交”补 |

---

## 2. 简历 bullet 模板（先占位，数字待实测）

- 设计并实现企业知识库 RAG 平台（FastAPI + SQLAlchemy async + MySQL/PostgreSQL/pgvector + Redis + React），支持多知识库、文档解析切片、流式问答与 Agent 工具调用。
- 定位并修复 RAG 向量链路故障（pgvector 客户端缺失、embedding 维度不一致、异常静默吞掉），建立 `prove_rag` 自检与维度校验，知识库检索从 0 向量恢复到可用。
- 为 Agent 增加知识库范围下推、迭代上限兜底与 LangGraph 降级保护，工具调用成功率从 __% 提升到 __%（待测）。
- 建立 25+ 条真实 QA 评测（recall@5 / MRR / 忠实度），将 chunk/top_k 调参从“拍脑袋”变为数据驱动，recall@5 从 __ 提升到 __（待测）。
- 完成容器化与 CI（Docker Compose + Nginx + GitHub Actions），实现一键部署、健康检查与备份恢复演练。

> 原则：没有证据的数字不写；面试官追问“怎么测的”必须能打开脚本/报告。

---

## 3. 核心题库

### A. Python / async（8 题）

**A1. async/await 解决了什么？和线程/进程的区别？**
- 骨架：单线程事件循环 + 协作式切换；适合 I/O 密集；CPU 密集用进程；线程受 GIL 限制。
- 证据：`llm_service.py` 的 `AsyncOpenAI`、`chat_stream` 异步生成器；`document_service.upload` 里的同步解析是反例。
- 追问：如果解析 PDF 是 CPU 密集，怎么不阻塞事件循环？

**A2. 在 async 函数里调用同步阻塞代码会怎样？**
- 骨架：阻塞整个事件循环，所有并发请求卡住；用 `run_in_executor`/线程池/后台任务。
- 证据：`document_service.py:107-108` 的 `parser.parse()` 在 async 里同步跑；`open()` 写文件。
- 追问：50MB PDF 上传时，其他用户的聊天会怎样？

**A3. `asyncio.gather` 和 `create_task` 的区别？**
- 骨架：`gather` 等待全部（可 `return_exceptions`）；`create_task` 立即调度、需自己管理异常/取消。
- 证据：项目里批量 embedding 目前是串行/一次请求，可改并发分批（GAP-022）。
- 追问：一个任务失败，其他任务怎么处理？

**A4. `async with` 与 `yield` 依赖的生命周期？**
- 骨架：进入建会话，退出 commit/rollback/close；异常也走 `finally`。
- 证据：`database/session.py:76-99` 的 `get_mysql_db/get_pg_db`。
- 追问：在 service 里手动 commit 会有什么问题？

**A5. 生成器/异步生成器在流式里的作用？**
- 骨架：逐块产出，不占内存；`yield` 给 `StreamingResponse`。
- 证据：`llm_service.chat_stream`、`chat_service.send_message_stream`。
- 追问：客户端中途断开，生成器会怎样？已生成内容怎么处理？

**A6. Python 类型注解/Pydantic 在项目里的价值？**
- 骨架：请求校验、响应序列化、IDE/重构、文档；`from_attributes` 从 ORM 转。
- 证据：`schemas/*`、`response_model=Response[...]`。
- 追问：`model_validate` 和 `model_dump` 区别？

**A7. 装饰器怎么实现缓存？有什么坑？**
- 骨架：包装函数、生成 key、序列化结果；坑：不可序列化、副作用、缓存穿透、参数顺序。
- 证据：`core/cache.py:162-218` 的 `@cached`；目前未大量使用。
- 追问：为什么 LLM 回答缓存要谨慎？

**A8. 大文件/大响应怎么处理内存？**
- 骨架：流式读/分块、临时文件、背压；不要一次 `read()`。
- 证据：`document_service.py:89` 一次性读入；上传上限 50MB。
- 追问：如何限制上传大小且不读入内存？

### B. FastAPI / HTTP（8 题）

**B1. `Depends` 的原理？**
- 骨架：依赖图、递归解析、缓存同请求结果、可 `yield` 清理。
- 证据：`routers/v1/__init__.py` 的 `get_current_user`、`get_db`。
- 追问：依赖里抛异常，响应会怎样？

**B2. 中间件与依赖的区别？执行顺序？**
- 骨架：中间件包住整个 ASGI 请求；依赖在路由解析阶段；CORS 中间件最外层之一。
- 证据：`main.py:71-91` CORS + RateLimitMiddleware。
- 追问：限流放中间件还是依赖？为什么项目两处都有？

**B3. `StreamingResponse` 怎么实现 SSE？**
- 骨架：`media_type="text/event-stream"`、`data: ...\n\n`、禁用缓冲；异常在响应头发出后无法改状态码。
- 证据：`routers/v1/chat.py:142-192`、`agent.py:80-136`。
- 追问：Nginx 需要什么配置？客户端怎么判断结束？

**B4. 请求体校验失败怎么统一格式？**
- 骨架：`RequestValidationError` handler；返回 `code/message/data.errors`。
- 证据：`core/exceptions.py:64-85`。
- 追问：422 和 400 的区别？

**B5. 为什么用 `OAuth2PasswordBearer`？**
- 骨架：从 `Authorization: Bearer` 取 token、自动 401、OpenAPI 集成；登录表单可 `OAuth2PasswordRequestForm`。
- 证据：`routers/v1/__init__.py:21`。
- 追问：和 Cookie Session 的取舍？

**B6. `response_model` 做了什么？**
- 骨架：序列化/过滤字段/生成 OpenAPI；防止泄露密码等。
- 证据：`Response[UserResponse]` 不含 `hashed_password`。
- 追问：`response_model_exclude_none` 有什么用？

**B7. 后台任务怎么做？**
- 骨架：`BackgroundTasks` 轻量、同进程；重活上 Celery/Arq/RQ；要考虑重试/幂等/进度。
- 证据：当前上传同步（GAP-014），W5 改后台。
- 追问：进程重启，未完成任务怎么办？

**B8. API 版本化/分页怎么设计？**
- 骨架：`/api/v1` 前缀；分页 `page/page_size` 或游标；返回 `items/total/page/page_size`。
- 证据：`schemas/common.py`、各列表路由。
- 追问：深分页为什么慢？怎么优化？

### C. MySQL / SQLAlchemy（8 题）

**C1. 索引原理与最左前缀？**
- 骨架：B+ 树、聚簇/二级索引、回表、覆盖索引；联合索引最左匹配。
- 证据：`models/*` 的 `index=True`；`document_chunks.document_id` 索引。
- 追问：为什么给 `status` 建索引？什么时候不该建？

**C2. 事务隔离级别与幻读？**
- 骨架：RC/RR、MVCC、间隙锁；MySQL 默认 RR。
- 证据：`get_mysql_db` 的 commit/rollback；双库无法一个事务。
- 追问：双库删除怎么保证一致性？

**C3. 什么是 N+1？项目哪里存在？**
- 骨架：1 次列表 + N 次关联；用 join/`selectinload`/聚合。
- 证据：`chat_service.py:192-204` 每个会话 count；`knowledge_base_service.py:46-50` 每个 KB count。
- 追问：怎么用一条 SQL 拿到会话+消息数？

**C4. async SQLAlchemy 的会话/连接池？**
- 骨架：`async_sessionmaker`、`expire_on_commit=False`、pool_size/max_overflow/pre_ping。
- 证据：`database/session.py:20-49`。
- 追问：会话泄露会怎样？怎么发现？

**C5. ORM 与原生 SQL 怎么选？**
- 骨架：ORM 开发快/可维护；复杂查询/向量/批量用 SQL；避免 N+1。
- 证据：`document_repo.similarity_search` 用 ORM 表达 pgvector 算子。
- 追问：`selectinload` 和 `joinedload` 区别？

**C6. Alembic 迁移怎么做？双库怎么办？**
- 骨架：`revision --autogenerate`、`upgrade head`、回滚；双 metadata/多 bind。
- 证据：`alembic/env.py` 目前只绑 MySQL；versions 为空（GAP-011）。
- 追问：生产怎么做到零停机迁移？

**C7. 双库一致性怎么保证？**
- 骨架：明确主库、应用层编排、补偿/清扫、幂等、最终一致；不要跨库事务。
- 证据：删 KB 不清 PG（GAP-015）；`DocumentChunk` 无 FK。
- 追问：删除失败一半怎么办？

**C8. 慢查询怎么定位？**
- 骨架：慢日志、`EXPLAIN`、索引、回表、排序/临时表、数据量。
- 证据：向量检索无 ANN 索引（GAP-004）。
- 追问：`EXPLAIN` 里 `type=ALL` 说明什么？

### D. Redis / 缓存 / 限流（7 题）

**D1. 项目用 Redis 做什么？**
- 骨架：LLM 响应缓存、文档切片缓存、限流计数、连接管理。
- 证据：`core/cache.py`、`rate_limiter.py`、`redis_client.py`。
- 追问：Redis 挂了业务会怎样？

**D2. 缓存穿透/击穿/雪崩？**
- 骨架：空值缓存/布隆；互斥锁/逻辑过期；过期时间加随机。
- 证据：当前缓存键 `md5(messages+model)`，无空值保护（GAP-022 相关）。
- 追问：LLM 缓存适合用哪种？

**D3. 限流算法有哪些？项目用的哪种？**
- 骨架：固定窗口、滑动窗口、令牌桶、漏桶；项目实际是固定窗口（注释写滑动，GAP-021）。
- 证据：`rate_limiter.py:114-123`。
- 追问：窗口交界双倍问题怎么解？

**D4. 为什么限流要 fail-open？什么时候 fail-close？**
- 骨架：缓存/限流非核心可放行；核心检索/鉴权应 fail-close。
- 证据：`rate_limiter.py:108-110`、`deps.py:19-32`。
- 追问：Redis 故障时每个请求重连 3s 怎么办？

**D5. 缓存键怎么设计？怎么失效？**
- 骨架：业务前缀 + 版本 + 关键参数哈希；写后失效/过期；避免跨用户泄露。
- 证据：`cache.py:53-66`。
- 追问：embedding 改了，旧缓存怎么办？

**D6. Redis 持久化与高可用？**
- 骨架：RDB/AOF、主从、哨兵/集群；缓存可丢，限流计数可丢。
- 证据：当前单容器 `redis:7-alpine`。
- 追问：Redis 重启后限流计数会怎样？

**D7. 分布式锁怎么实现？项目需要吗？**
- 骨架：`SET NX PX` + 唯一值 + Lua 释放；项目当前无并发写同一资源的场景。
- 证据：无锁代码；上传/索引未来可能需要。
- 追问：锁过期但业务没完成怎么办？

### E. LLM 基础（8 题）

**E1. token 是什么？上下文窗口怎么算？**
- 骨架：子词单位；输入+输出 ≤ 窗口；中文约 1 字 ≈ 1 token（粗略）；要预留输出。
- 证据：`llm_service.count_tokens` 存在但未用（GAP-017）。
- 追问：你怎么保证不超窗口？

**E2. temperature/top_p 怎么影响输出？**
- 骨架：温度低更确定；top_p 核采样；RAG 问答建议低温度。
- 证据：`LLM_TEMPERATURE=0.7`（可讨论是否适合问答）。
- 追问：为什么 0.7 可能不适合知识库问答？

**E3. 流式输出怎么实现？首 token 延迟怎么优化？**
- 骨架：`stream=True`、逐 chunk；减少 prompt、模型选择、并发检索、工具阶段缩短。
- 证据：`chat_stream`、Agent 伪流式（GAP-018）。
- 追问：流式下怎么统计 token/成本？

**E4. Function Calling 的协议？**
- 骨架：tools schema、`tool_calls`、assistant 消息、tool 消息回填、再调用。
- 证据：`llm_service.chat_with_tools`、`agent/graph.py`、`tools.py`。
- 追问：模型返回非法 JSON 怎么办？

**E5. Prompt 注入怎么防？**
- 骨架：文档内容标记为数据、系统提示优先级、输出过滤、工具白名单、权限校验。
- 证据：RAG 文档直接拼进 system prompt（GAP-034）。
- 追问：用户问“忽略以上指令”怎么办？

**E6. 怎么降低幻觉？**
- 骨架：检索、阈值、引用、要求“不知道就说不知道”、低温度、评测。
- 证据：`_build_rag_system_prompt` 目前允许“没找到也基于知识回答”（GAP-012 相关）。
- 追问：检索不到时应该怎么回答？

**E7. 多模型/供应商怎么抽象？**
- 骨架：配置 base_url/model、统一 OpenAI 兼容、fallback、按会话选模型。
- 证据：`ChatSession.model_name` 只记录不生效（GAP-033）。
- 追问：主模型 5xx 怎么切备？

**E8. LLM 成本怎么估？**
- 骨架：输入/输出 token × 单价；缓存命中；上下文裁剪；小模型分流。
- 证据：无 usage 埋点（GAP-022）。
- 追问：一次 RAG 问答大概多少 token？

### F. RAG（14 题）

**F1. 什么是 RAG？为什么需要？**
- 骨架：检索外部知识增强生成；解决知识过期/幻觉/私有数据；可溯源。
- 证据：`rag/*`、`chat_service._retrieve_rag_context`。
- 追问：RAG 和微调怎么选？

**F2. 完整 RAG 链路？**
- 骨架：解析→切片→embedding→存储→检索→重排→拼 prompt→生成→引用/评测。
- 证据：`document_service.upload`、`retriever.retrieve`、`chat_service`。
- 追问：哪一步最容易出问题？

**F3. 为什么要切片？chunk_size 怎么定？**
- 骨架：上下文窗口/检索粒度/成本；字符 vs token；中文分隔符；overlap。
- 证据：`text_splitter.py`、`VECTOR_CHUNK_SIZE=500`（无实验）。
- 追问：500 是字符还是 token？有对比数据吗？

**F4. embedding 模型怎么选？维度意味着什么？**
- 骨架：中文效果、成本、维度、最大输入、是否归一化；维度必须与列/索引一致。
- 证据：`BAAI/bge-m3` 1024；DB 曾 1536（GAP-002）。
- 追问：换模型要重建什么？

**F5. pgvector 和专用向量库怎么选？**
- 骨架：数据量、QPS、过滤、运维、事务；pgvector 简单、SQL 友好。
- 证据：Docker PG + pgvector 0.8.3；无 ANN 索引（GAP-004）。
- 追问：千万级向量还用它吗？

**F6. HNSW 和 IVFFlat 区别？**
- 骨架：HNSW 图、召回高、建慢/占内存；IVFFlat 聚类、需训练、lists；数据量大才建。
- 证据：当前无索引；W2 建 HNSW。
- 追问：`m`/`ef_construction`/`ef_search` 怎么调？

**F7. 余弦相似度/距离怎么算？**
- 骨架：`cosine_distance = 1 - cos`；pgvector `<=>`；相似度 = `1 - distance`。
- 证据：`document_repo.py:164-167`。
- 追问：归一化后内积和余弦关系？

**F8. top_k 和阈值怎么定？**
- 骨架：召回率/上下文长度/成本；阈值需评测，不能拍 0.7；不同模型分布不同。
- 证据：`VECTOR_TOP_K=5`、`THRESHOLD=0.7`；主链路未用阈值（GAP-012 相关）。
- 追问：阈值太高/太低分别怎样？

**F9. 混合检索怎么做？RRF 是什么？**
- 骨架：向量 + 关键词（BM25/tsvector）；RRF 按排名倒数融合，避免分数尺度问题。
- 证据：当前只有向量一路；PG 有 `tsvector` 未用。
- 追问：中文全文检索怎么分词？

**F10. Rerank 是什么？为什么需要？**
- 骨架：召回广、排序准；交叉编码器看 query-doc 交互；top20→top5；成本/延迟。
- 证据：当前无 rerank。
- 追问：双塔和交叉编码器区别？

**F11. 多轮对话检索 query 怎么处理？**
- 骨架：query 改写/指代消解；用历史+当前压成独立查询；否则“那这个呢”检索跑偏。
- 证据：`chat_service` 直接拿当前句检索。
- 追问：什么时候改写？成本怎么控？

**F12. 引用溯源怎么做？**
- 骨架：检索结果带 chunk_id/文档名/页码；prompt 要求编号；前端展示；评测引用覆盖率。
- 证据：当前未返回引用（GAP-034）。
- 追问：模型引用错了怎么办？

**F13. RAG 怎么评测？**
- 骨架：检索 recall@k/MRR、回答忠实度/相关性/引用覆盖；LLM-as-judge + 人工抽检；回归基线。
- 证据：`tests/` 无评测（GAP-012）；W2 建 25+ QA。
- 追问：没有标注数据怎么办？

**F14. RAG 常见失败模式？**
- 骨架：解析失败/切片断/embedding 失败/检索不到/阈值过高/上下文超限/模型不用上下文/引用错。
- 证据：本项目“0 向量 + 静默失败”就是典型。
- 追问：怎么快速定位是哪一环？

### G. Agent / LangGraph（9 题）

**G1. Agent 和普通 workflow/聊天区别？**
- 骨架：LLM 自主决定下一步/调工具；workflow 固定路径；Agent 需要循环/守卫/成本控制。
- 证据：`agent_service`、`graph.py`。
- 追问：什么时候不该用 Agent？

**G2. ReAct 是什么？**
- 骨架：Reason→Act→Observe 循环；工具结果回填；直到给出答案。
- 证据：`call_llm → execute_tool → call_llm`。
- 追问：怎么防止死循环？

**G3. 工具调用协议长什么样？**
- 骨架：`tools` JSON Schema、`tool_calls`、`role=tool` + `tool_call_id`、再调用。
- 证据：`tools.py`、`graph.py:64-96`。
- 追问：多个工具并行调用怎么处理？

**G4. LangGraph 的 State/Node/Edge/Reducer？**
- 骨架：TypedDict State；节点函数返回增量；条件边；`Annotated[list, operator.add]` 合并。
- 证据：`state.py`、`graph.py:197-238`。
- 追问：为什么手写循环会覆盖消息？

**G5. Checkpoint 有什么用？**
- 骨架：持久化中间状态、断点续跑、人工介入、回放；需要可序列化 state。
- 证据：当前无 checkpointer；`pg_db` 不可序列化（GAP-013 相关）。
- 追问：checkpoint 存哪？怎么恢复？

**G6. Agent 成本/延迟怎么控？**
- 骨架：最大迭代、工具超时、结果截断、缓存、小模型、并行工具。
- 证据：`max_iterations=10` 硬编码（GAP-007）。
- 追问：10 轮够吗？怎么定？

**G7. 工具安全怎么保证？**
- 骨架：白名单、参数校验、权限校验、超时、沙箱、审计。
- 证据：`calculator` AST 白名单；`knowledge_retrieval` 未下推 KB（GAP-006）。
- 追问：用户让 Agent 删库怎么办？

**G8. 多 Agent 有必要吗？**
- 骨架：按职责拆分（检索/写作/审核）；代价是协调/成本/调试；单 Agent 够用先不拆。
- 证据：当前单 Agent。
- 追问：什么时候拆？

**G9. Agent 怎么评测？**
- 骨架：任务成功率、工具选择准确率、迭代数、延迟、成本、失败分类；固定用例集。
- 证据：当前无 Agent 评测。
- 追问：怎么构造用例？

### H. 安全（8 题）

**H1. JWT 结构？怎么防篡改/过期？**
- 骨架：header.payload.signature；HS256；`exp`；`type` 防混用。
- 证据：`core/security.py`。
- 追问：密钥泄露怎么办？

**H2. 密码为什么要 bcrypt？**
- 骨架：加盐、慢哈希、抗彩虹表/暴力；不要 MD5/SHA。
- 证据：`security.py:21-44`；passlib/bcrypt 版本告警（GAP-037）。
- 追问：bcrypt 成本因子怎么定？

**H3. 越权怎么防？**
- 骨架：每个资源校验 owner；管理端角色；不要只靠前端隐藏。
- 证据：`verify_owner`、`get_current_admin`。
- 追问：水平/垂直越权区别？

**H4. 文件上传风险？**
- 骨架：类型/大小/内容校验、文件名净化、路径穿越、病毒、存储隔离。
- 证据：`document_service.py:305-326` 未净化 filename（GAP-014）。
- 追问：怎么防 `../../`？

**H5. 密钥怎么管理？**
- 骨架：环境变量/密钥管理、轮换、最小权限、不入库、扫描。
- 证据：`.env` 有真实 key、JWT 默认（GAP-009）。
- 追问：CI 里怎么注入？

**H6. CORS/XSS/CSRF？**
- 骨架：CORS 白名单；XSS 输出转义/CSP；CSRF token/SameSite；Bearer 降低 CSRF 但 localStorage 有 XSS 风险。
- 证据：CORS 仅 3000（GAP-024）；token 在 localStorage（GAP-020）。
- 追问：httpOnly cookie 怎么配合 CSRF？

**H7. SQL 注入怎么防？**
- 骨架：参数化/ORM；不要字符串拼接；最小权限。
- 证据：SQLAlchemy 表达式。
- 追问：`text()` 里拼字符串有什么风险？

**H8. 限流/登录爆破怎么防？**
- 骨架：IP/用户/全局、失败锁定、验证码、MFA、告警。
- 证据：`rate_limiter.py`；无失败锁定（GAP-021）。
- 追问：分布式限流怎么做？

### I. 部署 / 运维（8 题）

**I1. Docker 镜像分层/瘦身？**
- 骨架：基础镜像、依赖层缓存、多阶段、.dockerignore、非 root。
- 证据：当前无 Dockerfile（GAP-025）。
- 追问：为什么镜像要非 root？

**I2. Compose 网络/卷/依赖？**
- 骨架：service 名解析、命名卷、healthcheck、depends_on condition。
- 证据：当前 PG/Redis 手工容器；W7 Compose。
- 追问：数据库启动慢，API 怎么等？

**I3. Nginx 反代 SSE 注意什么？**
- 骨架：`proxy_buffering off`、超时、HTTP/1.1、gzip 关闭、`X-Accel-Buffering`。
- 证据：`chat.py:184-191` 已设头。
- 追问：为什么浏览器能逐字显示？

**I4. CI/CD 流水线怎么设计？**
- 骨架：lint→test→build→push→migrate→deploy→smoke；回滚；密钥。
- 证据：当前无 CI。
- 追问：迁移失败怎么回滚？

**I5. 可观测性三支柱？**
- 骨架：logs/metrics/traces；request_id；LLM 调用埋点；告警。
- 证据：当前只有 print（GAP-023）。
- 追问：一次慢请求怎么定位？

**I6. 备份/恢复怎么做？**
- 骨架：全量+增量、异地、定期演练、RTO/RPO；数据库 dump。
- 证据：`database-backups/` 有 dump，无脚本/演练（GAP-038）。
- 追问：恢复到某个时间点怎么做？

**I7. 配置怎么管理？**
- 骨架：12-factor、环境变量、分环境、密钥分离、启动校验。
- 证据：`.env` 依赖 CWD（GAP-024）。
- 追问：配置错了怎么快速发现？

**I8. 扩容/性能瓶颈？**
- 骨架：无状态 API 水平扩；DB 读写分离/索引；Redis；向量库；队列；限流。
- 证据：当前单机。
- 追问：10 倍用户先扩哪？

### J. 项目 / 行为 / 系统设计（10 题）

**J1. 2 分钟介绍项目？** 见 §1.1。
**J2. 最难的问题？**
- 骨架：RAG 假工作（0 向量/维度/静默）→ 定位方法 → 修复 → 防复发。
- 证据：`docs/GAP_ANALYSIS.md` GAP-001/002/003。
**J3. 最大的取舍？**
- 骨架：双库 vs 单库；同步上传 vs 异步；LangGraph vs while；SSE vs WS。
- 证据：`ARCHITECTURE.md` 决策表。
**J4. 为什么双库？**
- 骨架：MySQL 业务成熟；PG 向量/扩展；代价是一致性。
- 证据：`models/document.py` 无 FK 注释。
**J5. 重做会改什么？**
- 骨架：先评测再调参；先 pgvector 客户端验证；日志/request_id 前置；上传异步。
- 证据：GAP 清单。
**J6. 10 倍数据/用户怎么办？**
- 骨架：索引/ANN、分页/游标、缓存、异步、读写分离、队列、限流、对象存储。
- 证据：GAP-004/016/022/025。
**J7. 怎么和产品/前端协作？**
- 骨架：接口契约、错误码、联调、验收标准、灰度。
- 证据：统一响应/`/docs`。
**J8. 失败/线上事故经历？**
- 骨架：现象→影响→定位→修复→复盘→防复发。
- 证据：可讲“向量 0 条但状态 completed”。
**J9. 为什么做这个项目？**
- 骨架：企业知识分散/幻觉/权限；想练完整 AI 应用链路；持续迭代。
**J10. 你有什么问题问我们？**
- 骨架：团队 AI 应用场景、评测/上线流程、技术栈演进、On-call。

---

## 4. 四张必画图（白板 5 分钟内）

1. **整体组件图**：浏览器 → FastAPI → MySQL/PG/Redis → LLM/Embedding。
2. **RAG 检索时序**：问题 → embedding → pgvector top-k → 拼 prompt → 生成 → 引用。
3. **上传流水线**：校验 → 落盘 → Document → 解析 → 切片 → PG → embedding → completed。
4. **Agent 状态机**：CallLLM → (tool_calls?) → ExecuteTool → CallLLM → Done/上限兜底。

画图要点：标出**失败路径**与**降级策略**，面试官最关心这个。

---

## 5. 三分钟 demo 脚本

1. 登录（展示 JWT/受保护路由）。
2. 建知识库，上传一份 PDF/Markdown，展示切片数量/状态。
3. 提问，展示流式 + 引用来源。
4. 切到 Agent，问“计算 1024*768”并展示工具调用卡片。
5. 打开 `/health` 或日志，展示 request_id/依赖状态。
6. 说一句已知限制 + 下一步（诚实加分）。

---

## 6. 模拟面试评分表

| 维度 | 1 分 | 3 分 | 5 分 |
|---|---|---|---|
| 项目叙事 | 背功能 | 有背景/取舍 | 有数据/反思/演进 |
| 架构 | 说不清层 | 能画图 | 能讲失败路径与替代方案 |
| RAG | 背三步 | 讲清切片/检索/评测 | 有指标、失败案例、优化对比 |
| Agent | 背概念 | 讲清循环/工具 | 讲守卫/成本/评测/安全 |
| 工程化 | 只会跑 | 测试/日志/迁移 | 部署/故障演练/可观测 |
| 表达 | 冗长 | 结构清楚 | 先结论后展开、能量化 |
| 诚实 | 硬编 | 承认不足 | 不足+改进计划+证据 |

---

## 7. 证据链清单（面试前准备）

- [ ] `prove_rag` 输出截图/日志。
- [ ] `recall@5` 评测报告（baseline/改进）。
- [ ] 3 个 bug 的修复 diff + 测试。
- [ ] 压测/延迟/成本表。
- [ ] Docker Compose 一键起录屏/截图。
- [ ] 3 个故障演练记录。
- [ ] 4 张图（手画/导出）。
- [ ] 简历 bullet 与证据一一对应。

---

## 8. 反问清单（面试尾声）

- 团队目前 AI 应用的核心场景与用户量？
- RAG/Agent 的评测与上线流程？
- 模型选型/成本控制谁负责？
- 新人前 3 个月的期望？
- 是否有 On-call/事故复盘机制？

---

## 9. 常见“送命题”与应对

| 问题 | 不要答 | 应该答 |
|---|---|---|
| 你的 RAG 准确率多少？ | 编一个数字 | “我正在建 25 条评测集，baseline 是 __，改进后 __；指标脚本在 __” |
| 为什么用 LangGraph？ | “因为流行” | 状态/边/checkpoint 的可扩展性；当前也承认有过度设计风险 |
| 双库不麻烦吗？ | “还好” | 讲一致性代价、补偿/清扫、何时会合并 |
| 你的项目有什么不足？ | “没有” | 列 3 条 + 改进计划（评测/异步/可观测） |
| 这些是你写的吗？ | 含糊 | 讲你负责的模块、修过的 bug、能现场定位 |

> 面试官最想确认的是：**你真的做过、真的想过、真的能改。** 这三件事只能靠代码、数据和复盘证明。
