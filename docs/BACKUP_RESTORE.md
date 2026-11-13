# 备份与恢复

> 目标：**数据丢了能回来**。演练过的结论才作数，没演练过的备份只是"以为有备份"。

## 现状

| 项 | 情况 |
|---|---|
| MySQL | 业务库 `ai_kb_platform`，6 张表 |
| PostgreSQL | 向量库 `ai_kb_vector`，1 张表（`document_chunks`，1024 维） |
| 备份脚本 | `backend/scripts/backup_all.py` |
| 恢复脚本 | `backend/scripts/restore_all.py`（支持 `--drill` 演练） |
| 存放位置 | `database-backups/<时间戳>/{mysql.sql, pg.sql, manifest.json}` |
| 保留策略 | 默认最近 7 份，超出自动删除 |
| 最近演练 | 2026-11-08：备份 1.39s / 恢复 1.97s / 7 张表行数全部一致 |

## 备份

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\backup_all.py            # 备份一次
..\.venv\Scripts\python.exe scripts\backup_all.py --list     # 看历史
..\.venv\Scripts\python.exe scripts\backup_all.py --keep 14  # 保留 14 份
```

细节：

- MySQL 用 `mysqldump --single-transaction`：拿一致性快照，**不锁表**，可在线备份
- 口令通过 `MYSQL_PWD` / `PGPASSWORD` 环境变量传，不写进命令行参数（避免进 shell 历史）
- PostgreSQL 优先用本机 `pg_dump`；没有就走 `docker exec <容器> pg_dump`
  （本项目 PG 跑在容器 `kb-postgres-published` 里，宿主机没装客户端工具）
- 每次备份同时写 `manifest.json`：文件大小、sha256、**每张表的行数**
  —— 这张表是后面"恢复是否完整"的唯一依据

## 恢复演练（默认，安全）

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\restore_all.py --drill
```

流程与本次实测输出：

```text
① 备份当前库 ...            database-backups/20261108-204535
② 建临时库（ai_kb_restore_test / ai_kb_vec_restore_test）
③ 恢复 MySQL ...
④ 恢复 PostgreSQL ...
⑤ 逐表比对数 ...

  表              源      恢复
  users               60      60
  knowledge_bases      6       6
  documents            4       4
  chat_sessions        2       2
  chat_messages        6       6
  agent_tools          3       3
  document_chunks      4       4

  备份：1.39s | 恢复：1.97s
  ✓ 演练通过：备份可完整恢复，行数与源库一致
⑥ 清理临时库 ...
```

为什么演练恢复到**另一个库名**而不是原地：原地恢复会把当前库直接覆盖，
而"这份备份到底能不能用"恰恰还没被验证。恢复到 `*_restore_test` 再对数，
风险为零，却能证明备份完整。

## 真恢复（会覆盖当前库）

```powershell
cd backend
# 恢复指定备份
..\.venv\Scripts\python.exe scripts\restore_all.py ^
    --backup database-backups/20261108-204535 --yes

# 不带 --backup 时用最近一份
..\.venv\Scripts\python.exe scripts\restore_all.py --yes
```

脚本会打印恢复后的行数，并与 manifest 里的行数比对，不一致会标出来。

## 恢复后的冒烟清单

```powershell
# 1. 服务能起、依赖都活着
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001
curl http://127.0.0.1:8001/health          # 期望 status=healthy，三项依赖 up

# 2. 迁移版本没丢
..\.venv\Scripts\python.exe -m alembic current                 # 期望 head
..\.venv\Scripts\python.exe -m alembic -n postgres current     # 期望 head

# 3. 关键数据在
#    登录 → 知识库列表能看到历史库 → 文档 status 正常 → 检索能返回切片

# 4. 检索索引还在（HNSW）
docker exec kb-postgres-published psql -U postgres -d ai_kb_vector ^
    -c "select indexname from pg_indexes where tablename='document_chunks'"
```

## 已知限制

| 限制 | 影响 | 后续 |
|---|---|---|
| 没有定时任务 | 目前靠手动/外部调度执行 | 生产用计划任务（Windows 任务计划 / cron）每天跑一次 |
| 备份与业务库同机 | 磁盘坏了备份一起没 | 需要异地/对象存储（`pg_dump` 直传 S3/OSS） |
| 未做加密 | 备份文件里有用户消息与文档正文 | 生产应加密存放（`gpg`/KMS） |
| 只做全量 | 库大了以后慢 | 数据量大时改 `mysqldump --where` 增量或 binlog 归档 |
