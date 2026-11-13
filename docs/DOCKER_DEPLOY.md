# Docker 本地一键部署

> **定位**：让任何人 clone 下来后 **一条命令**起一套完整系统（含 MySQL/PG/Redis）。
> 这**不是生产部署**——没有域名、HTTPS、多副本、监控、滚动更新。生产还差什么见本文末尾。

## 架构

```text
浏览器 ──80──> frontend (nginx)  ──/api──>  backend (uvicorn:8000)  ──┬──> mysql:3306
                        │                                              ├──> postgres:5432 (pgvector)
                    静态文件 dist                                       └──> redis:6379
```

5 个服务全在 `ai-kb_kb-net` 自定义网络里，互相用**服务名**访问。

| 服务 | 镜像 | 对外端口 | 数据卷 |
|---|---|---|---|
| frontend | 本地构建（nginx:1.27-alpine） | **80** | — |
| backend | 本地构建（python:3.13-slim） | 无 | `ai-kb_uploads` → `/app/uploads`；`./backend/logs` → `/app/logs` |
| mysql | `mysql:8.2` | **无**（仅内部） | `ai-kb_mysql_data` |
| postgres | `pgvector/pgvector:pg16` | **无**（仅内部） | `ai-kb_pg_data` |
| redis | `redis:7-alpine` | **无**（仅内部） | `ai-kb_redis_data` |

**为什么数据库不发布端口**：① 避免和宿主机已有 MySQL/PG/Redis 抢 3306/5432/6379；② 数据库暴露到宿主机是攻击面。需要在宿主机直连时，临时加 `ports` 或用 `docker compose exec`。

## 快速开始

```powershell
# 1) 准备环境变量（含密钥，已被 .gitignore 排除）
Copy-Item .env.example .env     # 首次：按需修改口令与 LLM/Embedding key

# 2) 启动（会自动构建镜像 + 跑数据库迁移）
docker compose up -d

# 3) 看状态（等 mysql/postgres/redis/backend 都 healthy）
docker compose ps

# 4) 打开
start http://localhost
```

首次启动 backend 会自动执行两次迁移：

```
alembic upgrade head                # MySQL：建表 / 加列
alembic -n postgres upgrade head    # PostgreSQL：建切片表 + HNSW 索引 + vector 扩展
```

**验证接口层是否通**（不经浏览器）：

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1/api/v1/chat/models   # 期望 401（未带 token）
```

## 常用命令

```powershell
docker compose ps                      # 状态
docker compose logs -f backend         # 跟后端日志（JSON 格式，含 request_id）
docker compose logs -f frontend        # nginx 访问日志
docker compose restart backend         # 只重启后端
docker compose up -d --build backend   # 改代码后重建后端
docker compose exec backend sh         # 进容器
docker compose exec mysql mysql -uroot -p ai_kb_platform    # 进 MySQL
docker compose exec postgres psql -U kb -d ai_kb_vector     # 进 PG

docker compose stop                    # 停（保留容器与数据）
docker compose down                    # 删容器/网络（**保留数据卷**）
docker compose down -v                 # 连数据卷一起删（清库，慎用）
```

> `down -v` 只删 `ai-kb_*` 前缀的卷，**不会**影响其它项目的卷（本项目 compose 项目名为 `ai-kb`）。

## 环境变量

根目录 `.env`（Compose 自动读取；**已 gitignore**）：

| 变量 | 说明 |
|---|---|
| `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD` / `POSTGRES_PASSWORD` | 随机生成；生产必须改成独立强口令 |
| `MYSQL_DATABASE` / `POSTGRES_DATABASE` | `ai_kb_platform` / `ai_kb_vector` |
| `JWT_SECRET_KEY` | 长度 ≥32，非默认值（`DEBUG=false` 时校验，不满足拒绝启动） |
| `DEBUG` | `false` → `/docs`、`/redoc`、`/openapi.json` 全部 404（P2-2） |
| `LLM_API_KEY` / `EMBEDDING_API_KEY` | 必填；缺失时上传会失败、问答会报 502 |
| `MYSQL_IMAGE` / `PG_IMAGE` / `REDIS_IMAGE` | 可选。默认官方镜像名；网络受限时**在本机 `.env` 里**覆盖成镜像源，不影响仓库 |

## 踩过的坑（都是真实发生过的）

| 现象 | 根因 | 解决 |
|---|---|---|
| `docker build` 报 `dial tcp 127.0.0.1:7897` 或 `fetch oauth token: EOF` | Docker Desktop 走本地代理，代理没开/刚重启转发层未就绪/被污染 DNS 直连 | ① 确认代理在跑；② Docker Desktop → Proxies 用 `http://http.docker.internal:7897`；③ 改完设置先 `docker pull hello-world` 验链路，再 build |
| `docker run` 后立刻 `docker exec` 报 `No such container` | nginx **启动时**解析 `proxy_pass http://backend:8000` 的主机名，单容器没有 `backend` → `[emerg] host not found in upstream` → 退出；`--rm` 随即删除 | 单容器调试加 `--add-host backend:127.0.0.1`；compose 里靠 `depends_on: service_healthy` |
| 本机直连 `localhost` 返回 **502** | 客户端（httpx/requests）默认读系统代理，`localhost` 被走了代理 | 客户端设 `trust_env=False`，或把 `localhost,127.0.0.1` 加入 Clash 的 bypass 列表 |
| 上传大文件返回 **413** | nginx 默认 `client_max_body_size 1m` | `nginx.conf` 设 `client_max_body_size 50m`（与后端 `MAX_UPLOAD_SIZE_MB` 对齐） |
| SSE 回答"停顿后一大段刷出" | nginx 默认缓冲上游响应 | `proxy_buffering off; proxy_cache off;` |
| 刷新 `/chat` 页面 404 | SPA 路由没有 fallback | `try_files $uri $uri/ /index.html;` |
| backend 一直 restart | 迁移失败（连不上库/配置缺 key） | `docker compose logs backend --tail 60` 看 alembic 报错 |

## 和生产的差距（明确没做）

| 缺什么 | 说明 |
|---|---|
| 域名 + HTTPS | 现在只有 `http://localhost`；生产必须 TLS（token 不能明文传） |
| 多副本 + 负载均衡 | 单实例是单点；且 `backend` 启动时跑迁移，多副本会并发迁移（需拆成独立 job） |
| 镜像来源治理 | 生产应固定 digest（`mysql@sha256:...`）、走私有 registry、CI 里做漏洞扫描 |
| 观测 | 目前只有 `/health` 的进程内计数，重启即丢；缺少指标/日志采集与告警 |
| 备份异地 | 备份脚本产出在 `database-backups/`，与数据库同机、未加密 |
| 回滚 | 没有镜像 tag 策略与上一个版本的快速回退 |

## 在 CI 里怎么用（可选）

```yaml
# GitHub Actions 片段示意
- run: docker compose -f docker-compose.yml config --quiet     # 配置校验
- run: docker compose build                                    # 构建
- run: docker compose up -d && timeout 120 sh -c 'until curl -fsS http://localhost/; do sleep 3; done'
```

