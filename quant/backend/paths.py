from __future__ import annotations

import shutil
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

TRADING_DB_PATH = DATA_DIR / "trading.db"
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
    _migrate_legacy_file(LEGACY_TRADING_DB_PATH, TRADING_DB_PATH)
    _migrate_legacy_file(LEGACY_CUSTOM_ETF_PATH, CUSTOM_ETF_PATH)
    _migrate_legacy_file(LEGACY_REMOVED_ETF_PATH, REMOVED_ETF_PATH)
