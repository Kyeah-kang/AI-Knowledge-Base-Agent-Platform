"""
双库备份脚本（D-3）。

为什么需要它：
  仓库里只有一份 `ai_kb_vector_20261022.dump`，MySQL **一条备份都没有**，
  也没有恢复脚本 —— 数据丢了，前面所有修复都白做。

做法：
  - MySQL：`mysqldump --single-transaction`（事务一致快照，不锁表）
  - PostgreSQL：优先用本机 `pg_dump`；没有就用 `docker exec <容器> pg_dump`
    （本项目的 PG 跑在容器里，宿主机没装客户端工具）
  - 产出：`database-backups/<时间戳>/{mysql.sql, pg.sql, manifest.json}`
  - manifest 里记行数 + sha256，恢复后可以逐表对数
  - 默认保留最近 7 份（`--keep` 可调）

用法：
    python scripts/backup_all.py                # 备份一次
    python scripts/backup_all.py --keep 14      # 保留 14 份
    python scripts/backup_all.py --list         # 看历史备份
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings  # noqa: E402

BACKUP_ROOT = BASE_DIR.parent / "database-backups"

# 备份时记录行数的表（恢复后逐表对数，能立刻发现"备份不完整"）
MYSQL_TABLES = [
    "users",
    "knowledge_bases",
    "documents",
    "chat_sessions",
    "chat_messages",
    "agent_tools",
]
PG_TABLES = ["document_chunks"]


def _run(cmd: list[str], *, env: dict | None = None, binary: bool = False):
    """执行外部命令；失败时把 stderr 抛出来，不要静默"""
    result = subprocess.run(
        cmd,
        capture_output=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace")[:800]
        raise RuntimeError(f"命令失败（{cmd[0]}）：{stderr}")
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mysql_row_counts() -> dict[str, int]:
    import pymysql

    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
    )
    counts = {}
    try:
        with conn.cursor() as cur:
            for table in MYSQL_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int(cur.fetchone()[0])
    finally:
        conn.close()
    return counts


def pg_row_counts(database: str | None = None, *, via_docker: bool = True) -> dict[str, int]:
    """查 PG 行数。同样支持"宿主机有 psql"和"只有容器"两种情况"""
    db = database or settings.POSTGRES_DATABASE
    sql = " UNION ALL ".join(
        f"SELECT '{table}', COUNT(*) FROM {table}" for table in PG_TABLES
    )
    if via_docker:
        out = _run(
            [
                "docker",
                "exec",
                settings.POSTGRES_DOCKER_CONTAINER,
                "psql",
                "-U",
                settings.POSTGRES_USER,
                "-d",
                db,
                "-t",
                "-A",
                "-F",
                ",",
                "-c",
                sql,
            ]
        )
    else:
        out = _run(
            [
                "psql",
                f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{db}",
                "-t",
                "-A",
                "-F",
                ",",
                "-c",
                sql,
            ]
        )
    counts = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        name, value = line.split(",", 1)
        counts[name.strip()] = int(value)
    return counts


def backup_mysql(target_dir: Path) -> Path:
    out_path = target_dir / "mysql.sql"
    sql = _run(
        [
            "mysqldump",
            f"--host={settings.MYSQL_HOST}",
            f"--port={settings.MYSQL_PORT}",
            f"--user={settings.MYSQL_USER}",
            "--single-transaction",  # 一致性快照，不锁表
            "--routines",
            "--triggers",
            "--default-character-set=utf8mb4",
            "--databases",
            settings.MYSQL_DATABASE,
        ],
        env={"MYSQL_PWD": settings.MYSQL_PASSWORD},  # 口令不走命令行，避免进 ps 历史
    )
    out_path.write_text(sql, encoding="utf-8")
    return out_path


def backup_postgres(target_dir: Path) -> Path:
    """优先本机 pg_dump；没有就走容器（项目实际部署方式）"""
    out_path = target_dir / "pg.sql"
    if shutil.which("pg_dump"):
        sql = _run(
            [
                "pg_dump",
                f"--host={settings.POSTGRES_HOST}",
                f"--port={settings.POSTGRES_PORT}",
                f"--username={settings.POSTGRES_USER}",
                "--no-owner",
                "--clean",
                # 必须配 --if-exists：单独 --clean 生成的是不带 IF EXISTS 的 DROP，
                # 恢复到空库/新库时会因"index does not exist"直接失败（实测踩过）
                "--if-exists",
                settings.POSTGRES_DATABASE,
            ],
            env={"PGPASSWORD": settings.POSTGRES_PASSWORD},
        )
        out_path.write_text(sql, encoding="utf-8")
        return out_path

    # 容器里 dump：直接在容器内写文件再拷出来，避免二进制/编码问题
    container = settings.POSTGRES_DOCKER_CONTAINER
    tmp = f"/tmp/{settings.POSTGRES_DATABASE}.sql"
    _run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            settings.POSTGRES_USER,
            "--no-owner",
            "--clean",
            "--if-exists",
            "-f",
            tmp,
            settings.POSTGRES_DATABASE,
        ]
    )
    _run(["docker", "cp", f"{container}:{tmp}", str(out_path)])
    _run(["docker", "exec", container, "rm", "-f", tmp])
    return out_path


def create_backup(*, keep: int = 7, verbose: bool = True) -> Path:
    """做一次完整备份，返回备份目录"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target_dir = BACKUP_ROOT / stamp
    target_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    if verbose:
        print(f"→ 备份 MySQL（{settings.MYSQL_DATABASE}）...")
    mysql_path = backup_mysql(target_dir)

    if verbose:
        print(f"→ 备份 PostgreSQL（{settings.POSTGRES_DATABASE}）...")
    pg_path = backup_postgres(target_dir)

    manifest = {
        "created_at": stamp,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "mysql": {
            "database": settings.MYSQL_DATABASE,
            "file": mysql_path.name,
            "bytes": mysql_path.stat().st_size,
            "sha256": _sha256(mysql_path),
            "row_counts": mysql_row_counts(),
        },
        "postgres": {
            "database": settings.POSTGRES_DATABASE,
            "file": pg_path.name,
            "bytes": pg_path.stat().st_size,
            "sha256": _sha256(pg_path),
            "row_counts": pg_row_counts(),
        },
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _apply_retention(keep)
    if verbose:
        print(f"✓ 备份完成：{target_dir}")
        print(f"  MySQL {mysql_path.stat().st_size / 1024:.1f} KB | "
              f"PG {pg_path.stat().st_size / 1024:.1f} KB | "
              f"{manifest['elapsed_seconds']}s")
    return target_dir


def _apply_retention(keep: int) -> None:
    """只保留最近 keep 份，避免磁盘被备份吃满"""
    backups = sorted(
        (p for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True
    )
    for stale in backups[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def list_backups() -> None:
    if not BACKUP_ROOT.exists():
        print("还没有任何备份")
        return
    for path in sorted((p for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True):
        manifest_path = path / "manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(
                f"{path.name}  mysql={data['mysql']['bytes'] / 1024:.0f}KB "
                f"pg={data['postgres']['bytes'] / 1024:.0f}KB "
                f"{data['elapsed_seconds']}s"
            )
        else:
            print(f"{path.name}  (无 manifest，可能是手工放的)")


def latest_backup() -> Path:
    if not BACKUP_ROOT.exists():
        raise SystemExit("没有可用的备份目录")
    dirs = sorted((p for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True)
    for path in dirs:
        if (path / "manifest.json").exists():
            return path
    raise SystemExit("没有带 manifest 的备份")


def main() -> int:
    parser = argparse.ArgumentParser(description="MySQL + PostgreSQL 备份")
    parser.add_argument("--keep", type=int, default=7, help="保留最近多少份")
    parser.add_argument("--list", action="store_true", help="列出现有备份")
    args = parser.parse_args()

    if args.list:
        list_backups()
        return 0

    create_backup(keep=args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
