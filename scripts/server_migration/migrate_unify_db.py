# -*- coding: utf-8 -*-
"""统一数据库迁移:把三个独立 SQLite 合并进 data/stockrank.db。

合并对象(表名已核对零冲突,故原样搬表、不改任何 SQL):
  - quant(原 TrendZen) trading.db   : 21 张表(扫描信号/回测/自选/账户/鉴权等)
  - mp_game.db                        : 8 张表(小程序答题/弹幕墙)
  - mp_vpay.db                        : 2 张表(虚拟支付订单/权益)

在【服务器】上、两个后端都停机的维护窗口运行:
    python3 scripts/server_migration/migrate_unify_db.py            # 自动发现路径
    python3 scripts/server_migration/migrate_unify_db.py --trading-db /explicit/path

特性:
  - 幂等:可安全重跑(建表 IF NOT EXISTS + INSERT OR IGNORE,主键去重)
  - 先备份:所有源库(含 -wal/-shm)拷贝到 <target_dir>/migration_backup_<时间戳>/
  - 后校验:逐表比对源/目标行数,目标行数只许多不许少,少了非零退出
  - account.json 不在本脚本处理:quant 的 account.py 首次启动发现空表时自行导入
  - 兼容服务器旧版 Python(类型标注用 typing 写法,不用 PEP604 的 str|None)
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 各源库的候选路径(按序探测,取第一个存在的)。相对路径基于本仓库根。
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDIDATES = {
    "trading": [
        os.path.join(REPO_ROOT, "quant", "data", "trading.db"),          # 新布局
        os.path.join(REPO_ROOT, "data", "trading.db"),                    # 服务器可能仍在旧布局
        os.path.join(os.path.dirname(REPO_ROOT), "TrendZen", "data", "trading.db"),
    ],
    "mp_game": [
        os.path.join(REPO_ROOT, "data", "mp_game.db"),
        os.path.join(REPO_ROOT, "backend", "data", "mp_game.db"),        # config 重构前的旧位置
    ],
    "mp_vpay": [
        os.path.join(REPO_ROOT, "data", "mp_vpay.db"),
        os.path.join(REPO_ROOT, "backend", "data", "mp_vpay.db"),
    ],
}


def discover(key: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override if os.path.exists(override) else None
    for cand in CANDIDATES[key]:
        if os.path.exists(cand):
            return cand
    return None


def user_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return sorted(r[0] for r in rows)


def table_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def clone_schema(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    row = dst.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row:
        return  # 目标已有同名表(重跑幂等)
    create_sql = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    dst.execute(create_sql)


def clone_indexes(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    for (name, sql) in src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall():
        if dst.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            continue
        try:
            dst.execute(sql)
        except sqlite3.OperationalError:
            pass  # 表达式索引引用缺列等极端情况不阻塞迁移


def copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> Tuple[int, int]:
    before = table_rows(dst, table) if dst.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() else 0
    src_rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
    cols = [d[1] for d in src.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if not src_rows:
        return 0, before
    placeholders = ",".join("?" for _ in cols)
    quoted = ",".join(f'"{c}"' for c in cols)
    dst.executemany(
        f'INSERT OR IGNORE INTO "{table}" ({quoted}) VALUES ({placeholders})', src_rows
    )
    after = table_rows(dst, table)
    return after - before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.path.join(REPO_ROOT, "data", "stockrank.db"))
    parser.add_argument("--trading-db")
    parser.add_argument("--mp-game-db")
    parser.add_argument("--mp-vpay-db")
    parser.add_argument("--skip-backup", action="store_true")
    args = parser.parse_args()

    sources = {}
    for key, arg in (("trading", args.trading_db), ("mp_game", args.mp_game_db), ("mp_vpay", args.mp_vpay_db)):
        path = discover(key, arg)
        if path:
            sources[key] = path
    if not sources:
        print("[迁移] 未找到任何源库,无需迁移(可能是全新部署)。")
        return 0

    print(f"[迁移] 目标库: {args.target}")
    os.makedirs(os.path.dirname(args.target), exist_ok=True)

    # ---- 备份(含 wal/shm,保证源库状态完整可回退) ----
    if not args.skip_backup:
        backup_dir = os.path.join(
            os.path.dirname(args.target), f"migration_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        os.makedirs(backup_dir, exist_ok=True)
        for key, path in sources.items():
            for suffix in ("", "-wal", "-shm"):
                f = path + suffix
                if os.path.exists(f):
                    shutil.copy2(f, os.path.join(backup_dir, os.path.basename(f)))
            print(f"[备份] {key}: {path} -> {backup_dir}")

    # ---- 逐源合并 ----
    target = sqlite3.connect(args.target, timeout=30)
    target.execute("PRAGMA journal_mode=WAL")
    target.execute("PRAGMA synchronous=NORMAL")
    target.execute("PRAGMA busy_timeout=30000")

    report, failed = [], []
    seen_tables: Dict[str, str] = {}
    for key, src_path in sources.items():
        src = sqlite3.connect(src_path, timeout=30)
        try:
            tables = user_tables(src)
            for table in tables:
                if table in seen_tables:
                    print(f"[跳过] 表 {table} 已由 {seen_tables[table]} 迁移,跳过 {key} 同名表")
                    continue
                clone_schema(src, target, table)
                inserted, total = copy_table(src, target, table)
                clone_indexes(src, target, table)
                seen_tables[table] = key
                source_count = table_rows(src, table)
                report.append((key, table, source_count, total, inserted))
                if total < source_count:
                    failed.append((key, table, source_count, total))
        finally:
            src.close()

    target.commit()
    target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    target.close()

    # ---- 校验报告 ----
    print("\n===== 迁移报告 =====")
    print(f"{'来源':10} {'表名':30} {'源行数':>8} {'目标行数':>8} {'新插入':>8}")
    for key, table, src_n, dst_n, ins in report:
        mark = "OK" if dst_n >= src_n else "!! 缺行"
        print(f"{key:10} {table:30} {src_n:>8} {dst_n:>8} {ins:>8}  {mark}")
    if failed:
        print(f"\n[失败] {len(failed)} 张表目标行数少于源,迁移不完整:")
        for f in failed:
            print(f"  {f}")
        return 2
    print(f"\n[完成] 共迁移 {len(report)} 张表 -> {args.target}")
    print("[提醒] 迁移完成后源库文件不删除;确认新系统运行正常后可手动归档。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
