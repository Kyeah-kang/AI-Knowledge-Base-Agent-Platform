# 代码质量门禁

三个命令构成后端的"提交前体检"，CI 里跑同一套（D-2）：

```powershell
cd backend
..\.venv\Scripts\python.exe -m ruff check .          # 静态检查（秒级）
..\.venv\Scripts\python.exe -m mypy app              # 类型检查
..\.venv\Scripts\python.exe -m pytest --cov=app      # 测试 + 覆盖率门禁
```

## 当前基线（2026-11-09）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check .` | **0 问题**（88 条历史问题已修） |
| 类型检查 | `mypy app` | **0 问题**（71 个文件） |
| 测试 | `pytest` | **158 passed** |
| 覆盖率 | `pytest --cov=app` | **67.7%**（门禁 65%） |

## ruff 规则集：为什么只开这些

```toml
select = ["E4", "E7", "E9", "F", "I", "UP", "B"]
ignore = ["B008", "B904", "UP045", "UP046", "UP047"]
```

| 规则组 | 抓什么 | 为什么启用 |
|---|---|---|
| `E4/E7/E9` | 语法级错误（重复定义、缩进） | 这类问题直接导致运行时炸 |
| `F` | pyflakes：未使用变量/导入、未定义名 | **本次修了 20 个未用导入、1 个未定义名** |
| `I` | import 排序 | 减少合并冲突差异 |
| `UP` | 旧写法升级（`typing.Dict` → `dict`） | 与 Python 3.13 对齐 |
| `B` | bugbear：`zip` 不写 `strict`、循环变量晚绑定 | **本次抓到 2 类真陷阱**（见下） |

**被 ignore 的理由**：

- `B008`：FastAPI 的 `Depends()`/`Query()` 写在默认参数里是**官方写法**，不是 bug
- `B904`：`raise ... from e` 是风格问题，历史代码较多，不强制
- `UP045/046/047`：`Optional[X]` → `X | None`、PEP 695 泛型语法，纯风格且会大改代码

## 这一轮 ruff/mypy 抓到的真问题

| 问题 | 位置 | 后果 |
|---|---|---|
| **空知识库聊天会 500** | `chat_service._retrieve_rag_context` 里 `return ""`（应为 `return "", []`） | 选了没有文档的知识库提问 → 解包崩溃 |
| **`POST /agent/chat`（非流式）必崩** | 路由传了 `model_name=`，`AgentService.chat()` 没有这个参数 | 调用即 `TypeError` |
| `zip()` 未写 `strict` | embeddings / document_repo / 两个脚本 | 长度不一致时静默错位，把 A 的向量存给 B |
| lambda 捕获循环变量 | `llm_service._call_with_model_fallback` | 主备切换时"重试用的总是最后一个模型" |
| `_save_upload` 返回注解是 2 元组 | `document_service` | 注解与实现不符，调用方容易误解 |
| 未定义名 / 缺 import | 多处 | 运行时 `NameError` |

> 这些都不是"风格问题"。**类型检查的价值就在这里：它在你跑之前发现你的假设与代码不一致。**

## mypy：白名单式的债，不是免检

`mypy app` 初跑有 **45 条**。处理原则是"能修的真修，修不了的**按模块冻结并写清原因**"：

| 模块 | 冻结原因 |
|---|---|
| `app.agent.graph` | LangGraph 的 State 是普通 dict，与 TypedDict 声明天然不匹配 |
| `app.core.deps` / `app.database.session` | FastAPI 的 `yield` 依赖是 async generator，返回类型标注特殊 |
| `app.core.logging` | `logging.LogRecord` 是动态属性，挂 `request_id` 属正常扩展 |
| `app.rag.text_splitter` | langchain 新旧路径的降级导入无法静态推断 |
| `app.rag.embeddings` | 与 pgvector `Vector` 类型互操作 |
| `app.repositories.base` | 泛型 `T` 的 `id` 属性（`BaseRepository` 的约定） |

**规矩**：白名单只能减不能增。新增模块进白名单必须在 PR 里说明理由。

## 还没做的两件事

| 项 | 为什么没做 | 建议 |
|---|---|---|
| `ruff format`（格式化） | 会对 49 个文件产生纯格式 diff，淹没真实改动 | 单独一个 commit 落地，然后加入 CI |
| pre-commit 钩子 | 本地钩子依赖开发者安装，CI 才是硬约束 | D-2 之后可加 `.pre-commit-config.yaml`，但**以 CI 为准** |

## 装依赖提示（Windows 特有）

本机 pip 有全局 `target` 配置会把包装到 `D:\pip_global_libs`，venv 里看不到。装 lint 工具时用：

```powershell
$env:PIP_CONFIG_FILE = "$env:TEMP\pip_empty.ini"    # 空配置，忽略全局 target
..\.venv\Scripts\python.exe -m pip install ruff mypy
```
