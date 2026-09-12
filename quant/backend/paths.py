from __future__ import annotations

import os
import shutil
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# 合并进 StockRank 仓库后,业务库统一用仓库根的 data/stockrank.db
# (与 Flask 侧 core/config.UNIFIED_DB_FILE 指向同一文件;WAL + busy_timeout 保证双进程并发安全)。
# 注意:容器内 backend 挂载在 /app/backend,PROJECT_ROOT.parent 不是仓库根,
# 故支持 QUANT_DB_PATH 显式注入(compose 已配 /app/unified_data/stockrank.db,
# 该目录挂的正是宿主机 <仓库根>/data,与 Flask 同库);本地裸跑仍按目录推导。
MERGE_ROOT = PROJECT_ROOT.parent
_env_db_path = os.environ.get("QUANT_DB_PATH", "").strip()
TRADING_DB_PATH = Path(_env_db_path) if _env_db_path else MERGE_ROOT / "data" / "stockrank.db"
CUSTOM_ETF_PATH = DATA_DIR / "custom_etfs.json"
REMOVED_ETF_PATH = DATA_DIR / "removed_etfs.json"
PYTDX_HOST_CACHE_PATH = DATA_DIR / "pytdx_hosts.json"
A_SHARE_SPOT_CACHE_PATH = DATA_DIR / "a_share_spot.json"
DOWNLOAD_UNIVERSE_CACHE_PATH = DATA_DIR / "download_universe.json"

KLINE_PARQUET_DIR = DATA_DIR / "kline"

LEGACY_TRADING_DB_PATH = BACKEND_DIR / "trading.db"
LEGACY_CUSTOM_ETF_PATH = BACKEND_DIR / "custom_etfs.json"
LEGACY_REMOVED_ETF_PATH = BACKEND_DIR / "removed_etfs.json"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def ensure_unified_db_dir() -> Path:
    TRADING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TRADING_DB_PATH.parent


def ensure_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def ensure_kline_dir(code: str = "") -> Path:
    ensure_data_dir()
    KLINE_PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    if code:
        code_dir = KLINE_PARQUET_DIR / code
        code_dir.mkdir(parents=True, exist_ok=True)
        return code_dir
    return KLINE_PARQUET_DIR


def get_kline_parquet_path(code: str, period: str) -> Path:
    code_dir = ensure_kline_dir(code)
    return code_dir / f"{period}.parquet"


def _migrate_legacy_file(legacy_path: Path, new_path: Path):
    if new_path.exists() or not legacy_path.exists():
        return
    ensure_data_dir()
    shutil.copy2(legacy_path, new_path)


def ensure_runtime_storage_ready():
    ensure_data_dir()
    ensure_unified_db_dir()
    # 注意:旧 trading.db 不再自动拷到统一库路径——那会把只含量化表的文件
    # 整个覆盖成 stockrank.db。历史数据迁移由 scripts/server_migration/
    # migrate_unify_db.py 在服务器上一次性完成。
    _migrate_legacy_file(LEGACY_CUSTOM_ETF_PATH, CUSTOM_ETF_PATH)
    _migrate_legacy_file(LEGACY_REMOVED_ETF_PATH, REMOVED_ETF_PATH)
