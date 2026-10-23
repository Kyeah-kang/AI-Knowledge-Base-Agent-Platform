# LEARNING.md — 项目带学总清单与三周计划

> 配套文档：《面试审计报告_逐项可改.md》是本清单的内容来源，薄弱点的"面试官怎么问/代码现状证据"都在报告里，本表只做追踪与排程。报告标了 `文件:行号`，本表把锚点换成真实路径（相对 `backend/` 或 `backend/app/`）。
> 生成日期：2026-09-04。

---

## 〇、三条铁律（每节课都要遵守）

1. **教练不写代码**：我只讲原理、指位置、给思路、考你。**代码全部你自己写。** 你也不要叫我"帮我改/帮我写"，我会拒绝。
2. **五步流程**：每个薄弱点按 `我读代码 → 我复述 → 教练追问 → 我动手修 → 教练验收` 走完才算过。卡在哪一步就停在哪一步，别跳。
3. **【讲】的过关标准**：能口头讲清 **+** 能现场画出来（架构/时序/状态机草图）。不是"看过懂了"，是"讲给别人听、对方能听懂"。

## 一、名词图例

| 标记 | 含义 | 过关标准 |
|---|---|---|
| 【手】 | 动手项：改代码、跑通 | 达成对应验收标准（有可复现结果/输出） |
| 【讲】 | 讲清项：备讲稿 + 画图 + 被追问 | 见铁律③ |
| 【讲+手】 | 先讲清原理，再用最小代码把原理落到项目里 | 两个标准都要，手是练讲的证据 |
| ⬜ / 🟨 / ✅ | 状态：未开始 / 进行中 / 已完成 | 完成日期填当天 |

## 二、Part A — 19 个薄弱点清单

> 每过完一遍就把"状态/完成日期"更新；"我的笔记"写你复述时的卡壳点；"遗留疑问"写追问没答上的，攒着下次对练。

| # | 优先级 | 类型 | 代码锚点（先自己读） | 过关标准 | 关联R | 状态 | 完成日期 | 我的笔记 | 遗留疑问 |
|---|---|---|---|---|---|---|---|---|---|
| 薄弱点1 embedding 配置自相矛盾 / 链路没跑通 | P0 | 手+讲 | `backend/app/core/config.py:82-91`、`backend/app/rag/embeddings.py`、`backend/app/rag/retriever.py:77-99`、`backend/app/services/document_service.py:150-156` | 讲：说清"我的 embedding 到底在调谁、什么维度、为什么用 ta"；手：`prove_rag.py` 打印向量维度=DB 列维度、检索返回非空 chunk | R1 R2 R4 | ⬜ | | | |
| 薄弱点2 pgvector 无索引=全表扫描 | P0 | 讲+手 | `backend/app/repositories/document_repo.py:155-185`、`scripts/init_db.py` 建表处 | 讲：10 行讲清 HNSW vs IVFFlat、近似检索为何"只影响快不影响对"；手：已建 `hnsw (embedding vector_cosine_ops)` | R7 | ⬜ | | | |
| 薄弱点3 无 Rerank/无混合检索/无 query 改写 | P0/P1 | 讲(+手加分) | `backend/app/rag/retriever.py:77-99`、`backend/app/services/chat_service.py:294-298`（拿当前句原文检索） | 讲：召回要广/排序要准、双塔 vs 交叉编码、RRF 合并、多轮指代需 query 改写——能画两条路汇合的图；加分：R13/R14 demo 跑通 | R13 R14 | ⬜ | | | |
| 薄弱点4 无评测集无指标 | P0 | 手+讲 | `backend/tests/`（现状只有桩测试）、`backend/app/repositories/document_repo.py` 检索入口 | 手：`data/eval_qa.jsonl` ≥20 条真实 QA + `scripts/evaluate.py` 输出 `recall@5=0.xx`；讲：说出数字、评测集怎么来的 | R5 | ⬜ | | | |
| 薄弱点5 chunk 参数拍脑袋 | P0 | 讲+手 | `backend/app/core/config.py:99-104`、`backend/app/rag/text_splitter.py`（53 行 separators / 103 行 `len`）、`backend/app/rag/document_parser.py:90`（页标混正文） | 讲：完整推理链——500 是字符非 token、中文≈1字≈1token、overlap 保跨块断点、同代码切英文差异、页码该做 metadata；手：300/500/800 对比表进 `总结.md` | R8 | ⬜ | | | |
| 薄弱点6 双库架构理由与一致性 | P0 | 讲+手 | `backend/app/models/document.py`（无FK注释）、`backend/app/services/knowledge_base_service.py` 删除处、`backend/app/services/document_service.py:258-275` | 讲：拆库理由、删 KB 时 PG 谁删（先承认 bug）、迁移正确姿势（create_all 只建不改/alembic autogenerate）、演进取舍；手：删 KB 后 PG 无孤儿 | R9 | ⬜ | | | |
| 薄弱点7 LangGraph 名不副实 | P0 | 讲+手 | `backend/app/agent/graph.py`（206-238、287-314）、`backend/app/agent/state.py`、`backend/app/services/agent_service.py:313-395` | 讲：节点/边/`operator.add` reducer/checkpoint/断点续跑、"图 vs while"差别；手：进程级单例编译一次（用上 `_agent_app` 缓存）+ MemorySaver 试通 | R12 | ⬜ | | | |
| 薄弱点8 多轮上下文粗暴截 20 条 | P0 | 手+讲 | `backend/app/services/chat_service.py:404-420`、`backend/app/services/agent_service.py:459-467`、`backend/app/services/llm_service.py:212-220`（`count_tokens` 0 调用）、`backend/app/repositories/chat_repo.py:38`（updated_at 假排序） | 手：token 预算滑窗（≈8000 从新到老累加）+ `count_tokens` 真用上 + 发消息 touch `updated_at`；讲：预算制 vs 按条截断、与 LangChain Memory 模块的差别（诚实：现在没用任何 Memory） | R10 | ⬜ | | | |
| 薄弱点9 自建工具只有 schema 没 executor | P0/P1 | 手 | `backend/app/repositories/agent_repo.py:84-101`、`backend/app/services/agent_service.py:118-127`、`backend/app/agent/tools.py:109-118/153-161`（tool_map 只有 3 个真实现） | 手：动态工具 executor 打通或接口/UI 明确"仅演示 schema"；至少能主动说出这是个洞 | R17a | ⬜ | | | |
| 薄弱点10 迭代守卫边界丢结果 | P1 | 手 | `backend/app/agent/graph.py:169-189/379-383`、`backend/app/agent/state.py:66` | 手：到上限仍要工具时执行完/给"已达迭代上限"明确文案；空回答兜底；上限读配置 | R17b | ⬜ | | | |
| 薄弱点11 工具失败无重试 + mock 结果污染 | P1 | 手 | `backend/app/agent/tools.py:163-168/190-204` | 手：同一工具连续失败计数停用并把控制权还 LLM；开发期未配 key 不把"模拟结果"当 tool 消息发给模型（禁定义或加⚠前缀）；结果截断 | R17c | ⬜ | | | |
| 薄弱点12 无引用溯源、主链路没用阈值 | P1 | 手 | `backend/app/rag/retriever.py:145-200`（retrieve vs retrieve_with_details 行为不一致）、`backend/app/services/chat_service.py` RAG prompt 注入处 | 手：主链路统一阈值分支——低于→显式"未找到"不硬编；prompt 要求末尾给引用编号/文件名；前端可展出来源 | R11 | ⬜ | | | |
| 薄弱点13 LLM 无超时无重试 | P0 | 手+讲 | `backend/app/services/llm_service.py:26-29`（没传 timeout，SDK 默认 600s）、三个调用方法全无重试、`backend/app/rag/embeddings.py:45-48` | 手：`AsyncOpenAI(timeout=...)` + tenacity（429/5xx/连接错误，指数退避+抖动），模拟故障能自动重试成功；讲：为什么退这些状态码、为何加抖动 | R6 | ⬜ | | | |
| 薄弱点14 安全：JWT 默认密钥等 | P0 | 手+讲 | `backend/app/core/config.py:75-76`、`.env`、`test_token.txt`、`backend/app/core/security.py:86-107`、登录 bcrypt 处 | 手：换随机 64B secret、`.env` 进 `.gitignore`、删 `test_token.txt`、DEBUG 默认关；讲：JWT 三段/为何改一个字符失效、access 短 refresh 长、`type` 防混用、bcrypt 抗彩虹表、登录错误信息统一 | R3 | ⬜ | | | |
| 薄弱点15 限流注释与实现不符 | P1 | 讲+手 | `backend/app/core/rate_limiter.py:24`（自称滑动）、114-123（实为固定窗口）、108-110（fail-open）、191/206、`backend/app/routers/v1/__init__.py:59-69` | 讲：诚实讲"固定窗口 + Redis 计数器"，固定 vs 滑动 tradeoff、窗口交界可双倍、fail-open 是有意权衡；手：登录失败锁定（Redis `fail:{username}` 5 次锁 15 分钟）+ 合并重复 user 限流 | R19 | ⬜ | | | |
| 薄弱点16 核心故障静默降级、无日志基建 | P1 | 手+讲 | `backend/app/repositories/document_repo.py:179-181`、`backend/app/rag/retriever.py:97-99`、`backend/app/core/deps.py:19-32`、`redis_client.py`、`backend/app/main.py:125-128`（health 不探活） | 手：request_id 中间件 + 日志写文件 + LLM usage/tokens/latency 埋点 + `/health` 探活 DB/Redis；讲：分类降级原则（缓存/限流可静默、核心检索必须显式失败） | R18 | ⬜ | | | |
| 薄弱点17 大文件同步阻塞 + embedding 一把梭 | P1/P2 | 讲+手 | `backend/app/services/document_service.py:85-160`（上传/解析在 async 里跑同步 CPU）、`backend/app/rag/embeddings.py:109-114`（一次全发）、状态机 stuck | 讲：为什么 50MB 会卡事件循环、embed 一次全发为何必撞 provider 上限、BackgroundTasks vs Celery 取舍；手：上传只入 pending→后台任务解析/切片/embed 分批（32/64）→进度可查→启动清扫 stuck | R15 | ⬜ | | | |
| 薄弱点18 重复上传无去重、无 KB 级向量过滤 | P2/P1 | 手 | `backend/app/services/document_service.py` 上传入口、`backend/app/repositories/document_repo.py:172-173`、`backend/app/services/chat_service.py:106`（limit=9999） | 手：sha256 同 KB 同 hash 拒绝/提示覆盖；加分：chunk 冗余 `knowledge_base_id` 下推过滤，检索单条 SQL 限定 KB、顺带解 9999 | R16 | ⬜ | | | |
| 薄弱点19 N+1 与缓存键 | P2 | 讲(+小修) | `backend/app/services/chat_service.py:192-204`（list_sessions N+1）、`backend/app/services/knowledge_base_service.py`（KB doc_count N+1）、`backend/app/core/cache.py:53-56`（缓存键=md5(messages+model)） | 讲：能算出"50 会话发多少 SQL"、怎么用一次 `GROUP BY count`/`selectinload` 修、LLM 缓存键该含什么、为何 LLM 回答缓存要谨慎；小修可选 | — | ⬜ | | | |

## 三、Part B — R1~R19 任务清单

> 验收标准基本照搬报告路线图。改完一项就勾一项，并在"我的笔记"里写**你改了什么、为什么这么改**（这是复述素材）。

| # | 批次 | 类型 | 干什么 | 验收标准 | 状态 | 完成日期 | 我的笔记 | 遗留疑问 |
|---|---|---|---|---|---|---|---|---|
| R1 | 一·今晚 | 手 | 修 embedding 链路：选真能用的 OpenAI 兼容中文模型（智谱 `embedding-3` / 硅基流动 `bge-m3`，或本地 `sentence-transformers/bge-m3`），填对 `.env` | `prove_rag.py` 打印向量维度=DB 列维度、检索返回非空 chunk | ⬜ | | | |
| R2 | 一·今晚 | 手 | embedding/检索失败改显式：上传失败标 `failed`、检索失败 `logger.error` + 区分事件 | 断 embedding key 重传 → 状态 failed；检索断连 → 明确报错而非"没结果" | ⬜ | | | |
| R3 | 一·今晚 | 手 | 换随机 JWT secret、`.env` 进 `.gitignore`、删 `test_token.txt`、DEBUG 默认关 | clone 环境无法伪造 token；生产 `/docs` 不可见 | ⬜ | | | |
| R4 | 一·今晚 | 手 | 写 `backend/scripts/prove_rag.py`（embed→search→打印 top chunk） | 一键可复现"检索真的工作" | ⬜ | | | |
| R5 | 一·今晚 | 手 | 建 `backend/data/eval_qa.jsonl` 20~30 条 + `scripts/evaluate.py` 算 recall@k | 能输出一行 `recall@5 = 0.xx` | ⬜ | | | |
| R6 | 一·今晚 | 手 | LLM 加 timeout + tenacity 重试（429/5xx/连接错误，退避+抖动） | 模拟 5xx/断网，请求自动重试后成功 | ⬜ | | | |
| R7 | 二·本周 | 讲+手 | PG 建 HNSW 索引（`vector_cosine_ops`）；备 IVFFlat vs HNSW 讲稿 | `\d document_chunks` 能看到索引；能用 10 行讲清二者 | ⬜ | | | |
| R8 | 二·本周 | 手 | chunk_size 300/500/800 对比实验，结果写进 `总结.md` | 有一张"块大小 → recall"小表 | ⬜ | | | |
| R9 | 二·本周 | 手 | 修删 KB 留 PG 孤儿：删除同步清 PG + 孤儿清扫脚本 | 删 KB 后 PG `document_chunks` 无对应孤儿 | ⬜ | | | |
| R10 | 二·本周 | 手 | 多轮上下文改 token 预算滑窗；touch `session.updated_at` | 超长会话不再爆上下文；会话列表排序真实 | ⬜ | | | |
| R11 | 二·本周 | 手 | 主链路统一阈值 + 低于阈值显式"未找到"；prompt 加引用编号 | 知识库没答案时不再拿通用知识硬答 | ⬜ | | | |
| R12 | 二·本周 | 讲+手 | LangGraph 进程级单例编译一次图 + MemorySaver 试通 + 备 4 概念（节点/边/reducer/checkpoint） | 被问到能画图 + 演示断点续跑/中间态持久化 | ⬜ | | | |
| R13 | 三·有余力 | 手 | 混合检索 demo：PG `tsvector` 全文 + 向量，RRF 合并 | 关键词精确 & 语义两路都能召回 | ⬜ | | | |
| R14 | 三·有余力 | 手 | 最小 rerank：bge-reranker 或 rerank API 对 top20→top5，评测对比 | recall/回答分提升有记录 | ⬜ | | | |
| R15 | 三·有余力 | 手 | 大文件上传改后台任务 + embedding 分批 + stuck 清扫 | 传大文件接口即时返回、进度可查、进程崩了能恢复 | ⬜ | | | |
| R16 | 三·有余力 | 手 | 上传 sha256 去重 + chunk 冗余 `knowledge_base_id` 下推过滤 | 重复上传被拒；检索单条 SQL 限定 KB | ⬜ | | | |
| R17 | 三·有余力 | 手 | 修 Agent：a) 动态工具 executor 打通或明示仅演示；b) 最大迭代边界 bug；c) 失败重试计数 | a) 自建工具能被真调用 / UI 说清仅演示；b) 到上限返回明确文案不空答；c) 连续失败停用并说明 | ⬜ | | | |
| R18 | 三·有余力 | 手 | 日志基建：文件 handler + request_id 中间件 + LLM usage 埋点；`/health` 探活 | 一条完整请求可从日志串起；`/health` 反映 DB/Redis 真实状态 | ⬜ | | | |
| R19 | 三·有余力 | 讲+手 | 限流术语改对 + 修登录撞库（失败锁定）+ 合并重复检查 | 被追问"固定 vs 滑动"不翻车；5 次错锁 15 分钟能演示或讲清方案 | ⬜ | | | |

## 四、Part C — 三周逐日学习计划（每天 ≤3h）

> 说明：
> - **动手项**：自己读代码→自己改→自测，然后**回来找我验收**。
> - **讲清项 / 对练**：先自己备讲稿+画图，再**回来找我当考官追问**（我按报告的模拟题咬）。
> - 每天已把"找我验收 / 找我追问"写进当天，等于一次异步对练约 20~40 分钟，其余自学。
> - 日期按 09-05 起顺移 21 天（含周末）。若某天被占用：**先保住当天的【讲】子块（只要脑子），动手子块整体顺延**，别跳过讲只赶手。
> - 若某项 3h 内没做完：记录卡点→继续往下走，周末复盘日回来补，不恋战。

### 第 1 周 — 让 RAG 真能跑、真能测（地基，薄弱点 1/13/4/2/5）

| 天 | 日期 | 主题 | 内容（标记类型） | 找我 |
|---|---|---|---|---|
| D1 | 09-05 六 | 【手】修 embedding 并自证 | 读 `embeddings.py`+`config.py:82-91`+`retriever.py:77-99`+上传链路（40′）→ 备"现在调的是谁/为什么矛盾"（10′）→ R1 选供应商填 `.env`（40′）→ R4 写 `prove_rag.py` 跑通（50′） | 验收：prove_rag 输出 + 口答"embedding 在调谁、维度多少、为何这么选" |
| D2 | 09-06 日 | 【手】失败显式化 | 读 `document_service.py:140-160`+`retriever.py:90-100`+`document_repo.py:170-185`（30′）→ R2：embedding 失败标 `failed`、检索失败 `logger.error` 区分事件（100′）→ 补一句"为什么缓存可静默、检索不能"的讲稿（20′） | 验收：断 key 重传状态=failed；断 PG 返回明确错误 |
| D3 | 09-07 一 | 【手】LLM 超时与重试（薄弱点13） | 读 `llm_service.py` 三个方法 + `embeddings.py:45`（30′）→ R6：timeout 细分 + tenacity（429/5xx/连接，退避+抖动）（110′）→ 备"重哪些码/为何抖动"（20′） | 对练：口答重试策略 |
| D4 | 09-08 二 | 【手】建评测集 | 确认库里有可检索文档（20′）→ R5：造 `data/eval_qa.jsonl` 20~30 条（60′）+ `scripts/evaluate.py` 算 recall@5（90′） | 验收：输出一行 `recall@5=0.xx` |
| D5 | 09-09 三 | 【讲+手】向量索引（薄弱点2） | 读 `document_repo.py:155-185` + init_db 建表（20′）→ R7：建 HNSW 索引并验证（40′）→ 备"IVFFlat vs HNSW / 近似不影响对错"讲稿+画 HNSW 图（60′） | 对练：10 行讲清二者 |
| D6 | 09-10 四 | 【讲+手】分块推理链 | 读 `text_splitter.py` 全文 + `config.py:99-104`（30′）→ 备"500 是字符非 token、中文≈1字≈1token、overlap 干嘛的、切英文差异"讲稿（40′）→ R8：300/500/800 对比跑评测写进 `总结.md`（70′） | 验收：块大小→recall 小表；对练分块推理链 |
| D7 | 09-11 五 | 【讲】第一周收束 | 薄弱点 1/2/4/5/13 各口述 5 分钟+默画（检索时序 / HNSW / 评测闭环 / 上传流水线）（60′）→ 我按报告 P0 模拟题逐条追问（60′）→ 把 recall 数字与改动整理进总结（30′） | 模拟面试：薄弱点 1/2/4/5/13 追问全过 |

### 第 2 周 — 双库 / LangGraph / Agent / 多轮，修到能自圆其说

| 天 | 日期 | 主题 | 内容（标记类型） | 找我 |
|---|---|---|---|---|
| D8 | 09-12 六 | 【讲+手】双库一致性（薄弱点6） | 读 `document.py`(无FK)+`knowledge_base_service` 删除处+`document_service.py:258-275`（40′）→ 备"为什么双库 / 删 KB 时 PG 谁删(先承认 bug) / 迁移正确姿势"（30′）→ R9：删 KB 同步清 PG+孤儿清扫（80′） | 验收：删 KB 后 PG 无孤儿；对练讲双库取舍 |
| D9 | 09-13 日 | 【手】多轮上下文（薄弱点8） | 读 `chat_service.py:404-420`+`llm_service.count_tokens`+`chat_repo.py:38`（30′）→ R10：token 预算滑窗+`count_tokens` 真用上+touch `updated_at`（110′）→ 备"预算制 vs 截断 / vs LangChain Memory"讲稿（20′） | 验收：超长会话不爆、列表排序对 |
| D10 | 09-14 一 | 【手】阈值与溯源（薄弱点12） | 读 `retriever.py:145-200`（retrieve vs retrieve_with_details 为何不一致）+ chat RAG prompt（30′）→ R11：主链路统一阈值、低于→"未找到"、prompt 加引用编号（120′） | 验收：库外问题不再硬答 |
| D11 | 09-15 二 | 【讲】LangGraph 概念课（薄弱点7 前半） | 读 `graph.py` 全文（重点 169-238/287-314）+`state.py`+`agent_service.py:313-395`（70′）→ 概念课：节点/边/reducer/checkpoint/`operator.add`/图 vs while/三套循环为何是问题（40′）→ 画 Agent 状态机图（30′） | 对练：讲节点边 + 为什么每请求编译是缺陷 |
| D12 | 09-16 三 | 【手+讲】LangGraph 真用上（薄弱点7 后半） | R12：进程级单例编译（用上 `_agent_app` 缓存）(60′)+ MemorySaver/断点续跑最小演示（60′）→ 备"checkpoint 能带来什么"（20′）。**卡住先保单例编译，MemorySaver 降到"能讲清方案"** | 验收：进程只编一次图；对练 checkpoint 价值 |
| D13 | 09-17 四 | 【手】Agent 工具真相（薄弱点9/10/11） | 读 `tools.py` 全文+`agent_repo.create_tool`+`agent_service`（40′）→ R17：先做 b)迭代边界不空答 + c)失败重试计数/mock 加⚠（60′）→ 再做 a)动态工具 executor 打通 **或** UI 明示仅演示（50′） | 验收：第10轮仍要工具→明确文案；mock 不再当真 |
| D14 | 09-18 五 | 【讲】第二周收束 | 串讲薄弱点 6/7/8+默画（双库删除时序 / Agent 状态机 / 多轮滑窗示意）（60′）→ 我按报告模拟题追问（薄弱点6 三道、7 四道、8 三道）（60′）→ 补笔记与遗留疑问（30′） | 模拟面试：6/7/8 全过 |

### 第 3 周 — 安全 / 工程韧性 / 加分项冲刺

| 天 | 日期 | 主题 | 内容（标记类型） | 找我 |
|---|---|---|---|---|
| D15 | 09-19 六 | 【手+讲】安全（薄弱点14） | 读 `security.py:86-107`+`config.py:75-76`+登录 bcrypt 处（30′）→ R3：换 secret/`.env` 忽略/删 `test_token.txt`/DEBUG 关（30′）→ 备"JWT 三段/短 access 长 refresh/`type` 防混用/bcrypt"讲稿（50′） | 验收：改完四项；对练安全问答（含"能否伪造管理员"） |
| D16 | 09-20 日 | 【讲+手】限流（薄弱点15） | 读 `rate_limiter.py`（24 注释 vs 114-123 实现 vs 108-110）+v1/`__init__.py:59-69`（40′）→ 备"固定 vs 滑动 tradeoff / fail-open 是权衡"（40′）→ R19：登录失败锁定 Redis 计数 + 合并重复 user 限流（70′） | 对练：固定 vs 滑动被追问不翻车 |
| D17 | 09-21 一 | 【手】日志基建（薄弱点16） | 读 `main.py:125-128` + `deps.py`（20′）→ R18：request_id 中间件+日志写文件+LLM usage/耗时埋点+`/health` 探活 DB/Redis（130′） | 验收：一条请求能靠 request_id 串起；/health 真实 |
| D18 | 09-22 二 | 【讲+手】大文件上传（薄弱点17） | 读 `document_service.upload`+`embeddings.py:109-114`+上传入口 router（40′）→ 备"为何卡事件循环 / 全量一发必撞上限 / BackgroundTasks vs Celery"（30′）→ R15：上传只入 pending→后台任务+embed 分批(32/64)+stuck 清扫（70′）。**用 BackgroundTasks 轻量版即可，不必上 Celery** | 验收：大文件接口即时返回、进度可查 |
| D19 | 09-23 三 | 【手+讲】去重/过滤 + N+1（薄弱点18/19） | 读上传入口+`document_repo.py:172-173`+`chat_service.py:106`（30′）→ R16：sha256 去重（chunk 冗余 kb_id 下推做不了就只讲清）（70′）→ 备"50 会话发多少 SQL / 怎么用 GROUP BY count 修 / 缓存键该含什么"讲稿（50′） | 对练：N+1 与 LLM 缓存取舍 |
| D20 | 09-24 四 | 【讲+手·弹性】混合检索/rerank（薄弱点3） | 先读 `retriever` 现状与 PG 全文函数（30′）→ R13：tsvector+向量 RRF 混合 demo（90′）→ 有余力再 R14：rerank top20→top5 跑评测对比；**超时则降级为"三件套讲清课"**：召回广/排序准、交叉编码 vs 双塔、多轮指代怎么改写（60′） | 验收(做了 demo)或对练(讲清课) |
| D21 | 09-25 五 | 【讲·总冲刺】模拟面试+收表 | 默画 4 张图：上传流水线/检索时序/Agent 状态机/双库删除时序（45′）→ 我按报告把 P0/P1 模拟题全过一轮（90′）→ 逐项核对 Part A/B 状态、清遗留疑问、写"我还不会的 3 件事"（30′） | 全流程模拟面试 |

---

## 五、对练时的约定

- 你**口述**或**贴图给我看**，我追问；不许把"让我改一下代码"当请求发我，我只验收你自己改的。
- 我验收的标准就两句话：**结果可复现**（动手项）、**你能讲清+画得出**（讲清项）。
- 每次对练结束你把卡壳点写回本表"我的笔记/遗留疑问"，第二天从那里开始。

## 六、关键代码锚点速查（backend/app/ 下）

| 报告里的短名 | 真实路径 |
|---|---|
| config | `backend/app/core/config.py` |
| embeddings | `backend/app/rag/embeddings.py` |
| retriever / vector_store | `backend/app/rag/retriever.py` / `backend/app/rag/vector_store.py` |
| text_splitter / document_parser | `backend/app/rag/text_splitter.py` / `backend/app/rag/document_parser.py` |
| document_service / chat_service / llm_service / agent_service / knowledge_base_service | `backend/app/services/…_service.py` |
| document_repo / chat_repo / agent_repo / knowledge_base_repo | `backend/app/repositories/…_repo.py` |
| graph / state / tools | `backend/app/agent/{graph,state,tools}.py` |
| rate_limiter / cache / redis_client / security / deps / exceptions | `backend/app/core/…_*.py`（security→`core/security.py`） |
| main / v1 路由 | `backend/app/main.py`、`backend/app/routers/v1/__init__.py` |
| 数据库脚本 / 测试 / 迁移 | `backend/scripts/`、`backend/tests/`、`backend/alembic/versions/`（当前为空） |
