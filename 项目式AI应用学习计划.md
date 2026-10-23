# 项目式 AI 应用学习计划（两个月强化版）

## 1. 目标

以当前 `AI Knowledge Base Agent Platform` 为主线，把可运行的 Demo 演进为能够解释、评测、观测和部署的模块化单体项目，并同时准备 AI 应用开发岗位面试。

本计划保留原计划的全部主题：

- RAG：解析、切块、Embedding、pgvector、阈值、引用、混合检索、Rerank、Query Rewrite。
- LangChain：Document、TextSplitter、Embeddings、Retriever、Prompt、Runnable、Output Parser。
- LangGraph：State、Node、Edge、Reducer、Checkpoint、持久化和恢复。
- Agent：工具注册、Tool Calling、动态工具、权限、重试、超时、失败处理和 SSE。
- 评测：数据集、Recall@K、MRR、nDCG、Faithfulness、引用覆盖率、Agent 成功率和回归基线。
- 企业化：异步任务、批处理、幂等、去重、跨库一致性、日志、指标、健康检查、安全、限流、CI 和 Docker Compose。
- 面试：每周把代码、实验数据和故障处理转化成可回答的高频面试题。

## 2. 周期和时间预算

- **主计划：8 周，约两个月。**
- **每周学习 6 天，周四完全休息。**
- **每天 3–4 小时，总投入约 144–192 小时。**
- 每周日安排周总结；第 2、4、6、8 周结束安排阶段总结和费曼检验。
- 每天的时间分为：代码/原理阅读 45–60 分钟，实施或实验 90–120 分钟，测试和结果分析 45–60 分钟，面试表达和笔记 20–30 分钟。
- 8 周内完成主线目标；Kubernetes、模型训练、微调和多地域部署不纳入本轮。

## 3. 学习与协作方式

每个学习日采用以下闭环：

1. 定位当天的入口、核心代码和数据结构。
2. 解释设计目标、调用关系和关键取舍。
3. 由我完成必要的代码改造，你 Review 核心 Diff。
4. 运行单元测试、集成测试、脚本或评测实验。
5. 记录一个架构决策、一个失败案例和一个遗留问题。
6. 用“背景→方案→取舍→结果→风险”回答一个面试问题。

周四不安排项目学习、补课或强制阅读。未完成内容顺延到下一个学习日。

## 4. 费曼学习法和面试训练

每个主题都要做到：

1. 不看资料，用自己的话解释概念。
2. 画出调用链、时序图或状态图。
3. 用当前项目中的代码指出具体实现位置。
4. 说明失败方式、限制和替代方案。
5. 再回看代码，修正自己的解释。

每周日会加入面试训练：概念题、项目题、追问题、故障题和指标题。阶段总结时会进行 20–40 分钟的口述、白板图和代码定位追问。

---

# 阶段 0：基线和系统地图

## 第 1 周：读懂现有系统

### 周一：项目结构和启动基线

- 阅读后端入口、路由、Service、Repository、Model 和配置。
- 阅读前端 Chat、AgentChat、SSE Hook 和 API Client。
- 确认 MySQL、PostgreSQL/pgvector、Redis 和 OpenAI 兼容 API 的职责。
- 运行现有测试，记录当前能否启动、哪些依赖缺失、哪些功能可用。

### 周二：普通聊天调用链

- 跟踪 Router→ChatService→LLMService→消息 Repository 的完整路径。
- 解释非流式、流式和 SSE 的区别。
- 记录每一步的输入、输出、异常和持久化行为。
- 面试题：如何介绍一个 AI 应用的完整请求链路？

### 周三：文档和 Agent 调用链

- 跟踪上传→解析→切块→Embedding→向量写入。
- 跟踪 Agent→LLM→工具→工具结果→最终回答。
- 对比普通 Chat、RAG Chat 和 Agent Chat 的边界。
- 画出 RAG 时序图和 Agent 状态图。

### 周四：完全休息

### 周五：代码基线与问题清单

- 完成一次普通聊天、一次知识库检索和一次 Agent 工具调用。
- 记录当前检索延迟、回答延迟、引用情况和失败行为。
- 建立 Demo 问题清单：配置、检索、评测、工具、上下文、安全和部署。

### 周六：架构 Review

- 解释双数据库、Redis 缓存/限流和前后端边界。
- 画模块关系图和关键时序图。
- 将现有 `LEARNING.md` 中的薄弱点映射到真实代码。

### 周日：周总结

- 不看代码讲清项目架构和两条主链路。
- 面试追问：为什么采用 MySQL+PostgreSQL+Redis？线上变慢如何分层定位？
- 阶段 0 产出：架构图、基线数据、问题清单。

---

# 阶段 1：RAG 基础、可靠性和评测起点

## 第 2 周：让 RAG 真能跑、真能测

### 周一：Embedding 配置和维度

- 阅读 `config.py`、`embeddings.py`、`retriever.py` 和文档入库链路。
- 统一 Provider、模型、API Base、模型维度和 pgvector 字段维度。
- 增加 Embedding 可用性检查和明确失败信息。
- 面试题：Embedding 模型、维度和向量库字段为什么必须一致？

### 周二：解析、切块和元数据

- 阅读 PDF、DOCX、Markdown、TXT 解析逻辑。
- 将页码、章节、文件名、文档 ID 和 chunk index 放入结构化元数据。
- 比较 300/500/800 chunk size 和 overlap，记录切片数量和长度。
- 解释字符数、Token 数、中文和英文切分的差异。

### 周三：向量检索和索引

- 阅读 `DocumentChunk`、Repository 和 `VectorStore`。
- 增加知识库/文档过滤下推到数据库。
- 建立 pgvector HNSW 索引，理解 IVFFlat 与 HNSW 的取舍。
- 统一 Top-K、相似度阈值和低于阈值时的“未找到”分支。

### 周四：完全休息

### 周五：引用和失败处理

- 统一 `retrieve` 与 `retrieve_with_details` 的结果结构。
- 返回文件名、文档 ID、chunk ID、页码、相似度和引用编号。
- Embedding 失败时文档进入 `failed`，PostgreSQL 故障不能伪装成空结果。
- 前端展示检索来源和引用片段。

### 周六：RAG 证明脚本和评测集

- 增加 `scripts/prove_rag.py`，证明 Embedding→search→Top-K→引用链路。
- 建立至少 20–30 条 `data/eval_qa.jsonl`。
- 标注问题、知识库、gold chunk、参考答案、类别和难度。
- 实现 Recall@1、Recall@5、Recall@10 和 MRR 初版。

### 周日：阶段 1 总结

- 费曼复述：一个问题如何变成向量并找到正确文档？
- 面试追问：chunk size 如何选？阈值过高/过低有什么问题？如何证明检索变好了？
- 检查：Embedding 维度、HNSW、引用、失败处理和 Recall 输出是否全部可复现。

---

# 阶段 2：LangChain 和检索质量优化

## 第 3 周：LangChain 核心抽象

### 周一：Document、TextSplitter、Embeddings

- 将当前解析和切块链路映射到 LangChain 对象。
- 对比自定义分割器与 `RecursiveCharacterTextSplitter`。
- 明确框架抽象的复用收益和调试成本。

### 周二：PromptTemplate 和 Runnable

- 将 RAG Prompt 改造成结构化模板。
- 组合 Retriever、Prompt、LLM 和 Output Parser。
- 解释 Runnable 的输入输出和链式调用。

### 周三：Retriever 适配器

- 将向量检索封装为 Retriever 适配器。
- 保留业务层需要的权限、知识库过滤和引用信息。
- 明确框架 Retriever 与业务检索服务的边界。

### 周四：完全休息

### 周五：结构化输出和异常

- 定义回答结构：正文、引用、置信信息、错误状态。
- 处理空回答、格式错误、引用缺失和模型输出不符合 schema。
- 比较普通文本输出与结构化输出的稳定性。

### 周六：LangChain 参考链路

- 建立独立的最小 LangChain RAG 链。
- 与生产链路并行运行，不直接覆盖原业务模块。
- 记录 LangChain 负责什么、业务代码必须负责什么。

### 周日：周总结

- 费曼复述 Document、Retriever、Runnable、PromptTemplate 和 Output Parser。
- 面试追问：为什么不让框架对象直接渗透所有业务层？

## 第 4 周：Query Rewrite、混合检索和 Rerank

### 周一：Query Rewrite

- 为多轮对话增加查询改写步骤。
- 处理“它、这个方法、上面提到的内容”等指代。
- 比较原始问题和改写问题的 Recall。

### 周二：全文检索

- 在 PostgreSQL 中增加 `tsvector` 或等价全文检索。
- 测试函数名、错误码、专有名词和精确关键词。
- 记录全文召回与向量召回的差异。

### 周三：混合检索和 RRF

- 实现向量检索和全文检索两路召回。
- 使用 Reciprocal Rank Fusion 合并结果。
- 评估单路检索与混合检索的 Recall、MRR 和延迟。

### 周四：完全休息

### 周五：Rerank

- 对 Top 20 结果进行 Rerank，再取 Top 5 进入 Prompt。
- 控制 Rerank 超时、失败、成本和降级到原排序的行为。
- 解释双塔召回与交叉编码器排序。

### 周六：实验和前端展示

- 比较向量、混合、混合+Rerank 三组结果。
- 保存 chunk 配置、模型、指标、延迟和成本。
- 前端展示检索来源、排序变化和引用片段。

### 周日：阶段 2 总结

- 费曼复述：为什么召回要宽、排序要准？RRF 解决什么问题？
- 面试追问：Query Rewrite 什么时候会改坏原问题？Rerank 为什么不能替代第一阶段召回？
- 检查：能写出一条 LangChain 链，并用数据说明至少一个检索优化有效。

---

# 阶段 3：LangGraph 和 Agent

## 第 5 周：状态图、工具执行和边界控制

### 周一：State、Node、Edge

- 阅读 `agent/state.py` 和 `agent/graph.py`。
- 标注每个节点的输入、输出和状态更新。
- 对比 LangGraph 与手写 while 循环。
- 解释消息列表 reducer 和 `operator.add`。

### 周二：编译缓存和迭代守卫

- 将图编译改为进程级缓存。
- 最大迭代次数、超时和工具开关从配置读取。
- 处理达到上限时仍需工具、空回答和异常退出。

### 周三：工具注册与执行器

- 分离工具定义、动态注册、参数 schema 和真实 executor。
- 为动态工具增加真实执行器，或明确标记为不可执行。
- 增加未知工具、非法参数、结果截断和权限校验。

### 周四：完全休息

### 周五：工具失败、重试和 Mock

- 记录工具开始、成功、失败、耗时和结果摘要。
- 连续失败达到上限后停止调用并交还控制权。
- 禁止开发期 mock 结果伪装成真实外部工具结果。
- 测试计算器、搜索、知识库检索和错误工具。

### 周六：Agent 集成

- 明确普通问答、知识库问答和复杂工具任务的路由。
- 统一 `tool_call_id`、assistant tool call 和 tool message 格式。
- 测试直接回答、单工具、多工具、未知工具和最大迭代场景。

### 周日：周总结

- 画 Agent 状态图和一次工具调用消息时序。
- 面试追问：LangGraph 比 while 循环解决什么问题？工具失败时重试、降级还是终止？

## 第 6 周：Checkpoint、SSE 和 Agent 验收

### 周一：Checkpoint 和恢复

- 使用 MemorySaver 或持久化 Checkpointer。
- 模拟工具调用中断后恢复。
- 解释 session、thread 和 checkpoint 的关系。

### 周二：Agent 与 RAG 融合

- 明确知识库检索作为上下文还是工具的适用场景。
- 将知识库权限传入 Agent 工具执行层。
- 防止 Agent 越权检索其他用户的知识库。

### 周三：SSE 事件契约

- 统一 `session`、`rag`、`tool_call`、`tool_result`、`token`、`error`、`done` 事件。
- 定义事件顺序、断线、重复事件和最终保存行为。

### 周四：完全休息

### 周五：前端 Agent 验收界面

- 展示工具名称、参数、状态、结果摘要、耗时和迭代次数。
- 处理连接中断、错误、空回答和流结束。
- 展示 RAG 引用与 Agent 中间步骤。

### 周六：Agent 集成测试和代码 Review

- 测试 Checkpoint 恢复、工具超时、连续失败、越权、SSE 顺序和最终消息保存。
- 复查 Agent 图是否重复编译、工具是否真正可执行、边界是否清晰。

### 周日：阶段 3 总结

- 费曼复述 State、Node、Edge、Reducer、Checkpoint 和 Tool Calling。
- 面试追问：为什么需要 `tool_call_id`？如何防止 Agent 无限循环、重复调用和工具越权？
- 验收：有可复现的恢复演示，前端能观察完整 Agent 过程。

---

# 阶段 4：多轮上下文和安全

## 第 7 周：上下文、权限和安全边界

### 周一：Token 预算上下文

- 将最近 20 条消息改为 token 预算滑动窗口。
- 保留系统 Prompt、必要摘要和最近有效消息。
- 记录裁剪原因和估算 Token 数。

### 周二：会话摘要和并发

- 设计长会话摘要策略。
- 对比纯滑窗和滑窗+摘要的成本和回答效果。
- 修复会话更新时间，防止并发发送造成消息顺序错误。

### 周三：权限过滤

- 对知识库、文档、工具和会话统一校验用户权限。
- 将权限过滤下推到检索 SQL。
- 检查 Agent 工具是否复用同一权限规则。

### 周四：完全休息

### 周五：Prompt Injection

- 区分系统指令、用户输入和检索内容。
- 隔离文档中的“忽略之前指令”等恶意文本。
- 增加知识库注入、工具参数注入和越权测试。

### 周六：认证和限流

- 修复默认 JWT Secret、生产 Debug 和测试 Token 问题。
- 解释 access/refresh token、JWT 三段、token type 和 bcrypt。
- 解释固定窗口、滑动窗口和令牌桶。
- 增加登录失败锁定和统一错误响应。

### 周日：阶段 4 总结

- 费曼复述 token 预算、会话摘要、权限过滤和 Prompt Injection。
- 面试追问：为什么按 token 截断比按消息条数可靠？RAG 文档为什么不能当系统指令？
- 验收：长会话不爆上下文、用户不能越权、注入文本不能覆盖系统约束。

---

# 阶段 5：企业级可靠性和可观测性

## 第 8 周：异步任务、评测、部署和作品集

### 周一：文档异步任务

- 上传接口只保存文件和任务记录，快速返回任务 ID。
- 将解析、切块和 Embedding 移到 Worker。
- 增加进度查询、失败重试和 stuck 任务清扫。
- Embedding 分批执行，处理部分批次成功和失败恢复。

### 周二：幂等、去重和跨库一致性

- 对文件计算 SHA-256，处理同一知识库重复上传。
- 增加任务和消息幂等键。
- 修复 MySQL/PostgreSQL 跨库删除和孤儿 chunk。
- 解释 create_all 与 Alembic 迁移的区别。

### 周三：超时、重试、日志和指标

- LLM、Embedding、搜索工具统一 timeout。
- 对 429、5xx、连接错误使用指数退避和抖动。
- 增加 request ID、user ID、session ID、document ID 和 task ID。
- 记录模型、Token、延迟、状态、错误类型和费用。

### 周四：完全休息

### 周五：健康检查和评测闭环

- 拆分 `/health/live` 与 `/health/ready`，检查 MySQL、PostgreSQL 和 Redis。
- 完善 RAG 评测：Recall@K、MRR、nDCG、Faithfulness、引用准确率和覆盖率。
- 完善 Agent 评测：工具选择准确率、任务成功率、平均迭代、失败率。
- 保存模型、Embedding、chunk、策略、评测集和 baseline。

### 周六：Docker Compose、CI 和端到端验收

- 编写 MySQL、PostgreSQL/pgvector、Redis、API、Worker 和前端 Compose 服务。
- 使用 Alembic 完成迁移和初始化数据。
- CI 执行后端测试、集成测试、前端构建、类型检查、迁移检查和镜像构建。
- 完成端到端链路：上传→处理→检索→引用回答；普通聊天→SSE；Agent→工具→回答。

### 周日：阶段 5 和最终总结

- 费曼复述：异步任务、幂等、重试、日志、指标、健康检查、评测和部署。
- 面试追问：为什么 async API 不等于后台任务？哪些错误应该重试？如何定位线上慢请求？
- 进行最终项目答辩式 Review：由你讲解架构，我根据代码、指标和故障场景追问。
- 形成 README、架构图、评测报告、故障排查说明和个人面试讲稿。

---

## 5. 原计划的任务映射

原计划的 R1–R19 全部保留，只是压缩到 8 周：

| 原任务 | 安排 |
|---|---|
| R1 Embedding 链路 | 第 2 周周一 |
| R2 失败显式化 | 第 2 周周五 |
| R3 安全配置 | 第 7 周周六 |
| R4 prove_rag.py | 第 2 周周六 |
| R5 评测集 | 第 2 周周六、 第 8 周周五 |
| R6 LLM 超时重试 | 第 8 周周三 |
| R7 HNSW 索引 | 第 2 周周三 |
| R8 chunk 对比 | 第 2 周周二 |
| R9 双库一致性 | 第 8 周周二 |
| R10 Token 上下文 | 第 7 周周一、周二 |
| R11 阈值与引用 | 第 2 周周五 |
| R12 LangGraph 单例和 Checkpoint | 第 5、6 周 |
| R13 混合检索 | 第 4 周周二、周三 |
| R14 Rerank | 第 4 周周五 |
| R15 异步上传和批量 Embedding | 第 8 周周一 |
| R16 去重和 KB 过滤 | 第 2 周周三、 第 8 周周二 |
| R17 Agent 工具边界和失败处理 | 第 5、6 周 |
| R18 日志、request ID、健康检查 | 第 8 周周三、周五 |
| R19 限流和登录锁定 | 第 7 周周六 |

## 6. 每阶段固定总结模板

```text
阶段：
本阶段解决的问题：
我能用自己的话解释：
我能画出的图：
我亲自 Review 过的核心代码：
本阶段实验数据：
一个失败案例：
一个架构取舍：
一个高频面试问题及我的回答：
目前仍然不理解：
下一阶段需要复用的接口：
```

## 7. 最终验收标准

- 能解释并运行完整 RAG 链路，检索结果有引用且有 Recall/MRR 数据。
- 能说明 LangChain 的核心抽象和业务边界。
- 能绘制并修改 LangGraph 状态图，演示 Checkpoint 恢复。
- Agent 工具具备 schema、权限、超时、失败处理和迭代边界。
- 长会话具备 token 预算，知识库和工具具备权限过滤。
- 文档任务支持异步处理、进度、重试、恢复、去重和幂等。
- 关键请求可以通过 request ID、日志、指标和健康检查追踪。
- 评测集能分别评价检索、回答、引用和 Agent，优化有 baseline 对照。
- Docker Compose 可以启动完整环境，CI 可以执行测试、构建和迁移检查。
- 能结合当前项目回答架构、RAG、LangChain、LangGraph、Agent、评测和企业工程高频面试问题。

## 8. 明天的启动任务

从第 1 周周一开始：

1. 阅读项目目录、后端入口和前端入口。
2. 阅读普通聊天、文档上传和 Agent 三条调用链。
3. 画第一版模块关系图和请求时序图。
4. 运行现有测试并记录基线。
5. 我会逐段讲解关键代码，并用费曼和面试追问检查理解程度。
