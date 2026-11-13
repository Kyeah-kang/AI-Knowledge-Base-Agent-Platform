"""
双库恢复脚本（D-3）。

两种用法：

1. **演练（默认推荐）** —— 不碰生产库，恢复到临时库里对数
   python scripts/restore_all.py --drill
   流程：备份 → 建临时库 → 恢复 → 逐表比行数 → 删临时库 → 汇报耗时

2. **真恢复** —— 把某个备份写回真实库（会覆盖！）
   python scripts/restore_all.py --backup database-backups/20261108-204435 --yes

为什么演练要恢复到"另一个库名"而不是原地：
  原地恢复会把当前库直接覆盖，而"备份能不能用"这件事本身就还没被验证。
  演练恢复到 `ai_kb_restore_test` / `ai_kb_vec_restore_test`，对数通过再删掉，
  风险为零，却能证明备份是完整的。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pymysql  # noqa: E402

from app.core.config import settings  # noqa: E402
from scripts.backup_all import (  # noqa: E402
    MYSQL_TABLES,
    PG_TABLES,
    _run,
    create_backup,
    latest_backup,
    mysql_row_counts,
    pg_row_counts,
)

MYSQL_DRILL_DB = "ai_kb_restore_test"
PG_DRILL_DB = "ai_kb_vec_restore_test"


# ─────────────────── 基础操作 ───────────────────


def _mysql_conn(database: str | None = None):
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=database,
    )


def create_mysql_db(name: str) -> None:
    conn = _mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
            cur.execute(
                f"CREATE DATABASE `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()


def drop_mysql_db(name: str) -> None:
    conn = _mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        conn.commit()
    finally:
        conn.close()


def _pg_exec(sql: str, database: str = "postgres") -> None:
    _run(
        [
            "docker",
            "exec",
            settings.POSTGRES_DOCKER_CONTAINER,
            "psql",
            "-U",
            settings.POSTGRES_USER,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]
    )


def create_pg_db(name: str) -> None:
    _pg_exec(f"DROP DATABASE IF EXISTS {name}")
    _pg_exec(f"CREATE DATABASE {name}")
    _pg_exec("CREATE EXTENSION IF NOT EXISTS vector", database=name)


def drop_pg_db(name: str) -> None:
    _pg_exec(f"DROP DATABASE IF EXISTS {name}")


# ─────────────────── 恢复 ───────────────────


def restore_mysql(dump: Path, *, source_db: str, target_db: str) -> None:
    """把 dump 恢复到 target_db（dump 里的库名会被替换成目标库名）"""
    sql = dump.read_text(encoding="utf-8")
    if source_db != target_db:
        # --databases 模式会写 CREATE DATABASE/USE，要换名才能恢复到临时库
        sql = sql.replace(f"`{source_db}`", f"`{target_db}`")
    proc = subprocess.run(
        [
            "mysql",
            f"--host={settings.MYSQL_HOST}",
            f"--port={settings.MYSQL_PORT}",
            f"--user={settings.MYSQL_USER}",
            "--default-character-set=utf8mb4",
        ],
        input=sql.encode("utf-8"),
        capture_output=True,
        env={**__import__("os").environ, "MYSQL_PWD": settings.MYSQL_PASSWORD},
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"MySQL 恢复失败：{proc.stderr.decode('utf-8', 'replace')[:600]}"
        )


def restore_postgres(dump: Path, *, target_db: str) -> None:
    """把 plain SQL dump 灌进目标库（先传进容器，再 psql -f）"""
    container = settings.POSTGRES_DOCKER_CONTAINER
    tmp = f"/tmp/restore_{int(time.time())}.sql"
    _run(["docker", "cp", str(dump), f"{container}:{tmp}"])
    try:
        _run(
            [
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                settings.POSTGRES_USER,
                "-d",
                target_db,
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                tmp,
            ]
        )
    finally:
        _run(["docker", "exec", container, "rm", "-f", tmp])


# ─────────────────── 演练 ───────────────────


def drill(*, keep_source: bool = False) -> int:
    print("① 备份当前库 ...")
    backup_dir = create_backup(keep=7, verbose=False)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"   {backup_dir}")

    source_counts = mysql_row_counts()
    source_pg_counts = pg_row_counts()

    print(f"② 建临时库（{MYSQL_DRILL_DB} / {PG_DRILL_DB}）...")
    create_mysql_db(MYSQL_DRILL_DB)
    create_pg_db(PG_DRILL_DB)

    started = time.perf_counter()
    try:
        print("③ 恢复 MySQL ...")
        restore_mysql(
            backup_dir / manifest["mysql"]["file"],
            source_db=settings.MYSQL_DATABASE,
            target_db=MYSQL_DRILL_DB,
        )
        print("④ 恢复 PostgreSQL ...")
        restore_postgres(
            backup_dir / manifest["postgres"]["file"], target_db=PG_DRILL_DB
        )
        restore_seconds = round(time.perf_counter() - started, 2)

        print("⑤ 逐表比对数 ...")
        conn = _mysql_conn(MYSQL_DRILL_DB)
        try:
            restored = {}
            with conn.cursor() as cur:
                for table in MYSQL_TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                    restored[table] = int(cur.fetchone()[0])
        finally:
            conn.close()
        restored_pg = pg_row_counts(PG_DRILL_DB)

        problems = []
        for table in MYSQL_TABLES:
            if restored.get(table) != source_counts.get(table):
                problems.append(
                    f"MySQL {table}: 源 {source_counts.get(table)} ≠ 恢复 {restored.get(table)}"
                )
        for table in PG_TABLES:
            if restored_pg.get(table) != source_pg_counts.get(table):
                problems.append(
                    f"PG {table}: 源 {source_pg_counts.get(table)} ≠ 恢复 {restored_pg.get(table)}"
                )

        print("\n  表              源      恢复")
        for table in MYSQL_TABLES:
            print(f"  {table:<16}{source_counts.get(table, 0):>6}{restored.get(table, 0):>8}")
        for table in PG_TABLES:
            print(f"  {table:<16}{source_pg_counts.get(table, 0):>6}{restored_pg.get(table, 0):>8}")

        print(f"\n  备份：{manifest['elapsed_seconds']}s | 恢复：{restore_seconds}s")
        if problems:
            print("  ✗ 恢复结果与源库不一致：")
            for item in problems:
                print(f"    - {item}")
            return 1
        print("  ✓ 演练通过：备份可完整恢复，行数与源库一致")
        return 0
    finally:
        if keep_source:
            print(f"  （保留临时库 {MYSQL_DRILL_DB} / {PG_DRILL_DB}，可人工检查）")
        else:
            print("⑥ 清理临时库 ...")
            drop_mysql_db(MYSQL_DRILL_DB)
            drop_pg_db(PG_DRILL_DB)


def restore_real(backup_dir: Path, *, confirmed: bool) -> int:
    """把备份写回真实库（危险操作，需要 --yes）"""
    if not confirmed:
        print("拒绝执行：真恢复会覆盖当前数据库，请确认后加 --yes")
        return 2

    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"→ 使用备份 {backup_dir}（{manifest['created_at']}）")

    print("→ 恢复 MySQL ...")
    restore_mysql(
        backup_dir / manifest["mysql"]["file"],
        source_db=manifest["mysql"]["database"],
        target_db=settings.MYSQL_DATABASE,
    )
    print("→ 恢复 PostgreSQL ...")
    restore_postgres(
        backup_dir / manifest["postgres"]["file"],
        target_db=settings.POSTGRES_DATABASE,
    )

    print("\n恢复后行数：")
    for table, count in mysql_row_counts().items():
        expected = manifest["mysql"]["row_counts"].get(table)
        flag = "" if expected == count else f"  ← 备份里是 {expected}"
        print(f"  {table:<16}{count:>6}{flag}")
    for table, count in pg_row_counts().items():
        expected = manifest["postgres"]["row_counts"].get(table)
        flag = "" if expected == count else f"  ← 备份里是 {expected}"
        print(f"  {table:<16}{count:>6}{flag}")
    print("\n✓ 恢复完成。请按 docs/BACKUP_RESTORE.md 的冒烟清单验证接口。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MySQL + PostgreSQL 恢复/演练")
    parser.add_argument("--drill", action="store_true", help="恢复到临时库演练（默认）")
    parser.add_argument("--backup", type=str, default="", help="指定备份目录")
    parser.add_argument("--yes", action="store_true", help="真恢复确认")
    parser.add_argument(
        "--keep-source", action="store_true", help="演练后保留临时库"
    )
    args = parser.parse_args()

    if args.backup:
        backup_dir = Path(args.backup)
        if not backup_dir.is_absolute():
            backup_dir = BASE_DIR.parent / args.backup
        if not (backup_dir / "manifest.json").exists():
            raise SystemExit(f"备份目录没有 manifest：{backup_dir}")
        return restore_real(backup_dir, confirmed=args.yes)

    if args.drill or not args.yes:
        return drill(keep_source=args.keep_source)

    return restore_real(latest_backup(), confirmed=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
