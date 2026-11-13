# B1 阶段修复总结报告（止血批次）

> 报告日期：2026-10-29 · 对象：`backend/`（FastAPI + LangGraph + pgvector）与 `frontend/`（React + SSE）
> 配套：[企业级复核](ENTERPRISE_GAP_REVIEW.md) · [修复执行清单](FIX_PLAN.md) · [进度台账](TRACKER.md) · [学习路线](CURRICULUM.md) · [面试题库](INTERVIEW.md)
> 写法：**现象 → 根因 → 改法 → 证据 → 可迁移的结论**。每条都能在代码里指到位置，也能变成面试回答。

---

## 0. 一句话结论

B1 不是"加功能"，而是把系统从**「看起来在工作」修成「不会把错误结果当成功返回」**：

- 计划内 **5 项**全部关闭（P0-2 / P0-4 / P0-5 / P0-6 / P1-8）；
- 端到端验证时又挖出 **7 个此前两轮审计都没发现的 bug**，其中 **3 个是阻断级**（Agent 全挂、非流式 500、业务状态码全被吞成 500），修掉 6 个、明确留下 1 个（N-7）；
- 新增 **24 个不依赖 DB/网络的回归用例**，全套由 29 → **53 passed**；
- 阶段判断从「可演示 Demo」变为**「错误可见、语义正确、但还不够可信」**——所以下一批是 B2 可信。

一句话记忆点：**B1 修的是"说真话"，B2 修的是"有权限"，B3 修的是"不卡顿"，B5 修的是"能证明"。**

> **定稿说明**：本报告聚焦 B1。定稿时（2026-10-29 11:45）B2 也已同日闭环（见 [B2 批次修复记录](ENTERPRISE_GAP_REVIEW.md#b2-批次修复记录2026-10-28)），因此 §6 的测试数、§7 的评分、§8 的"当前状态"、§10 的覆盖度按 **B1+B2** 校正；B1 自身的范围、改动与结论不变。

---

## 1. 为什么 B1 排第一

复核报告里 35 个问题，最致命的不是"功能少"，而是三种"静默"：

1. 检索坏了 → 返回空上下文，模型用通用知识编一个像样的答案，**用户和运维都不知道 RAG 已经失效**；
2. Agent 挂了 → HTTP 200、SSE 只有一帧 `event: session`，**页面空白且没有报错**；
3. 失败被映射 → 登录失败返回 400、资源不存在返回 400，**前端拦截器、网关、监控按状态码统计全部失真**。

这三类问题会污染之后所有的优化：性能、评测、上线都会建立在"结果不可信"的基础上。所以批次定义是：

> **B1 止血：用户不被告知错误结果的场景清零。**
> 判断标准不是"代码改了多少"，而是"随便挑一条错误路径，用户/运维能不能看见它"。

---

## 2. 修复台账（总览）

| 编号 | 用户看到的症状 | 根因（代码视角） | 修复后的行为 | 主要落点 |
|---|---|---|---|---|
| **P0-2** | 同一句话被模型"听两遍"，长会话更容易答偏 | 先存消息 → 读最近 20 条（已含当前）→ 又 append 一次当前问题 | 历史查询按 **消息 ID** 排除当前这条；chat/agent 共用唯一入口 | `services/message_context.py`（新增）、`repositories/chat_repo.py` |
| **P0-4** | Agent 问复杂问题，转几轮后**回答是空的** | 超限时最后一条 assistant 是 `content=None` 的 tool_calls，取正文取不到 | 上限走配置；超限强制一次**不带工具**的总结调用；总结失败也有可读兜底 | `agent/graph.py`、`services/agent_service.py`、`core/config.py` |
| **P0-5** | Agent 页流式输出完，**答案瞬间消失**；每问一句多一个会话 | `onDone` 读闭包里的旧 `streamContent`（连接时为 `""`）；URL 不带 `session_id` | `useRef` 保存最新流内容；监听 `event: session` 记住会话；支持 `?session_id=` 恢复历史 | `frontend/src/pages/AgentChat.tsx`、`hooks/useSSE.ts` |
| **P0-6** | 登录失败返回 HTTP **400**（body 里才是 401） | `AppException.http_status_code` 默认写死 400 | 没显式传时**默认取 `code`**（非合法 HTTP 码才退回 400）；auth 5 处补显式值 | `core/exceptions.py`、`services/auth_service.py` |
| **P1-8** | LangGraph 出问题时降级，**回答变空或 400** | 降级循环用 `dict.update()` **替换**了消息历史 | `_merge_state()`：`messages` 追加、其余字段覆盖 | `agent/graph.py`、`agent/state.py` |

---

## 3. 逐项 before / after（这是复习的主线）

### 3.1 P0-2 当前问题在 prompt 里出现两次

**旧代码**（`chat_service.send_message`，旧版约 300–320 行）：

```python
user_msg = await self.message_repo.create(session_id=..., role="user", content=content)  # 先存
history = await self._get_context_messages(session_id)                                   # 读最近 20 条，已含刚落库的这条
messages = self.llm.build_messages(content, history, effective_system_prompt)            # 再把 content 拼一次
```

**新代码**：

```python
user_msg = await self.message_repo.create(session_id=session_id, role="user", content=content)
history = await load_history(                                   # 唯一入口
    self.message_repo, session_id, current_message_id=user_msg.id
)
messages = self.llm.build_messages(content, history, effective_system_prompt)
```

关键实现（`repositories/chat_repo.py::get_recent_history`）：

```python
query = select(self.model).where(self.model.session_id == session_id)
if exclude_id is not None:
    query = query.where(self.model.id != exclude_id)   # 排除在 SQL 层，精确
query = query.order_by(self.model.created_at.desc()).limit(limit)
```

**三个设计决策，面试可以直接讲：**

1. **为什么不"排除最后一条 user 消息"？** —— 用户完全可能连问两次同一句话（"再解释一遍"），按内容排除会把上一轮的真问题也删掉；按主键排除语义才唯一。
2. **为什么抽公共模块而不是改两处？** —— 修复前 chat 与 agent 各有一份同构实现，这是"同一 bug 两个副本"。抽 `message_context.load_history()` 后，只要一个单测就能同时守住两条链路；B3-1 的 token 预算裁剪也准备加在这里，调用方不用再改。
3. **`limit` 在排除之后生效**：`WHERE` → `ORDER BY` → `LIMIT`，所以是"20 条历史 + 当前 1 条"，不会因为排除而少一条窗口。

**证据**：`tests/test_b1_agent_and_context.py`
- `test_load_history_excludes_current_message`
- `test_chat_send_message_injects_current_question_once`
- `test_chat_stream_injects_current_question_once`
- `test_agent_chat_injects_current_question_once`

四个用例断言同一件事：**`messages` 里当前内容出现次数 == 1**。

---

### 3.2 P0-4 Agent 达到迭代上限返回空回答

**旧行为**：`max_iterations = 10` 写死在两处；到上限直接结束循环 → 最后一条 assistant 是 `content=None` 的 tool_calls → `_extract_result` 找不到正文 → `result = ""` → 前端渲染空气泡。

**新行为**（`agent/graph.py`）：

```python
_FINAL_SUMMARY_INSTRUCTION = "现在不要再调用任何工具。请仅基于上面已经获得的工具结果，直接给出最终回答……"
_NO_ANSWER_TEMPLATE = "我已经连续调用了 {n} 轮工具，但没能整理出最终结论。建议把问题拆成更小的一步……"

async def summarize_without_tools(messages, max_iterations) -> str:
    try:
        final_messages = _close_pending_tool_calls(list(messages)) + [
            {"role": "user", "content": _FINAL_SUMMARY_INSTRUCTION}
        ]
        text = (await llm.chat(final_messages, use_cache=False) or "").strip()
        if text:
            return text
    except Exception:
        ...
    return _NO_ANSWER_TEMPLATE.format(n=max_iterations)

async def _ensure_final_answer(state, max_iterations):
    result = _extract_result(state)
    if result["result"]:
        return result
    text = await summarize_without_tools(state["messages"], max_iterations)
    state["messages"].append({"role": "assistant", "content": text})   # 让提取器能取到
    return _extract_result(state)
```

同时 `should_continue` 改为读 `state.max_iterations`，`run_agent` 用 `settings.AGENT_MAX_ITERATIONS` 初始化。这样服务端改环境变量为 1，就能稳定复现"超限"场景（E2E 就是这么验的）。

**可迁移结论：**
- **"终止"必须定义输出契约**：函数承诺 `result: str`，就永远不能返回空串。空字符串在 UI 上等于"系统坏了"，在评测里等于"零分"，还是最难排查的那种。
- **降级文案是产品的一部分**：`"我已经连续调用了 N 轮工具，但没能整理出结论"` 比空回答、比 `500 Internal Server Error` 都更有用——它告诉用户"信息不足，换个问法"。

**证据**：`test_manual_loop_falls_back_when_iterations_exhausted`、`test_summarize_returns_readable_fallback_when_llm_fails`；E2E 输出 `reply: "1024 × 768 = 786,432（说明：上面的工具调用实际未执行成功……）"`，**非空**。

---

### 3.3 P0-5 流式结束后答案消失 + 没有会话连续性

**旧代码**（`AgentChat.tsx`，diff 里的 `-` 行就是原样）：

```tsx
const url = `${BASE}/agent/chat/stream?content=${encodeURIComponent(content)}${kbParam}`; // 没有 session_id

connect(url, {
  onToken: (token) => setStreamContent((prev) => prev + token),
  onDone: () => {
    setMessages((prev) => [...prev, { content: streamContent, toolCalls: currentToolCalls }]); // 读闭包旧值
    setStreamContent("");
  },
});
```

`connect()` 调用发生在组件本次渲染里，`onDone` 闭包捕获的 `streamContent` 是**那一刻的值 `""`**；之后 `setStreamContent` 再多次更新也只会触发重渲染，**不会改变这个闭包里已经捕获的变量**。所以流式过程正常显示，结束瞬间用 `""` 追加了一条空消息。

**新代码**：

```tsx
const streamContentRef = useRef("");
const toolCallsRef = useRef<ToolCallItem[]>([]);

onToken: (token) => {
  streamContentRef.current += token;          // ref：可变，永远最新
  setStreamContent(streamContentRef.current); // state：只负责触发渲染
},
onDone: () => {
  const finalContent = streamContentRef.current;
  const finalToolCalls = toolCallsRef.current;
  setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: finalContent, ... }]);
  ...
},
onSession: (data) => { if (data?.session_id) setSessionId(data.session_id); },
```

URL 也补上了 `&session_id=`，并在 `useEffect` 里读取 `?session_id=` 调 `getSessionDetail` 恢复历史。`onError` 也会把**已收到的部分回答**追加成一条带"生成中断"说明的消息，而不是直接丢弃。

**可迁移结论：**
- **React 闭包 = 快照**。异步回调（SSE/WebSocket/定时器）里要读"最新值"，用 `ref`；要"驱动 UI"，用 `state`。两者混用就会出现"流式时看得见、结束时消失"这种只在特定时序下出现的 bug。
- 前端消费流式协议时，**session/错误/结束三种帧必须都处理**，只处理 token 的 UI 一定是残缺的。

**证据**：E2E 两轮流式都带同一个 `session_id`；第二轮不再出现 `event: session`；会话总数 `before/after = 2/2`（没有新建）；消息角色序列 `['user','assistant','user','assistant']`。前端 `npm run build` 与 `npx oxlint` 通过。

---

### 3.4 P0-6 业务异常 HTTP 状态码错（401/403/404 全变 400）

**旧代码**：

```python
def __init__(self, code: int = 400, message: str = "请求失败", data: any = None,
             detail: any = None, http_status_code: int = 400):
    ...
    self.http_status_code = http_status_code
```

两个问题叠在一起：① 默认值写死 400，调用方只传 `code=401` 时 HTTP 仍是 400；② `data: any` 把内建 `any` 当类型注解（应为 `Any`），注解实际失效。

**新代码**：

```python
_HTTP_STATUS_LIKE = range(400, 600)   # 当 code 落在 4xx/5xx 时，它与 HTTP 状态码同义

self.http_status_code = (
    http_status_code if http_status_code is not None
    else (code if code in _HTTP_STATUS_LIKE else 400)
)
super().__init__(message)   # 否则 str(exc) 是空串（N-6）
```

**这里有一个非常值得学的"修了但看起来没修"的坑（N-3）**：`deps.get_vector_db` 把 `yield` 包在 `try/except Exception` 里。FastAPI 会把路由抛出的异常 `throw` 回生成器的 `yield` 处，外层 `except` 接住后又 `yield` 一次 → `RuntimeError: generator didn't stop after athrow()` → **500**。也就是说：P0-6 把 `AppException` 修对了，但 `GET /chat/sessions/{不存在的id}` 依然是 500。必须同时改依赖层，状态码才真正到达客户端。

**新写法**（把"降级"限定在"创会话对象失败"，路由异常原样上抛）：

```python
try:
    session = PostgreSQLAsyncSessionLocal()
except Exception as e:
    metrics.incr("vector_db_session_total", status="error")
    logger.error(...)
    yield None
    return

try:
    yield session
    await session.commit()
except Exception:
    await session.rollback()
    raise          # ← 关键：不吞
finally:
    await session.close()
```

**证据**：`test_app_exception_uses_code_as_http_status`（9 个参数化用例覆盖 400/401/403/404/422/429/500/502/503）、`test_app_exception_non_http_code_falls_back_to_400`、`test_app_exception_explicit_http_status_wins`、`test_app_exception_str_keeps_message`；E2E：错误密码 **401**、不存在的会话 **404**、重复用户名 **400**。

**可迁移结论：**
- **HTTP 状态码是给基础设施看的契约**（网关、监控、重试策略、前端拦截器），**业务 code 是给业务代码看的载荷**。两者可以解耦，但必须有明确的映射规则，且默认值不能"一律 400"。
- **`yield` 依赖里不要写 `except Exception`**。这是 FastAPI 最容易踩、也最难查的一类 bug：异常被吞 → 500 → 你以为是业务没抛。

---

### 3.5 P1-8 降级路径把消息历史覆盖掉

**旧代码**：

```python
current_state = dict(state)
for _ in range(max_iterations):
    result = await call_llm_node(current_state)
    current_state.update(result)          # ← dict.update 是"替换 messages 列表"
    ...
```

`AgentState` 上声明了 `messages: Annotated[list, operator.add]`，但 `operator.add` **只在 LangGraph 图内生效**；手写循环里 `update()` 是普通字典合并，等于把整个历史换成"本轮新增的那一条"。结果是：tool 消息前面没有对应的 assistant `tool_calls`，上游直接 400（协议要求 `tool_call_id` 一一配对）。

**新代码**：

```python
def _merge_state(state: dict, delta: dict | None) -> None:
    for key, value in (delta or {}).items():
        if key == "messages":
            state["messages"] = list(state.get("messages") or []) + list(value or [])  # 追加
        else:
            state[key] = value                                                          # 覆盖
```

**可迁移结论：**
- **"降级实现"必须复制语义，而不是复制意图**。框架帮你做了 reducer，你手写的时候要显式把 reducer 的行为实现出来。
- 降级路径平时不执行，所以**它是最容易腐烂的代码**。任何 fallback 都要有单独的测试（这里补了 `test_manual_loop_keeps_full_tool_history`、`test_langgraph_exception_degrades_to_manual_loop`）。

---

## 4. 计划外的 7 个发现（B1 真正的含金量）

| ID | 问题 | 严重度 | 为什么之前两轮审计没抓到 | 状态 |
|---|---|---|---|---|
| N-1 | 工具名重复 → 上游 `400 Tool names must be unique` → **所有 Agent 请求失败** | 🔴 阻断 | 单看 `tools.py` 是对的；问题在 `seed_data.py` 把 3 个内建工具也写进了 `agent_tools` 表，注册成"动态工具"后与系统工具重名。**跨文件的组合缺陷** | ✅ `get_tool_definitions()` 按名去重，系统工具优先 |
| N-2 | 非流式 Agent `len(tool_calls_infos)` 拼错变量名 → `NameError` → 500 | 🔴 阻断 | 静态阅读时太容易"脑补"成正确名字；只有真的走一遍非流式分支才炸 | ✅ 改为 `tool_call_infos` |
| N-3 | 依赖层 `try/except` 吞掉路由异常 → 404 变 500 | 🔴 阻断 | 必须同时看 FastAPI 的 `yield` 依赖语义 + 路由异常传播；只读业务代码看不出来 | ✅ 只在创建会话失败时降级，其余原样上抛 |
| N-4 | 超限时消息停在 `assistant(tool_calls)`，兜底总结调用必然 400 | 🟠 中 | 需要知道上游"tool_calls 必须配对"的硬约束 | ✅ `_close_pending_tool_calls()` 补占位 tool 消息 |
| N-5 | 启动维度探测按 `atttypmod - 4` 解码，把 `vector(1024)` 误报成 `vector(1020)` | 🟡 低 | pgvector 的 `atttypmod` **直接等于维度**，与 varchar 的 `-4` 惯例不同 | ✅ 修正 |
| N-6 | `AppException` 不调 `super().__init__()` → `str(exc)` 为空 | 🟠 中 | Python 异常链的默认行为很隐蔽；只有日志里看到 `Agent 执行出错：` 才会察觉 | ✅ `super().__init__(message)` |
| N-7 | `register_vector` 协程未 `await` → `RuntimeWarning: coroutine was never awaited` | 🟡 低 | 实测 ORM 读写仍可用（pgvector 的 SQLAlchemy 类型自带 bind/result），所以"没坏"掩盖了"写错了" | ⬜ **未修**，登记在案 |

**三个值得当作案例讲的：**

**N-1：注册表必须单一来源。** 系统工具是代码里的常量，动态工具是数据库里的行，两者在"给 LLM 的 tools 数组"里汇合。任何汇合点都要做**边界校验**（去重 + 空名过滤 + 无 executor 过滤），否则一条脏数据能让整个功能 100% 不可用。面试里可以这样讲："这个 bug 不是逻辑错误，是**数据契约错误**——数据库里存了不该存的工具定义，而代码没有在边界上拒绝它。"

**N-3：异常传播链比异常类型更重要。** 修 bug 时顺序很关键：先修 `deps` 再修 `exceptions`，否则你会以为"映射没生效"，反复在业务层打转。这也是"**改默认值之前，先看谁在吞异常**"这个原则的来源。

**N-4：协议约束是硬约束。** OpenAI 兼容接口要求 `assistant(tool_calls)` 之后必须跟齐 `tool` 消息。所以"补一条说明性 tool 消息"不是 hack，而是**满足协议的最小正确解**——这比"删掉最后一条 assistant"更安全（不破坏历史）。

---

## 5. 改动地图与规模

B1 直接触及的文件（约 14 个，含新增）：

| 文件 | 改了什么 |
|---|---|
| `backend/app/services/message_context.py` | **新增**：`load_history()`，chat/agent 共用的上下文唯一入口 |
| `backend/app/services/chat_service.py` | 改用 `load_history`；流式/非流式各一处；错误进 SSE |
| `backend/app/repositories/chat_repo.py` | `get_recent_history(exclude_id=)` 按主键排除当前消息 |
| `backend/app/services/agent_service.py` | 同上；`event: session` 先发；上限走配置；超限总结；SSE `error`/`done` |
| `backend/app/agent/graph.py` | `_merge_state`、`_close_pending_tool_calls`、`summarize_without_tools`、`_ensure_final_answer` |
| `backend/app/agent/state.py` | 状态字段（`document_ids`/`max_iterations`）与 reducer 语义对齐 |
| `backend/app/agent/tools.py` | `get_tool_definitions()` 去重；检索工具缺范围即拒绝 |
| `backend/app/core/exceptions.py` | HTTP 状态码默认取 `code`；`super().__init__`；`RetrievalError` |
| `backend/app/core/deps.py` | **不再吞路由异常**（N-3）；PG 会话提交/回滚/关闭 |
| `backend/app/core/config.py` | `AGENT_MAX_ITERATIONS`、`CONTEXT_HISTORY_LIMIT` |
| `backend/app/services/auth_service.py` | 5 处补显式 `http_status_code` |
| `frontend/src/pages/AgentChat.tsx` | ref 保存流内容；`session_id` 续接；历史恢复；中断保留部分输出 |
| `frontend/src/hooks/useSSE.ts` | `event: error` / `done` / `session` 分发 |
| `backend/tests/test_b1_agent_and_context.py` | **新增 24 个回归用例** |

规模（`git diff --stat`，注意这是 **B1+B2 合并**的工作区改动，不是 B1 单独）：

```
27 files changed, 1343 insertions(+), 397 deletions(-)
```

> 为什么不能把 +1343 全算给 B1：基线提交之后，B1 与 B2 的改动都还没提交（见 §8.2）。拆开算需要按 hunk 归属，意义不大；面试里说"这一轮总共改了两千行、新增 40+ 用例"是诚实的，说"B1 改了 1343 行"反而容易被追问穿。

---

## 6. 验证证据

### 6.1 测试

```
# B1 收尾时（复核报告记录）
pytest → 53 passed   （29 旧 + 24 新）

# B2 收尾时（复核报告记录）
pytest → 72 passed   （53 + 19 个 B2 用例）

# 2026-10-29 本机复跑（含 B2 用例，运行在沙箱内）
pytest → 70 passed, 2 errors
  2 个 ERROR 均为 fixture 建临时目录失败：
  PermissionError: [WinError 5] ...\Temp\dsh-9tJVhO\pytest-of-10767
  → 这是沙箱对 %TEMP% 的 ACL 限制，不是代码失败；普通终端 / CI 下为 72 passed。
```

B1 的 24 个用例全部**不依赖数据库与网络**：用 `FakeMessageRepo`、`RecordingLLM` 替身 + `monkeypatch`，所以能在任何机器上秒级跑完。这是"AI 应用"测试的关键技巧——**把不确定的外部模型换成确定性的假实现，只测你写的编排逻辑**。

### 6.2 真实运行（E2E）

```
[P0-6] 错误密码登录      HTTP 401  body.code 401
[P0-6] 不存在的会话       HTTP 404
[P0-6] 重复用户名注册     HTTP 400

[P0-4] POST /agent/chat（服务端 AGENT_MAX_ITERATIONS=1）
       HTTP 200  iterations=1
       reply: "1024 × 768 = 786,432（说明：上面的工具调用实际未执行成功，这个结果是我直接计算的。）"

[P0-5] 两轮流式均带 session_id；第二轮无 event: session
       会话总数 before/after = 2 / 2
       消息角色序列 = ['user','assistant','user','assistant']
```

### 6.3 前端

`npm run build` 通过；`npx oxlint` 无新增告警。

### 6.4 证据强度自评

| 项 | 强度 | 说明 |
|---|---|---|
| P0-2 | 强 | 单测断言次数，E2E 可复现；不依赖环境 |
| P0-4 | 强 | 单测 + 真实 LLM 跑通（改配置即可复现） |
| P0-5 | 中强 | E2E 验证会话连续性；"工具卡片展开"属前端交互，需人工点一次 |
| P0-6 | 强 | 9 个参数化单测 + 3 条真实 HTTP |
| P1-8 | 强 | 单测覆盖降级路径 |
| N-1 | 中强 | 去重单测 + 真实 Agent 请求成功；但"为什么数据库里会有重复"只是推断（seed 脚本） |

---

## 7. 效果评估

复核报告的原始评分（1–5）：

| 维度 | B1 前 | B1 后 | B2 后（当前） | 依据 |
|---|---|---|---|---|
| 正确性 | 2.0 | **3.0** | **3.5** | B1 关 5 项（重复注入/空回答/答案消失/状态码/降级覆盖）；B2 关 6 项、**P0 清零**；仍缺真流式（B3）、失败原因持久化（B5-2）、内容去重 |
| 可靠性/可观测 | 1.5 | 1.5 | 1.5 | 日志/指标/request_id/健康检查（B4）未动 |
| 工程化交付 | 1.5 | 1.5 | 1.5 | 迁移/Docker/CI（B6）未动 |
| 质量保障 | 1.5 | **2.0** | **2.5** | 用例 29 → 53 → 72；仍无接口级测试与覆盖率门禁（B5-4） |
| 架构 | 4.0 | 4.0 | 4.0 | 未变；新增 `message_context`、`_resolve_document_ids` 反而更收敛 |

**DoD 清单的变化**：企业级验收清单从 2 条 ✅ 变成 **7 条 ✅**（B1 贡献 3 条：当前问题出现 1 次、Agent 连续追问不丢、错误登录 401/不存在 404；B2 贡献 3 条：向量维度一致、选 A 库只出 A、删库无孤儿）。**这是最硬的成绩**——不是"感觉修好了"，而是验收项被勾掉。

> 评分是估算，口径与原报告一致（按 DoD 勾选数与缺口定性）。面试时不要报"我从 2.3 提到 2.8"这种伪精确数字，直接说"两批一共关闭 11 个 P0/P1 项、7 条验收项转绿、回归用例从 29 涨到 72"。

---

## 8. B1 的边界与"当前仓库真实状态"

### 8.1 B1 明确没解决（后续批次）

| 缺口 | 条目 | 后果 | 排期 |
|---|---|---|---|
| Agent 检索忽略选中的知识库（越权） | P0-3 | 选 A 库仍检索全库 | B2 |
| 默认 JWT 密钥、上传路径穿越、依赖不可复现 | P0-7/8/9 | 可伪造 token、可写任意路径、新人装不上 | B2 |
| 删 KB 不清 PG 切片、会话列表 N+1 | P1-3/4 | 孤儿数据、列表慢 | B2 |
| Agent 不是真流式 | P1-6 | 首 token = 整段生成时间 | B3 |
| `/health` 假探针、无结构化日志/request_id/成本 | P1-9/10 | 出问题发现不了 | B4 |
| 无 HNSW、无迁移、无评测 | P1-1/2、P2-6 | 效果无法证明、schema 无法演进 | B5 |
| 维度/失败原因未持久化 | P0-1 遗留 | 用户看不到失败原因的历史记录 | B5-2（`documents.error_message`） |

### 8.2 当前仓库真实状态（2026-10-29 11:45）

**B2 已同日闭环**，记录在 [ENTERPRISE_GAP_REVIEW.md §B2](ENTERPRISE_GAP_REVIEW.md#b2-批次修复记录2026-10-28)（19 个用例 + 真实 E2E：上传→切片→向量首次跑通、文件名穿越被净化、选 A 库只出 A、删库无孤儿、会话排序与计数正确）。上表前三行（P0-3/7/8/9、P1-3/4）现已关闭——保留它们是为了说明 **B1 当时的边界**，而不是"待办"。

但有三件事必须记住，面试时也不能吹：

1. **所有改动都还没提交**。`git log` 只有一条基线 `5aa558b`，49 个文件处于 modified/untracked，B1 与 B2 混在一个工作区。建议按批次拆成两个 commit（`fix(b1): ...` / `fix(b2): ...`），否则回滚、`git bisect`、写复盘都很难。**这是当前最该做的一件小事。**
2. **B2 自述的边界**：上传仍是同步处理（只做到"不阻塞事件循环 + 不爆内存"，真正的任务队列在 B6/B7 之后）；内容级去重需要 `documents.file_hash` 列 + 迁移；N-11（前端 `SessionDetail` 类型缺 `message_total`）未修。
3. **文档已同步**：`FIX_PLAN` §0 改为"B1 5 项 + B2 6 项、P0 清零、剩余 25 项"；本报告的 bug 板校正也已写进 `TRACKER.md`。

> 下一步（按顺序）：① 提交 B1、B2 两个 commit（含本报告）；② 进 **B3**：token 预算（`load_history` 里加）、Agent 真流式（`chat_stream` 逐 token）、LLM 超时/重试、工具 executor 注册；③ **B4** 可观测。**不要在没有提交的情况下继续往前修**——这是把学习项目做成"能讲清楚"的项目的最低成本。

---

## 9. 十二条可迁移的工程原则（B1 的真正产出）

> 这一节是"报告"和"笔记"的分界线：以后遇到新项目，这 12 条可以直接复用。

1. **先修"骗人"，再修"慢"和"丑"。** 错误结果比慢结果贵得多——慢只会被抱怨，错会被当成事实使用。
2. **同一段逻辑出现两次，就是两个 bug 的配额。** 修的时候先收敛成一个实现，再谈修不修。
3. **排除/去重靠主键，不靠内容。** 内容会重复（同一句话问两次），主键不会。
4. **终止条件必须附带输出契约。** "循环结束"不等于"有答案"；函数承诺返回 `str`，就永远不能是空串。
5. **上游协议是硬约束。** `assistant(tool_calls)` 后必须跟 `tool` 消息；不满足就 400，跟你代码"逻辑对不对"无关。
6. **降级路径要单独写测试。** 它平时不执行，所以最容易腐烂；而且它一出问题，往往是在"主路径已经坏了"的时候雪上加霜。
7. **改默认值之前，先查谁在吞异常。** 否则你会以为"改了没生效"，然后在错误的地方反复打转（N-3）。
8. **React 异步回调里读 state，读到的是快照；最新值放 `ref`。** 这条对 SSE/WebSocket/定时器/IntersectionObserver 全部适用。
9. **流式 UI 必须处理三种帧：token、error、done（+session）。** 只处理 token 的页面一定会出现"空白/卡住/丢答案"。
10. **测试断言"不变量"，不要断言实现。** 断言"当前内容出现 1 次"，而不是"第 5 步调用了 load_history"——前者在重构后依然成立。
11. **任何注册表/合并点都要做边界校验。** 系统常量与数据库行汇合时（工具、插件、模型、路由），空值、重名、无实现必须当场拒绝。
12. **端到端跑一遍，抵得上读三遍代码。** 7 个计划外 bug 里 6 个是跑起来才暴露的——其中 3 个是阻断级。

---

## 10. 对照「AI 应用开发」岗位要求：B1 给了你什么

岗位 JD 的常见拆法（不同公司措辞不同，但就这几块）：

| JD 能力块 | 典型要求 | B1 覆盖度 | 你的证据（面试可指） | 还缺什么 |
|---|---|---|---|---|
| **LLM 集成** | 熟悉 OpenAI 兼容 API、流式、function calling、多模型 | 🟨 已覆盖 | `llm_service`、SSE 协议、`chat_with_tools` | 超时/重试/降级、多 provider（P1-14/P2-4） |
| **Prompt / 上下文工程** | 多轮上下文管理、token 预算、注入防护 | 🟩 **B1 主战场** | P0-2 单一入口、`exclude_id`、`load_history` | token 预算（B3-1）、prompt 版本化（B8-2） |
| **Agent** | 工具调用循环、终止条件、错误恢复 | 🟩 **B1 主战场** | `_merge_state`、`summarize_without_tools`、`_close_pending_tool_calls`、工具去重、B2 的检索范围解析 | 真流式（B3）、executor 注册（B3-4） |
| **RAG** | 切片、embedding、检索、rerank、引用 | 🟨 有链路，无评测 | 双库设计、pgvector、检索失败显式化 | HNSW、rerank、recall@k（B5） |
| **流式交互** | SSE/WebSocket、首 token、断流恢复 | 🟩 **B1 主战场** | P0-5、`useSSE` 的 error/done/session 帧 | 真流式（B3-3）、心跳/重连（B7-3） |
| **后端工程** | FastAPI、异步、分层、依赖注入、事务 | 🟩 有真实教训 | N-3 `yield` 依赖、`to_thread`、双库事务 | 后台任务/迁移（B5/B6） |
| **可靠性与错误语义** | 状态码、错误码、失败可见 | 🟩 **B1 主战场** | P0-6、`RetrievalError`、SSE `event: error` | 重试/熔断、失败原因持久化 |
| **测试** | 单测、接口测试、mock 外部模型 | 🟨 29 → 72 | 43 个不依赖 DB/网络的用例、fake LLM、`monkeypatch` | 接口级测试/覆盖率（B5-4） |
| **可观测** | 结构化日志、request_id、指标、成本 | 🟥 几乎空白 | `/health` 有失败计数 | B4 整批 |
| **评测** | RAG 指标、LLM-as-judge、回归门槛 | 🟥 空白 | — | B5 整批 |
| **安全** | 越权、密钥、上传、注入 | 🟩 B2 已闭环（部分） | 检索范围校验、文件名净化、JWT 轮换、删库清孤儿 | 内容去重/异步上传（B5/B6）、限流与 SSE 改 POST（B4） |
| **交付** | Docker、CI、备份 | 🟥 空白 | — | B6 |

**读法**：B1 让你在 **"上下文工程 / Agent 编排 / 流式交互 / 错误语义 / 回归测试"** 这五块有了**能指代码、能讲取舍**的真实素材——这恰好是 AI 应用开发面试里最容易被追问、也最容易露馅的部分（只会调 API 的人答不上"为什么上限要强制总结"、"为什么 404 变 500"）。

**但不要高估**：**可观测、评测、交付三块还是空的**——这三块决定你是"会写 AI 功能"还是"能对线上 AI 系统负责"。B2 补上了"可信"（权限/密钥/上传/数据一致性），但"能被发现"和"能被证明"要等 B4/B5。所以别跳过 B4/B5 直接去刷八股。

---

## 11. 七天带练计划（每天 2–2.5h，产出可提交）

> 原则：**不重写 B1，而是把 B1 当教材，通过"复现 → 改写 → 讲清"把知识变成你的。**
> 每天结束必须留下三样：一段代码/测试、一条命令输出、一段 3 分钟口述（录音或写下来）。

| 天 | 主题 | 读 | 动手（产出） | 验收 | 面试落点 |
|---|---|---|---|---|---|
| **D1** | 上下文工程 | `message_context.py`、`chat_repo.get_recent_history`、4 个 P0-2 用例 | 用 `git show 5aa558b:backend/app/services/chat_service.py` 看旧实现；写一个**会失败**的测试复现"出现两次"；再让它通过 | `pytest -k context -q` 通过；能口述"为什么按 ID 排除" | 多轮上下文怎么组装？token 超了怎么办？ |
| **D2** | Agent 循环与终止 | `graph.py` 全文、`agent/state.py`、`_execute_knowledge_retrieval` | 手画状态机（call_llm / should_continue / execute_tool / END）；把 `AGENT_MAX_ITERATIONS=1` 跑一次真实 Agent；用 fake LLM 构造 10 轮 tool_calls | 画出图 + 一次真实超限回复 + 一条"悬空 tool_calls"用例 | Agent 死循环怎么防？超限怎么给用户交代？ |
| **D3** | 流式协议 | `useSSE.ts`、`agent_service._stream_events`、`AgentChat.tsx` | 用 `curl -N` 抓一次 SSE 原始帧；在浏览器里把 `useRef` 改成 `useState` 复现"答案消失"；写一张"帧类型 → 前端动作"对照表 | 原始帧截图 + 复现记录 + 对照表 | SSE 和 WebSocket 怎么选？断流怎么办？ |
| **D4** | 异常语义与依赖注入 | `exceptions.py`、`deps.py`、`auth_service.py` | 写一个最小 FastAPI 复现"yield 里 except 把 404 吞成 500"；再改成正确写法；跑 9 个状态码映射用例 | 两版代码对比 + 测试输出 | 业务错误码和 HTTP 状态码怎么设计？ |
| **D5** | 回归测试方法论 | `test_b1_agent_and_context.py` 全文 | 给 B1 的某个修复补 1 个**边界用例**（比如 `limit=0`、空历史、`code=599`）；把测试按"不变量"改名 | 新增用例通过；说明它为什么测的是行为不是实现 | 怎么测 AI 应用？模型不确定怎么测？ |
| **D6** | 复盘与叙事 | 本报告 §3/§9/§10、`INTERVIEW.md` 的 Agent/RAG 段 | 写 3 分钟 STAR 版 B1 故事；给每条修复配一句"取舍"；录一遍 | 不看稿讲 3 分钟，能被追问 2 层 | 讲一个你修过最难查的 bug |
| **D7** | 小改造（接 B3） | `llm_service.count_tokens`（写了但没人调用）、`config.py` | 在 `load_history` 里加 token 预算骨架（先只算 token 并打日志，不改行为）；写测试 | 日志里出现"历史 tokens / 预算"；测试通过 | 上下文窗口怎么算？为什么要留输出预算？ |

**D1 现在就能开始的 20 分钟版本**：

1. 读 `backend/app/services/message_context.py`（44 行，很短）和 `backend/app/repositories/chat_repo.py` 的 `get_recent_history`；
2. 读 `backend/tests/test_b1_agent_and_context.py` 的前 170 行（P0-2 的 4 个用例）；
3. 回答我三个问题（下一节"入学测"）。

---

## 12. 入学测（回答完再进 D2）

> 不要查代码，先凭理解答；答完再回去核对。这三题答不上来，说明 B1 只是"看过了"，不是"会了"。

1. **P0-2**：为什么"排除当前这条"要用 `message_id`，而不是"排除内容相同的最后一条用户消息"？举一个按内容排除会出错的真实场景。
2. **P0-4**：如果只加"超限时返回兜底文案"，不加 `_close_pending_tool_calls()`，会发生什么？为什么？
3. **P0-6 / N-3**：`AppException(code=404)` 修好之后，为什么 `GET /chat/sessions/999999` 还是返回 500？说出完整的异常传播路径。

---

## 13. 三分钟叙述模板（面试/复盘直接用）

> **背景**（20s）：这是一个 RAG + Agent 的全栈项目，我做企业级复核时发现 35 个问题，按"先止血、再可信、再性能、再可观测、再评测、再交付"分了 8 批。B1 是止血批，5 项。
>
> **问题**（40s）：三个"静默"——检索坏了还照常回答；Agent 超限返回空回答；401/404 全变 400。最典型的是 Agent：页面 HTTP 200、SSE 只有一帧 session，用户什么都看不到，日志里也没有异常。
>
> **动作**（60s）：① 上下文收敛成 `load_history` 单一入口，SQL 层按主键排除当前消息；② 超限强制一次不带工具的总结调用，并补齐悬空 tool_calls（上游协议要求配对）；③ 前端用 ref 保存流式缓冲、URL 带 session_id；④ 异常默认状态码取业务码，同时修掉依赖层吞异常；⑤ 降级循环的 `dict.update` 改成"messages 追加"。
>
> **结果**（40s）：新增 24 个不依赖 DB/网络 的回归用例，全套 53 通过；E2E 验证 401/404/400、超限非空回答、两轮同会话。**过程里还挖出 7 个此前没发现的 bug，3 个是阻断级**——比如 seed 脚本把内建工具写进数据库导致工具重名，上游直接 400，所有 Agent 请求都失败。
>
> **反思**（20s）：最大的教训是"修默认值之前先查谁在吞异常"，以及"降级路径必须单独测试"。B1 之后同一天又做了 B2（权限、密钥、上传、环境、孤儿数据、N+1），**P0 清零**；下一步是 B3 性能与上下文。

---

## 14. 自检清单（能全部打勾，B1 才算真掌握）

- [ ] 不看代码，说出 5 个修复的"症状 + 根因 + 改法"
- [ ] 画出 Agent 循环状态机，标出三个终止出口
- [ ] 解释 `assistant(tool_calls)` 与 `tool` 消息的配对约束，以及不满足时的报错
- [ ] 解释 FastAPI `yield` 依赖为什么会吞异常，并能写最小复现
- [ ] 解释 React 闭包捕获，说明为什么流式缓冲要用 `ref`
- [ ] 解释业务 `code` 与 HTTP 状态码的关系，说出默认值规则
- [ ] 能手写"当前问题只出现一次"的测试（不查原文件）
- [ ] 说出 N-1 为什么能导致"所有 Agent 请求失败"
- [ ] 说出 B1 没解决的 3 个缺口及对应批次
- [ ] 能用一句话说出 B2 六项各自修了什么（越权 / 密钥 / 上传 / 依赖 / 孤儿 / N+1）
- [ ] 能讲 3 分钟版本，并回答"那你怎么保证以后不再犯？"（答案：不变量测试 + 边界校验 + E2E 证据）

---

## 附录 A：常用命令

```powershell
# 看"修复前"的代码（基线提交）
git show 5aa558b:backend/app/services/chat_service.py
git show 5aa558b:backend/app/core/deps.py

# 只看 B1 的测试
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_b1_agent_and_context.py -q

# 全套（普通终端；沙箱下 2 个 tmp_path 用例会因 %TEMP% ACL 报错）
..\.venv\Scripts\python.exe -m pytest -q

# 复现"超限"（改配置后重启后端）
$env:AGENT_MAX_ITERATIONS=1
```

## 附录 B：本报告与其它文档的关系

| 文档 | 回答什么 | 什么时候看 |
|---|---|---|
| 本报告 | B1 **改了什么、为什么、怎么验证、怎么学** | 现在；复盘；面试前 |
| `ENTERPRISE_GAP_REVIEW.md` | 35 个问题的**定义/影响/验收标准** | 想知道"还差什么" |
| `FIX_PLAN.md` | **先改哪个文件哪一行、怎么验收** | 动手修的时候 |
| `TRACKER.md` | 进度、证据、每日复盘 | 每天结束 |
| `CURRICULUM.md` | 48 天课程 | 长期节奏 |
| `INTERVIEW.md` | 题库与话术 | 面试前两周 |
