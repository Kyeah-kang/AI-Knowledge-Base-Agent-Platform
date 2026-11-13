# 前端 — AI 知识库 Agent 平台

> 根文档：[README](../README.md) · [架构](../docs/ARCHITECTURE.md) · [企业级差距复核](../docs/ENTERPRISE_GAP_REVIEW.md) · [首轮审计](../docs/GAP_ANALYSIS.md)

React + TypeScript + Vite 实现的管理后台与对话界面：登录/注册、仪表盘、普通聊天（SSE）、Agent 对话（工具可视化）、知识库/文档管理、个人中心、管理员页面。

---

## 技术栈

| 类别 | 技术 | 版本 |
|---|---|---|
| 框架 | React | 19 |
| 语言 | TypeScript | 6.0 |
| 构建 | Vite | 8.1 |
| UI | Ant Design + @ant-design/icons | 6.4 / 6.2 |
| 路由 | React Router | 7.18 |
| 状态 | Zustand | 5.0 |
| HTTP | Axios | 1.18 |
| Lint | Oxlint | 1.69 |

---

## 快速开始

```powershell
cd frontend
npm install

# 开发期用 3000 端口，匹配后端默认 CORS（5173 需后端加白名单）
npm run dev -- --port 3000
```

打开 <http://localhost:3000>。

`.env`：

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

> 后端必须先启动，且从 `backend/` 目录启动（`.env` 相对 CWD）。

### 可用脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | Vite 开发服务器 |
| `npm run build` | `tsc -b && vite build` |
| `npm run preview` | 预览构建产物 |
| `npm run lint` | Oxlint |

---

## 目录结构

```
src/
├── main.tsx                 # React 入口
├── App.tsx                  # 路由表 + ConfigProvider(zhCN)
├── api/                     # Axios API 封装
│   ├── client.ts            # 实例、Bearer、401 refresh
│   ├── auth.ts / user.ts
│   ├── knowledgeBase.ts / document.ts
│   ├── chat.ts / agent.ts
├── components/
│   ├── Layout.tsx           # 侧边栏 + Header + Outlet
│   ├── ProtectedRoute.tsx   # 登录守卫
│   └── AdminRoute.tsx       # 管理员守卫
├── hooks/
│   └── useSSE.ts            # fetch + ReadableStream 解析 SSE
├── pages/
│   ├── Login.tsx / Register.tsx
│   ├── Dashboard.tsx
│   ├── Chat.tsx             # 普通聊天（会话 + SSE）
│   ├── AgentChat.tsx        # Agent 对话（工具卡片）
│   ├── KnowledgeBaseList.tsx
│   ├── DocumentList.tsx     # 上传/预览切片
│   ├── Profile.tsx
│   └── admin/
│       ├── UserManage.tsx
│       └── ToolManage.tsx
├── store/
│   ├── authStore.ts         # token/user 恢复
│   ├── chatStore.ts         # 会话/消息/流式
│   └── appStore.ts
└── utils/
    ├── constants.ts         # 应用名、分页、文件类型
    └── token.ts             # localStorage 读写
```

---

## 路由

| 路径 | 页面 | 权限 |
|---|---|---|
| `/login`、`/register` | 登录/注册 | 公开 |
| `/dashboard` | 仪表盘 | 登录 |
| `/chat` | 智能对话（SSE） | 登录 |
| `/agent` | Agent 对话 | 登录 |
| `/knowledge-bases` | 知识库管理 | 登录 |
| `/knowledge-bases/:kbId/documents` | 文档管理 | 登录 |
| `/profile` | 个人中心 | 登录 |
| `/admin/users`、`/admin/tools` | 管理后台 | 管理员 |

---

## 数据流

```
页面组件
  ├─► api/*.ts (Axios) ──► client.ts（Bearer + 401 refresh）──► FastAPI
  ├─► useSSE（fetch + ReadableStream）──► FastAPI StreamingResponse
  └─► store（Zustand）──► localStorage（access/refresh/user）
```

### SSE 事件

普通聊天：

```
data: {"token":"你","done":false}
data: {"token":"好","done":false}
data: {"token":"","done":true}
```

Agent：

```
event: session     data: {"session_id":1}
event: rag         data: {"context_length":500}
event: tool_call   data: {"name":"calculator","arguments":"..."}
event: tool_result data: {"name":"calculator","result":"..."}
event: token       data: {"token":"..."}
event: done        data: {"iterations":2,"tool_calls_count":1}
event: error       data: {"message":"..."}
```

`useSSE` 按行解析 `event:`/`data:`；当前不支持多行 `data:` 与断线重连，W4 改进。

---

## 与后端的约定

- 统一响应：`{ code, message, data }`；列表为 `{ items, total, page, page_size }`。
- 鉴权：`Authorization: Bearer <access_token>`；401 时用 refresh 换新 access。
- 流式接口是 GET + query（当前实现），消息内容会进 URL；W4 改 POST/SSE。
- 上传：`multipart/form-data`，字段名 `file`。

---

## 已知问题（详见根仓库差距审计）

| 问题 | 现象 | 计划 |
|---|---|---|
| AgentChat 闭包 | 流式结束后答案变空、工具卡片丢失 | W4 用 ref 保存最新值 |
| 无会话连续性 | 每次 Agent 提问新建会话 | W4 传 `session_id`/记录 `event: session` |
| CORS | 5173 被拦，只能用 3000 | W4 后端加白名单 |
| Dashboard 文档数 | 恒为 0 | W4 请求真实统计 |
| UserManage email | 后端无 email 字段，显示空 | W4 去掉或补字段 |
| 无 Markdown/引用 | 回答是纯文本 | W4 加渲染与引用 |
| 无停止/重试 | 流式不可中断 | W4/D23 |
| 类型 `any` 多 | 维护性差 | W6 逐步收紧 |

---

## 构建与部署

```powershell
npm run build
# 产物在 dist/；W7 由 Nginx 托管，/api 反代到后端
```

注意：

- 生产用 `VITE_API_BASE_URL=/api/v1`（同源反代），不要写死 `localhost`。
- SSE 经 Nginx 需关闭缓冲（`proxy_buffering off`）。
- token 目前存 localStorage；W4 评估 httpOnly cookie 或内存存储。

---

## 面试可讲点

- 为什么用 Zustand 而不是 Redux？（轻量、样板少；大型项目需规范）
- Axios 拦截器怎么实现自动刷新？并发 401 怎么只刷新一次？（当前未做并发去重，可改进）
- SSE 与 WebSocket 的选择？`fetch` 流式与 `EventSource` 的区别？（`EventSource` 不能带 Authorization 头）
- React 闭包陷阱：为什么 `onDone` 读到旧 state？怎么用 `useRef` 解决？
- 受保护路由/管理员路由怎么实现？前端隐藏不等于安全，后端仍要校验。

---

## 说明

本项目为个人工程实践，前端优先保证“能演示 + 能讲清”，UI 细节与可访问性在 W4/W6 逐步完善。任何“已完成”以根 README 状态表和 `docs/GAP_ANALYSIS.md` 为准。
