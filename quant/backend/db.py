import atexit
import json
import math
import os
import sqlite3
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from backend.time_utils import now_beijing
from pathlib import Path
from typing import Iterable, Optional

from backend.paths import (
    TRADING_DB_PATH,
    ensure_runtime_storage_ready,
)


DB_PATH = str(TRADING_DB_PATH)
_init_lock = threading.Lock()
_db_initialized = False
_db_thread_local = threading.local()

_DB_CONNECT_MAX_RETRIES = 5
_DB_CONNECT_RETRY_DELAY = 0.5


def _now_text() -> str:
    # 库内时间字符串统一为北京墙钟(服务器时区不可靠);历史函数名 _utcnow_text 名不符实,已改名
    return now_beijing().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_optional_text(value) -> Optional[str]:
    if value in ("", "-", "--", None):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _is_plausible_bar_date_text(value: str) -> bool:
    text = str(value or "").strip()[:10]
    if not text:
        return False
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return False
    min_date = datetime(1990, 1, 1).date()
    max_date = (now_beijing() + timedelta(days=1)).date()
    return min_date <= parsed <= max_date


_storage_ready = False
_storage_ready_lock = threading.Lock()


def _ensure_storage_ready_once():
    global _storage_ready
    if _storage_ready:
        return
    with _storage_ready_lock:
        if _storage_ready:
            return
        ensure_runtime_storage_ready()
        _storage_ready = True


@contextmanager
def get_connection():
    _ensure_storage_ready_once()
    conn = _get_thread_connection()
    current_depth = int(getattr(_db_thread_local, "tx_depth", 0) or 0)
    outermost = current_depth == 0
    _db_thread_local.tx_depth = current_depth + 1
    try:
        yield conn
        if outermost:
            _commit_connection(conn)
    except Exception:
        if outermost:
            try:
                conn.rollback()
            except Exception:
                close_thread_connection()
        raise
    finally:
        _db_thread_local.tx_depth = max(int(getattr(_db_thread_local, "tx_depth", 1) or 1) - 1, 0)


def _create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _get_thread_connection() -> sqlite3.Connection:
    conn = getattr(_db_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            close_thread_connection()

    last_exc = None
    for attempt in range(_DB_CONNECT_MAX_RETRIES):
        try:
            conn = _create_connection()
            _db_thread_local.conn = conn
            _db_thread_local.tx_depth = 0
            return conn
        except sqlite3.OperationalError as e:
            last_exc = e
            if attempt < _DB_CONNECT_MAX_RETRIES - 1:
                time.sleep(_DB_CONNECT_RETRY_DELAY * (attempt + 1))
    raise last_exc


def _commit_connection(conn: sqlite3.Connection):
    try:
        conn.commit()
        return
    except sqlite3.OperationalError as e:
        if "locked" not in str(e).lower():
            close_thread_connection()
            raise

    for attempt in range(_DB_CONNECT_MAX_RETRIES):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt >= _DB_CONNECT_MAX_RETRIES - 1:
                close_thread_connection()
                raise
            time.sleep(_DB_CONNECT_RETRY_DELAY * (attempt + 1))


def close_thread_connection():
    conn = getattr(_db_thread_local, "conn", None)
    _db_thread_local.conn = None
    _db_thread_local.tx_depth = 0
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


atexit.register(close_thread_connection)


def init_db(
    default_watchlist: Optional[Iterable[dict]] = None,
    legacy_custom_path: Optional[str] = None,
    legacy_removed_path: Optional[str] = None,
):
    global _db_initialized
    if _db_initialized:
        return
    with _init_lock:
        if _db_initialized:
            return
        _init_db_impl(default_watchlist, legacy_custom_path, legacy_removed_path)
        _db_initialized = True


def _init_db_impl(
    default_watchlist: Optional[Iterable[dict]] = None,
    legacy_custom_path: Optional[str] = None,
    legacy_removed_path: Optional[str] = None,
):
    _ensure_storage_ready_once()
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                owner_username TEXT NOT NULL DEFAULT 'vk',
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                market INTEGER NOT NULL DEFAULT 1,
                t0 INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_username, code)
            )
            """
        )
        _ensure_watchlist_owner_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 0,
                strategy_name TEXT NOT NULL DEFAULT 'MACD_Cross',
                interval_minutes INTEGER NOT NULL DEFAULT 30,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "scan_settings", "scan_scope_type", "TEXT NOT NULL DEFAULT 'all'")
        _ensure_column(conn, "scan_settings", "scan_scope_codes", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "scan_settings", "scan_focus_codes", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "scan_settings", "scan_period", "TEXT NOT NULL DEFAULT '30min'")
        _ensure_column(conn, "scan_settings", "auto_download_enabled", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "scan_settings", "auto_download_hour", "INTEGER NOT NULL DEFAULT 15")
        _ensure_column(conn, "scan_settings", "kline_force_refresh", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "scan_settings", "strategy_owner_username", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                strategy TEXT NOT NULL DEFAULT 'MA_BULL_PULLBACK_BOLL',
                start_date TEXT NOT NULL DEFAULT '20240101',
                end_date TEXT NOT NULL DEFAULT '',
                cash REAL NOT NULL DEFAULT 100000.0,
                period TEXT NOT NULL DEFAULT 'daily',
                mode TEXT NOT NULL DEFAULT 'single',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO backtest_settings (id, strategy, start_date, end_date, cash, period, mode, updated_at)
            VALUES (1, 'MA_BULL_PULLBACK_BOLL', '20240101', '', 100000.0, 'daily', 'single', ?)
            """,
            (_now_text(),),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                strategy_name TEXT NOT NULL,
                owner_username TEXT,
                trigger_type TEXT NOT NULL DEFAULT 'auto',
                candidate_count INTEGER NOT NULL DEFAULT 0,
                scanned_count INTEGER NOT NULL DEFAULT 0,
                signal_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                message TEXT
            )
            """
        )
        _ensure_column(conn, "scan_runs", "trigger_type", "TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "scan_runs", "owner_username", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                price REAL NOT NULL,
                signal_time TEXT NOT NULL,
                reason TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                owner_username TEXT,
                period TEXT NOT NULL DEFAULT '30',
                detected_at TEXT NOT NULL,
                run_slot TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                UNIQUE(code, direction, signal_time, strategy_name, period)
            )
            """
        )
        _ensure_column(conn, "scan_signals", "run_id", "INTEGER")
        _ensure_column(conn, "scan_signals", "owner_username", "TEXT")
        # --- 套利背离监控（分时叠加 + 基准背离提示） ---
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS arb_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO arb_settings (id, enabled, updated_at) VALUES (1, 1, ?)
            """,
            (_now_text(),),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS arb_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_username TEXT NOT NULL DEFAULT 'vk',
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                bench_kind TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_label TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                preopen_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(owner_username, stock_code, bench_kind, bench_code)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_arb_pairs_owner ON arb_pairs (owner_username, enabled)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS arb_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id INTEGER NOT NULL,
                owner_username TEXT,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                bench_kind TEXT NOT NULL,
                bench_code TEXT NOT NULL,
                bench_label TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_time TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                stock_pct REAL,
                bench_pct REAL,
                beta REAL,
                corr REAL,
                spread_sigma REAL,
                reason TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                UNIQUE(pair_id, direction, trade_date, signal_time)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_arb_alerts_owner_time ON arb_alerts (owner_username, detected_at)
            """
        )
        # delivered: 是否已被下游(StockRank 异动预警)经 /arb/feed 拉走;与 is_read(闭环回执)独立
        _ensure_column(conn, "arb_alerts", "delivered", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bench_registry (
                keyword TEXT PRIMARY KEY,
                items TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_username TEXT NOT NULL,
                signal_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_price REAL NOT NULL,
                signal_time TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                period TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                tracked_at TEXT NOT NULL,
                UNIQUE(owner_username, signal_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_signal_settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_username TEXT NOT NULL,
                tracked_signal_id INTEGER NOT NULL,
                signal_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_price REAL NOT NULL,
                signal_time TEXT NOT NULL,
                exit_price REAL NOT NULL,
                exit_time TEXT NOT NULL,
                return_pct REAL NOT NULL,
                strategy_name TEXT NOT NULL,
                period TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                tracked_at TEXT NOT NULL,
                settled_at TEXT NOT NULL,
                removed_from_watchlist INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tracked_signal_settlements_owner_code
            ON tracked_signal_settlements (owner_username, code, settled_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tracked_signals_owner_code
            ON tracked_signals (owner_username, code)
            """
        )
        conn.execute(
            """
            UPDATE scan_signals
            SET run_id = (
                SELECT scan_runs.id
                FROM scan_runs
                WHERE scan_signals.detected_at >= scan_runs.started_at
                  AND (
                    scan_runs.finished_at IS NULL
                    OR scan_signals.detected_at <= datetime(scan_runs.finished_at, '+3 seconds')
                  )
                ORDER BY scan_runs.id DESC
                LIMIT 1
            )
            WHERE run_id IS NULL
              AND EXISTS (
                SELECT 1
                FROM scan_runs
                WHERE scan_signals.detected_at >= scan_runs.started_at
                  AND (
                    scan_runs.finished_at IS NULL
                    OR scan_signals.detected_at <= datetime(scan_runs.finished_at, '+3 seconds')
                  )
              )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_pool (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                market INTEGER NOT NULL DEFAULT 1,
                security_type TEXT NOT NULL DEFAULT 'stock',
                total_mv REAL,
                circ_mv REAL,
                price REAL,
                change_pct REAL,
                prev_close REAL,
                is_st INTEGER NOT NULL DEFAULT 0,
                is_delisted INTEGER NOT NULL DEFAULT 0,
                is_low_mv INTEGER NOT NULL DEFAULT 0,
                ma144_passed INTEGER NOT NULL DEFAULT 0,
                scan_eligible INTEGER NOT NULL DEFAULT 1,
                kline_downloaded INTEGER NOT NULL DEFAULT 0,
                download_source TEXT,
                industry TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_pool_eligible
            ON stock_pool (scan_eligible, security_type)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_pool_type
            ON stock_pool (security_type, code)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                owner_username TEXT,
                symbol TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                final_capital REAL NOT NULL,
                total_return REAL NOT NULL DEFAULT 0,
                max_drawdown REAL NOT NULL DEFAULT 0,
                sharpe_ratio REAL,
                win_rate REAL,
                total_trades INTEGER NOT NULL DEFAULT 0,
                winning_trades INTEGER NOT NULL DEFAULT 0,
                params TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS full_backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                owner_username TEXT,
                period TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                target_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                profitable_count INTEGER NOT NULL DEFAULT 0,
                loss_count INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                cumulative_return REAL NOT NULL DEFAULT 0,
                average_return REAL NOT NULL DEFAULT 0,
                max_drawdown REAL NOT NULL DEFAULT 0,
                max_gain REAL NOT NULL DEFAULT 0,
                payload TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL DEFAULT 'default',
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                current_price REAL,
                market_value REAL,
                unrealized_pnl REAL,
                unrealized_pnl_pct REAL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, symbol)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL DEFAULT 'default',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0,
                pnl REAL,
                strategy TEXT,
                signal_id INTEGER,
                executed_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                param_key TEXT NOT NULL,
                param_value TEXT NOT NULL,
                param_type TEXT NOT NULL DEFAULT 'string',
                description TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(strategy_name, param_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "auth_users", "expires_at", "TEXT")
        _ensure_column(conn, "auth_users", "status", "TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(conn, "auth_users", "must_change_credentials", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "auth_users", "last_login_at", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_orders (
                id TEXT PRIMARY KEY,
                plan_key TEXT NOT NULL,
                plan_label TEXT NOT NULL,
                amount REAL NOT NULL,
                duration_days INTEGER NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'alipay',
                provider_trade_no TEXT,
                username TEXT,
                password_plain TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT
            )
            """
        )
        _ensure_column(conn, "payment_orders", "buyer_username", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_captchas (
                captcha_id TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_backtest_results_strategy
            ON backtest_results (strategy_name, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_full_backtest_runs_strategy
            ON full_backtest_runs (strategy_name, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trades_account_symbol
            ON trades (account_id, symbol, executed_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_username
            ON auth_sessions (username, expires_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auth_captchas_expires
            ON auth_captchas (expires_at)
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO scan_settings (id, enabled, strategy_name, interval_minutes, updated_at)
            VALUES (1, 0, 'MACD_Cross', 30, ?)
            """,
            (_now_text(),),
        )
        conn.execute(
            "UPDATE scan_settings SET auto_download_hour = 15 WHERE auto_download_hour < 15"
        )

        _ensure_column(conn, "stock_pool", "ma144_passed", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "stock_pool", "scan_eligible", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "stock_pool", "kline_downloaded", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "stock_pool", "download_source", "TEXT")
        _ensure_column(conn, "stock_pool", "industry", "TEXT")
        _ensure_column(conn, "stock_pool", "kline_periods", "TEXT")
        _ensure_column(conn, "stock_pool", "kline_time_span", "TEXT")
        _ensure_column(conn, "backtest_results", "owner_username", "TEXT")
        _ensure_column(conn, "full_backtest_runs", "owner_username", "TEXT")

        existing_count = conn.execute("SELECT COUNT(1) AS cnt FROM watchlist").fetchone()["cnt"]
        if existing_count == 0:
            removed_codes = _load_legacy_removed_codes(legacy_removed_path)
            merged = {}
            for item in list(default_watchlist or []) + _load_legacy_watchlist(legacy_custom_path):
                code = str(item.get("code", "")).strip().zfill(6)
                if not code or code in removed_codes:
                    continue
                merged[code] = {
                    "code": code,
                    "name": str(item.get("name", "") or code),
                    "market": int(item.get("market", 1)),
                    "t0": 1 if item.get("t0") else 0,
                }
            now_text = _now_text()
            for item in merged.values():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO watchlist (code, name, market, t0, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item["code"], item["name"], item["market"], item["t0"], now_text),
                )


def _load_legacy_watchlist(file_path: Optional[str]) -> list:
    if not file_path or not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str):
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(str(row["name"]) == column_name for row in columns):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _ensure_watchlist_owner_schema(conn: sqlite3.Connection):
    columns = conn.execute("PRAGMA table_info(watchlist)").fetchall()
    owner_column = next((row for row in columns if str(row["name"]) == "owner_username"), None)
    code_column = next((row for row in columns if str(row["name"]) == "code"), None)
    if owner_column and code_column and int(owner_column["pk"] or 0) > 0 and int(code_column["pk"] or 0) > 0:
        return

    conn.execute("ALTER TABLE watchlist RENAME TO watchlist_legacy_owner_migration")
    conn.execute(
        """
        CREATE TABLE watchlist (
            owner_username TEXT NOT NULL DEFAULT 'vk',
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            market INTEGER NOT NULL DEFAULT 1,
            t0 INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (owner_username, code)
        )
        """
    )
    legacy_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(watchlist_legacy_owner_migration)").fetchall()
    }
    owner_expr = "LOWER(TRIM(owner_username))" if "owner_username" in legacy_columns else "'vk'"
    conn.execute(
        f"""
        INSERT OR IGNORE INTO watchlist (owner_username, code, name, market, t0, created_at)
        SELECT COALESCE(NULLIF({owner_expr}, ''), 'vk'), code, name, market, t0, created_at
        FROM watchlist_legacy_owner_migration
        """
    )
    conn.execute("DROP TABLE watchlist_legacy_owner_migration")


def _load_legacy_removed_codes(file_path: Optional[str]) -> set[str]:
    if not file_path or not os.path.exists(file_path):
        return set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return set()
        return {str(code).strip().zfill(6) for code in data if str(code).strip()}
    except Exception:
        return set()


def _load_legacy_json_rows(file_path: Path) -> list[dict]:
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def _normalize_watchlist_owner(owner_username: Optional[str]) -> str:
    owner = str(owner_username or "").strip().lower()
    return owner or "vk"


def list_watchlist(owner_username: Optional[str] = None) -> list[dict]:
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT owner_username, code, name, market, t0, created_at
            FROM watchlist
            WHERE owner_username = ?
            ORDER BY created_at ASC, code ASC
            """,
            (owner,),
        ).fetchall()
    return [
        {
            "owner_username": row["owner_username"],
            "code": row["code"],
            "name": row["name"],
            "market": int(row["market"]),
            "t0": bool(row["t0"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_watchlist_item(code: str, owner_username: Optional[str] = None) -> Optional[dict]:
    code = str(code).strip().zfill(6)
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT owner_username, code, name, market, t0, created_at
            FROM watchlist
            WHERE owner_username = ? AND code = ?
            """,
            (owner, code),
        ).fetchone()
    if not row:
        return None
    return {
        "owner_username": row["owner_username"],
        "code": row["code"],
        "name": row["name"],
        "market": int(row["market"]),
        "t0": bool(row["t0"]),
        "created_at": row["created_at"],
    }


def upsert_watchlist_item(code: str, name: str, market: int, t0: bool, owner_username: Optional[str] = None) -> dict:
    code = str(code).strip().zfill(6)
    owner = _normalize_watchlist_owner(owner_username)
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO watchlist (owner_username, code, name, market, t0, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_username, code) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                t0 = excluded.t0
            """,
            (owner, code, name or code, int(market), 1 if t0 else 0, now_text),
        )
    return get_watchlist_item(code, owner) or {
        "owner_username": owner,
        "code": code,
        "name": name or code,
        "market": int(market),
        "t0": bool(t0),
        "created_at": now_text,
    }


def delete_watchlist_item(code: str, owner_username: Optional[str] = None):
    code = str(code).strip().zfill(6)
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE owner_username = ? AND code = ?", (owner, code))


def track_signal(signal_id: int, owner_username: Optional[str] = None) -> dict:
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, code, name, direction, price, signal_time, reason, strategy_name, period
            FROM scan_signals
            WHERE id = ?
            """,
            (signal_id,),
        ).fetchone()
    if not row:
        return {"success": False, "message": "信号不存在"}
    code = str(row["code"]).strip().zfill(6)
    name = row["name"]
    direction = row["direction"]
    signal_price = float(row["price"])
    signal_time = row["signal_time"]
    reason = row["reason"] or ""
    strategy_name = row["strategy_name"]
    period = row["period"]
    now_text = _now_text()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tracked_signals (owner_username, signal_id, code, name, direction, signal_price, signal_time, strategy_name, period, reason, tracked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_username, signal_id) DO UPDATE SET
                    code = excluded.code,
                    name = excluded.name,
                    direction = excluded.direction,
                    signal_price = excluded.signal_price,
                    signal_time = excluded.signal_time,
                    strategy_name = excluded.strategy_name,
                    period = excluded.period,
                    reason = excluded.reason,
                    tracked_at = excluded.tracked_at
                """,
                (owner, signal_id, code, name, direction, signal_price, signal_time, strategy_name, period, reason, now_text),
            )
            tracked_row = conn.execute(
                "SELECT id FROM tracked_signals WHERE owner_username = ? AND signal_id = ?",
                (owner, signal_id),
            ).fetchone()
        tracked_id = tracked_row["id"] if tracked_row else None
    except Exception as e:
        return {"success": False, "message": str(e)}
    return {
        "success": True,
        "data": {
            "tracked_id": tracked_id,
            "code": code,
            "name": name,
        },
    }


def untrack_signal(
    tracked_id: int,
    exit_price: float,
    exit_time: Optional[str] = None,
    owner_username: Optional[str] = None,
    removed_from_watchlist: bool = False,
) -> Optional[dict]:
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, owner_username, signal_id, code, name, direction,
                   signal_price, signal_time, strategy_name, period, reason, tracked_at
            FROM tracked_signals
            WHERE id = ? AND owner_username = ?
            """,
            (tracked_id, owner),
        ).fetchone()
        if not row:
            return None
        signal_price = float(row["signal_price"])
        settled_at = str(exit_time or _now_text()).strip() or _now_text()
        return_pct = round((float(exit_price) - signal_price) / signal_price * 100, 2) if signal_price > 0 else 0.0
        conn.execute(
            """
            INSERT INTO tracked_signal_settlements (
                owner_username, tracked_signal_id, signal_id, code, name, direction,
                signal_price, signal_time, exit_price, exit_time, return_pct,
                strategy_name, period, reason, tracked_at, settled_at, removed_from_watchlist
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["owner_username"],
                int(row["id"]),
                int(row["signal_id"]),
                row["code"],
                row["name"],
                row["direction"],
                signal_price,
                row["signal_time"],
                float(exit_price),
                settled_at,
                return_pct,
                row["strategy_name"],
                row["period"],
                row["reason"] or "",
                row["tracked_at"],
                settled_at,
                1 if removed_from_watchlist else 0,
            ),
        )
        conn.execute("DELETE FROM tracked_signals WHERE id = ? AND owner_username = ?", (tracked_id, owner))
    return {
        "id": tracked_id,
        "code": row["code"],
        "name": row["name"],
        "signal_id": int(row["signal_id"]),
        "direction": row["direction"],
        "signal_price": signal_price,
        "signal_time": row["signal_time"],
        "exit_price": float(exit_price),
        "exit_time": settled_at,
        "return_pct": return_pct,
        "strategy_name": row["strategy_name"],
        "period": row["period"],
        "reason": row["reason"] or "",
        "tracked_at": row["tracked_at"],
        "removed_from_watchlist": bool(removed_from_watchlist),
    }


def list_tracked_signals(owner_username: Optional[str] = None) -> list[dict]:
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, owner_username, signal_id, code, name, direction,
                   signal_price, signal_time, strategy_name, period, reason, tracked_at
            FROM tracked_signals
            WHERE owner_username = ?
            ORDER BY tracked_at DESC
            """,
            (owner,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "owner_username": row["owner_username"],
            "signal_id": row["signal_id"],
            "code": row["code"],
            "name": row["name"],
            "direction": row["direction"],
            "signal_price": float(row["signal_price"]),
            "signal_time": row["signal_time"],
            "strategy_name": row["strategy_name"],
            "period": row["period"],
            "reason": row["reason"],
            "tracked_at": row["tracked_at"],
        }
        for row in rows
    ]


def get_tracked_signals_by_code(code: str, owner_username: Optional[str] = None) -> list[dict]:
    code = str(code).strip().zfill(6)
    owner = _normalize_watchlist_owner(owner_username)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, owner_username, signal_id, code, name, direction,
                   signal_price, signal_time, strategy_name, period, reason, tracked_at
            FROM tracked_signals
            WHERE owner_username = ? AND code = ?
            ORDER BY tracked_at DESC
            """,
            (owner, code),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "owner_username": row["owner_username"],
            "signal_id": row["signal_id"],
            "code": row["code"],
            "name": row["name"],
            "direction": row["direction"],
            "signal_price": float(row["signal_price"]),
            "signal_time": row["signal_time"],
            "strategy_name": row["strategy_name"],
            "period": row["period"],
            "reason": row["reason"],
            "tracked_at": row["tracked_at"],
        }
        for row in rows
    ]


def list_settled_signals(
    code: Optional[str] = None,
    owner_username: Optional[str] = None,
) -> list[dict]:
    """读取已结算归档的历史跟踪记录（按结束日期倒序）。

    对应 tracked_signal_settlements 表，此前仅写入不读取，本函数补齐「读」链路。
    """
    owner = _normalize_watchlist_owner(owner_username)
    normalized_code = str(code).strip().zfill(6) if code else ""
    with get_connection() as conn:
        if normalized_code:
            rows = conn.execute(
                """
                SELECT id, owner_username, tracked_signal_id, signal_id, code, name, direction,
                       signal_price, signal_time, exit_price, exit_time, return_pct,
                       strategy_name, period, reason, tracked_at, settled_at, removed_from_watchlist
                FROM tracked_signal_settlements
                WHERE owner_username = ? AND code = ?
                ORDER BY settled_at DESC
                """,
                (owner, normalized_code),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, owner_username, tracked_signal_id, signal_id, code, name, direction,
                       signal_price, signal_time, exit_price, exit_time, return_pct,
                       strategy_name, period, reason, tracked_at, settled_at, removed_from_watchlist
                FROM tracked_signal_settlements
                WHERE owner_username = ?
                ORDER BY settled_at DESC
                """,
                (owner,),
            ).fetchall()
    return [
        {
            "id": row["id"],
            "owner_username": row["owner_username"],
            "tracked_signal_id": int(row["tracked_signal_id"]),
            "signal_id": int(row["signal_id"]),
            "code": row["code"],
            "name": row["name"],
            "direction": row["direction"],
            "signal_price": float(row["signal_price"]),
            "signal_time": row["signal_time"],
            "exit_price": float(row["exit_price"]),
            "exit_time": row["exit_time"],
            "return_pct": float(row["return_pct"]),
            "strategy_name": row["strategy_name"],
            "period": row["period"],
            "reason": row["reason"] or "",
            "tracked_at": row["tracked_at"],
            "settled_at": row["settled_at"],
            "removed_from_watchlist": bool(row["removed_from_watchlist"]),
        }
        for row in rows
    ]


def get_scan_settings() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT enabled, strategy_name, interval_minutes, updated_at, scan_scope_type, scan_scope_codes,
                   scan_focus_codes,
                   scan_period, auto_download_enabled, auto_download_hour, kline_force_refresh, strategy_owner_username
            FROM scan_settings
            WHERE id = 1
            """
        ).fetchone()
    if not row:
        return {
            "enabled": False,
            "strategy_name": "MACD_Cross",
            "interval_minutes": 30,
            "scan_scope_type": "all",
            "scan_scope_codes": [],
            "scan_focus_codes": [],
            "scan_period": "30min",
            "auto_download_enabled": True,
            "auto_download_hour": 15,
            "kline_force_refresh": False,
            "strategy_owner_username": None,
            "updated_at": _now_text(),
        }
    try:
        scope_codes = json.loads(row["scan_scope_codes"] or "[]")
    except Exception:
        scope_codes = []
    try:
        focus_codes = json.loads(row["scan_focus_codes"] or "[]")
    except Exception:
        focus_codes = []
    return {
        "enabled": bool(row["enabled"]),
        "strategy_name": row["strategy_name"],
        "interval_minutes": int(row["interval_minutes"]),
        "scan_scope_type": row["scan_scope_type"] or "all",
        "scan_scope_codes": [str(code).strip().zfill(6) for code in scope_codes if str(code).strip()],
        "scan_focus_codes": [str(code).strip().zfill(6) for code in focus_codes if str(code).strip()],
        "scan_period": row["scan_period"] or "30min",
        "auto_download_enabled": bool(row["auto_download_enabled"]) if "auto_download_enabled" in row.keys() else True,
        "auto_download_hour": max(15, int(row["auto_download_hour"])) if "auto_download_hour" in row.keys() else 15,
        "kline_force_refresh": bool(row["kline_force_refresh"]) if "kline_force_refresh" in row.keys() else False,
        "strategy_owner_username": row["strategy_owner_username"] if "strategy_owner_username" in row.keys() else None,
        "updated_at": row["updated_at"],
    }


def update_scan_settings(
    enabled: Optional[bool] = None,
    strategy_name: Optional[str] = None,
    interval_minutes: Optional[int] = None,
    scan_scope_type: Optional[str] = None,
    scan_scope_codes: Optional[Iterable[str]] = None,
    scan_focus_codes: Optional[Iterable[str]] = None,
    scan_period: Optional[str] = None,
    auto_download_enabled: Optional[bool] = None,
    auto_download_hour: Optional[int] = None,
    kline_force_refresh: Optional[bool] = None,
    strategy_owner_username: Optional[str] = None,
) -> dict:
    current = get_scan_settings()
    next_enabled = current["enabled"] if enabled is None else bool(enabled)
    next_strategy = current["strategy_name"] if strategy_name is None else str(strategy_name)
    next_interval = current["interval_minutes"] if interval_minutes is None else int(interval_minutes)
    next_scope_type = current["scan_scope_type"] if scan_scope_type is None else str(scan_scope_type or "all")
    next_scope_codes = (
        list(current["scan_scope_codes"])
        if scan_scope_codes is None
        else [str(code).strip().zfill(6) for code in scan_scope_codes if str(code).strip()]
    )
    next_focus_codes = (
        list(current["scan_focus_codes"])
        if scan_focus_codes is None
        else [str(code).strip().zfill(6) for code in scan_focus_codes if str(code).strip()]
    )
    next_scan_period = current["scan_period"] if scan_period is None else str(scan_period or "30min")
    next_auto_dl = current["auto_download_enabled"] if auto_download_enabled is None else bool(auto_download_enabled)
    next_auto_dl_hour = current["auto_download_hour"] if auto_download_hour is None else max(15, int(auto_download_hour))
    next_kline_force_refresh = current["kline_force_refresh"] if kline_force_refresh is None else bool(kline_force_refresh)
    next_owner = (
        current.get("strategy_owner_username")
        if strategy_owner_username is None
        else (str(strategy_owner_username).strip().lower() or None)
    )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scan_settings
            SET enabled = ?, strategy_name = ?, interval_minutes = ?, scan_scope_type = ?, scan_scope_codes = ?, scan_focus_codes = ?,
                scan_period = ?, auto_download_enabled = ?, auto_download_hour = ?, kline_force_refresh = ?, strategy_owner_username = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                1 if next_enabled else 0,
                next_strategy,
                next_interval,
                next_scope_type,
                json.dumps(next_scope_codes, ensure_ascii=False),
                json.dumps(next_focus_codes, ensure_ascii=False),
                next_scan_period,
                1 if next_auto_dl else 0,
                next_auto_dl_hour,
                1 if next_kline_force_refresh else 0,
                next_owner,
                _now_text(),
            ),
        )
    return get_scan_settings()


def get_arb_settings() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT enabled, updated_at FROM arb_settings WHERE id = 1"
        ).fetchone()
    if not row:
        return {"enabled": True, "updated_at": _now_text()}
    return {"enabled": bool(row["enabled"]), "updated_at": row["updated_at"]}


def update_arb_settings(enabled: Optional[bool] = None) -> dict:
    current = get_arb_settings()
    next_enabled = current["enabled"] if enabled is None else bool(enabled)
    with get_connection() as conn:
        conn.execute(
            "UPDATE arb_settings SET enabled = ?, updated_at = ? WHERE id = 1",
            (1 if next_enabled else 0, _now_text()),
        )
    return get_arb_settings()


def _arb_pair_row_to_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "owner_username": row["owner_username"],
        "stock_code": row["stock_code"],
        "stock_name": row["stock_name"],
        "bench_kind": row["bench_kind"],
        "bench_code": row["bench_code"],
        "bench_label": row["bench_label"],
        "enabled": bool(row["enabled"]),
        "preopen_enabled": bool(row["preopen_enabled"]),
        "created_at": row["created_at"],
    }


def list_arb_pairs(owner_username: Optional[str] = None, enabled_only: bool = False) -> list[dict]:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "arb_pairs")
    enabled_clause = "AND enabled = 1" if enabled_only else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label,
                   enabled, preopen_enabled, created_at
            FROM arb_pairs
            WHERE 1 = 1
            {owner_clause}
            {enabled_clause}
            ORDER BY id
            """,
            tuple(owner_params),
        ).fetchall()
    return [_arb_pair_row_to_dict(row) for row in rows]


def count_arb_pairs(owner_username: Optional[str]) -> int:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "arb_pairs")
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(1) AS total FROM arb_pairs WHERE 1 = 1 {owner_clause}",
            tuple(owner_params),
        ).fetchone()
    return int(row["total"]) if row else 0


def add_arb_pair(
    stock_code: str,
    stock_name: str,
    bench_kind: str,
    bench_code: str,
    bench_label: str,
    owner_username: Optional[str] = None,
    preopen_enabled: bool = True,
) -> dict:
    code = str(stock_code).strip().zfill(6)
    owner = _normalize_owner_username(owner_username) or "vk"
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO arb_pairs
            (owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label, enabled, preopen_enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                owner,
                code,
                str(stock_name or code).strip() or code,
                str(bench_kind).strip(),
                str(bench_code).strip(),
                str(bench_label or bench_code).strip() or bench_code,
                1 if preopen_enabled else 0,
                _now_text(),
            ),
        )
        if cursor.rowcount == 0:
            # 同一对已存在：刷新名称/标签并原样返回
            conn.execute(
                """
                UPDATE arb_pairs
                SET stock_name = ?, bench_label = ?, preopen_enabled = ?
                WHERE owner_username = ? AND stock_code = ? AND bench_kind = ? AND bench_code = ?
                """,
                (
                    str(stock_name or code).strip() or code,
                    str(bench_label or bench_code).strip() or bench_code,
                    1 if preopen_enabled else 0,
                    owner,
                    code,
                    str(bench_kind).strip(),
                    str(bench_code).strip(),
                ),
            )
            row = conn.execute(
                """
                SELECT id, owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label,
                       enabled, preopen_enabled, created_at
                FROM arb_pairs
                WHERE owner_username = ? AND stock_code = ? AND bench_kind = ? AND bench_code = ?
                """,
                (owner, code, str(bench_kind).strip(), str(bench_code).strip()),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label,
                       enabled, preopen_enabled, created_at
                FROM arb_pairs WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
    pair = _arb_pair_row_to_dict(row)
    pair["existed"] = cursor.rowcount == 0
    return pair


def remove_arb_pair(pair_id: int, owner_username: Optional[str] = None) -> bool:
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        if owner and owner != "vk":
            cursor = conn.execute("DELETE FROM arb_pairs WHERE id = ? AND owner_username = ?", (int(pair_id), owner))
        else:
            cursor = conn.execute("DELETE FROM arb_pairs WHERE id = ?", (int(pair_id),))
        return cursor.rowcount > 0


def set_arb_pair_enabled(pair_id: int, enabled: bool, owner_username: Optional[str] = None) -> bool:
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        if owner and owner != "vk":
            cursor = conn.execute(
                "UPDATE arb_pairs SET enabled = ? WHERE id = ? AND owner_username = ?",
                (1 if enabled else 0, int(pair_id), owner),
            )
        else:
            cursor = conn.execute("UPDATE arb_pairs SET enabled = ? WHERE id = ?", (1 if enabled else 0, int(pair_id)))
        return cursor.rowcount > 0


def insert_arb_alert(
    pair_id: int,
    stock_code: str,
    stock_name: str,
    bench_kind: str,
    bench_code: str,
    bench_label: str,
    direction: str,
    signal_time: str,
    trade_date: str,
    reason: str,
    owner_username: Optional[str] = None,
    stock_pct: Optional[float] = None,
    bench_pct: Optional[float] = None,
    beta: Optional[float] = None,
    corr: Optional[float] = None,
    spread_sigma: Optional[float] = None,
) -> Optional[dict]:
    """写入一条背离提示；同 (pair,direction,trade_date,signal_time) 已存在时返回 None（用于去重/冷却）。"""
    detected_at = _now_text()
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO arb_alerts
            (pair_id, owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label,
             direction, signal_time, trade_date, stock_pct, bench_pct, beta, corr, spread_sigma,
             reason, detected_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                int(pair_id),
                owner,
                str(stock_code).strip().zfill(6),
                str(stock_name or stock_code).strip(),
                str(bench_kind).strip(),
                str(bench_code).strip(),
                str(bench_label or bench_code).strip(),
                str(direction).strip(),
                str(signal_time).strip(),
                str(trade_date).strip(),
                float(stock_pct) if stock_pct is not None else None,
                float(bench_pct) if bench_pct is not None else None,
                float(beta) if beta is not None else None,
                float(corr) if corr is not None else None,
                float(spread_sigma) if spread_sigma is not None else None,
                reason,
                detected_at,
            ),
        )
        if cursor.rowcount == 0:
            return None
        alert_id = int(cursor.lastrowid)
    return {
        "id": alert_id,
        "pair_id": int(pair_id),
        "owner_username": owner,
        "stock_code": str(stock_code).strip().zfill(6),
        "stock_name": str(stock_name or stock_code).strip(),
        "bench_kind": str(bench_kind).strip(),
        "bench_code": str(bench_code).strip(),
        "bench_label": str(bench_label or bench_code).strip(),
        "direction": str(direction).strip(),
        "signal_time": str(signal_time).strip(),
        "trade_date": str(trade_date).strip(),
        "stock_pct": stock_pct,
        "bench_pct": bench_pct,
        "beta": beta,
        "corr": corr,
        "spread_sigma": spread_sigma,
        "reason": reason,
        "detected_at": detected_at,
        "is_read": False,
    }


def list_arb_alerts(limit: int = 100, owner_username: Optional[str] = None) -> list[dict]:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "arb_alerts")
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, pair_id, owner_username, stock_code, stock_name, bench_kind, bench_code, bench_label,
                   direction, signal_time, trade_date, stock_pct, bench_pct, beta, corr, spread_sigma,
                   reason, detected_at, is_read
            FROM arb_alerts
            WHERE 1 = 1
            {owner_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*owner_params, int(limit)),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "pair_id": int(row["pair_id"]),
            "owner_username": row["owner_username"],
            "stock_code": row["stock_code"],
            "stock_name": row["stock_name"],
            "bench_kind": row["bench_kind"],
            "bench_code": row["bench_code"],
            "bench_label": row["bench_label"],
            "direction": row["direction"],
            "signal_time": row["signal_time"],
            "trade_date": row["trade_date"],
            "stock_pct": row["stock_pct"],
            "bench_pct": row["bench_pct"],
            "beta": row["beta"],
            "corr": row["corr"],
            "spread_sigma": row["spread_sigma"],
            "reason": row["reason"],
            "detected_at": row["detected_at"],
            "is_read": bool(row["is_read"]),
        }
        for row in rows
    ]


def mark_arb_alerts_read(alert_ids: Iterable[int], owner_username: Optional[str] = None) -> int:
    ids = [int(alert_id) for alert_id in alert_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE arb_alerts SET is_read = 1 WHERE id IN ({placeholders})", tuple(ids))
        return cursor.rowcount


def list_undelivered_arb_alerts(limit: int = 50) -> list[dict]:
    """尚未被下游(StockRank)经 /arb/feed 拉走的告警,按 id 升序(先产生的先推)。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, pair_id, stock_code, stock_name, bench_kind, bench_code, bench_label,
                   direction, signal_time, trade_date, stock_pct, bench_pct, reason, detected_at
            FROM arb_alerts
            WHERE delivered = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "pair_id": int(row["pair_id"]),
            "stock_code": row["stock_code"],
            "stock_name": row["stock_name"],
            "bench_kind": row["bench_kind"],
            "bench_code": row["bench_code"],
            "bench_label": row["bench_label"],
            "direction": row["direction"],
            "signal_time": row["signal_time"],
            "trade_date": row["trade_date"],
            "stock_pct": row["stock_pct"],
            "bench_pct": row["bench_pct"],
            "reason": row["reason"],
            "detected_at": row["detected_at"],
        }
        for row in rows
    ]


def mark_arb_alerts_delivered(alert_ids: Iterable[int]) -> int:
    """把告警标记为已拉取(/arb/feed 取走即标,防下游重复推送)。"""
    ids = [int(alert_id) for alert_id in alert_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE arb_alerts SET delivered = 1 WHERE id IN ({placeholders})", tuple(ids))
        return cursor.rowcount


def get_bench_registry(keyword: str, max_age_seconds: int = 24 * 3600) -> Optional[list[dict]]:
    """按关键词取已缓存的基准代码候选；超过 max_age_seconds 视为过期返回 None。"""
    text = str(keyword or "").strip()
    if not text:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT items, updated_at FROM bench_registry WHERE keyword = ?",
            (text,),
        ).fetchone()
    if not row:
        return None
    try:
        updated_at = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if (now_beijing().replace(tzinfo=None) - updated_at).total_seconds() > max_age_seconds:
        return None
    try:
        items = json.loads(row["items"])
    except Exception:
        return None
    return items if isinstance(items, list) and items else None


def upsert_bench_registry(keyword: str, items: list[dict]) -> None:
    text = str(keyword or "").strip()
    if not text or not items:
        return
    payload = json.dumps(items, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO bench_registry (keyword, items, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(keyword) DO UPDATE SET items = excluded.items, updated_at = excluded.updated_at
            """,
            (text, payload, _now_text()),
        )


def get_backtest_settings() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT strategy, start_date, end_date, cash, period, mode, updated_at
            FROM backtest_settings
            WHERE id = 1
            """
        ).fetchone()
    if not row:
        return {
            "strategy": "MA_BULL_PULLBACK_BOLL",
            "start_date": "20240101",
            "end_date": "",
            "cash": 100000.0,
            "period": "daily",
            "mode": "single",
        }
    return {
        "strategy": row["strategy"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "cash": row["cash"],
        "period": row["period"],
        "mode": row["mode"],
        "updated_at": row["updated_at"],
    }


def update_backtest_settings(
    strategy: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cash: Optional[float] = None,
    period: Optional[str] = None,
    mode: Optional[str] = None,
) -> dict:
    current = get_backtest_settings()
    next_strategy = current["strategy"] if strategy is None else str(strategy)
    next_start = current["start_date"] if start_date is None else str(start_date)
    next_end = current["end_date"] if end_date is None else str(end_date)
    next_cash = current["cash"] if cash is None else float(cash)
    next_period = current["period"] if period is None else str(period)
    next_mode = current["mode"] if mode is None else str(mode)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE backtest_settings
            SET strategy = ?, start_date = ?, end_date = ?, cash = ?, period = ?, mode = ?, updated_at = ?
            WHERE id = 1
            """,
            (next_strategy, next_start, next_end, next_cash, next_period, next_mode, _now_text()),
        )
    return get_backtest_settings()


def _normalize_owner_username(username: Optional[str]) -> Optional[str]:
    text = str(username or "").strip().lower()
    return text or None


def create_scan_run(strategy_name: str, trigger_type: str = "auto", owner_username: Optional[str] = None) -> int:
    normalized_trigger = "manual" if str(trigger_type).lower() == "manual" else "auto"
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scan_runs (started_at, strategy_name, owner_username, trigger_type, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_now_text(), strategy_name, owner, normalized_trigger, "running"),
        )
        return int(cursor.lastrowid)


def finish_scan_run(
    run_id: int,
    candidate_count: int,
    scanned_count: int,
    signal_count: int,
    status: str,
    message: str = "",
):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE scan_runs
            SET finished_at = ?, candidate_count = ?, scanned_count = ?, signal_count = ?, status = ?, message = ?
            WHERE id = ?
            """,
            (_now_text(), candidate_count, scanned_count, signal_count, status, message, int(run_id)),
        )


def _list_scan_run_buy_industries(conn, run_id: int, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(stock_pool.industry), ''), '未分类') AS industry,
            COUNT(DISTINCT scan_signals.code) AS stock_count
        FROM scan_signals
        LEFT JOIN stock_pool ON stock_pool.code = scan_signals.code
        WHERE scan_signals.run_id = ?
          AND scan_signals.direction = 'buy'
        GROUP BY COALESCE(NULLIF(TRIM(stock_pool.industry), ''), '未分类')
        ORDER BY stock_count DESC, industry ASC
        LIMIT ?
        """,
        (int(run_id), int(limit)),
    ).fetchall()
    return [
        {
            "industry": str(row["industry"] or "未分类"),
            "stock_count": int(row["stock_count"] or 0),
        }
        for row in rows
    ]


def _owner_filter_clause(owner_username: Optional[str], table_name: str = "") -> tuple[str, list]:
    owner = _normalize_owner_username(owner_username)
    prefix = f"{table_name}." if table_name else ""
    if owner == "vk":
        return f"AND ({prefix}owner_username = ? OR {prefix}owner_username IS NULL OR TRIM({prefix}owner_username) = '')", [owner]
    if owner:
        return f"AND {prefix}owner_username = ?", [owner]
    return "", []


def _scan_run_display_no_expr(owner_username: Optional[str]) -> tuple[str, list]:
    owner = _normalize_owner_username(owner_username)
    if owner == "vk":
        return (
            """
            (
                SELECT COUNT(1)
                FROM scan_runs sr2
                WHERE sr2.id <= scan_runs.id
                  AND (sr2.owner_username = ? OR sr2.owner_username IS NULL OR TRIM(sr2.owner_username) = '')
            ) AS display_no
            """,
            [owner],
        )
    if owner:
        return (
            """
            (
                SELECT COUNT(1)
                FROM scan_runs sr2
                WHERE sr2.id <= scan_runs.id
                  AND sr2.owner_username = ?
            ) AS display_no
            """,
            [owner],
        )
    return (
        "(SELECT COUNT(1) FROM scan_runs sr2 WHERE sr2.id <= scan_runs.id) AS display_no",
        [],
    )


def get_latest_scan_run(owner_username: Optional[str] = None) -> Optional[dict]:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "scan_runs")
    display_no_expr, display_no_params = _scan_run_display_no_expr(owner_username)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT id, started_at, finished_at, strategy_name, owner_username, trigger_type, candidate_count, scanned_count, signal_count, status, message,
                   {display_no_expr}
            FROM scan_runs
            WHERE 1 = 1
            {owner_clause}
            ORDER BY id DESC
            LIMIT 1
            """,
            (*display_no_params, *owner_params),
        ).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "strategy_name": row["strategy_name"],
        "trigger_type": row["trigger_type"] or "auto",
        "candidate_count": int(row["candidate_count"] or 0),
        "scanned_count": int(row["scanned_count"] or 0),
        "signal_count": int(row["signal_count"] or 0),
        "status": row["status"],
        "message": row["message"] or "",
        "display_no": int(row["display_no"] or row["id"]),
        "buy_industries": _list_scan_run_buy_industries(conn, int(row["id"])),
    }


def list_scan_runs(limit: int = 20, owner_username: Optional[str] = None) -> list[dict]:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "scan_runs")
    display_no_expr, display_no_params = _scan_run_display_no_expr(owner_username)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, started_at, finished_at, strategy_name, owner_username, trigger_type, candidate_count, scanned_count, signal_count, status, message,
                   {display_no_expr}
            FROM scan_runs
            WHERE 1 = 1
            {owner_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*display_no_params, *owner_params, int(limit)),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "strategy_name": row["strategy_name"],
            "owner_username": row["owner_username"],
            "trigger_type": row["trigger_type"] or "auto",
            "candidate_count": int(row["candidate_count"] or 0),
            "scanned_count": int(row["scanned_count"] or 0),
            "signal_count": int(row["signal_count"] or 0),
            "status": row["status"],
            "message": row["message"] or "",
            "display_no": int(row["display_no"] or row["id"]),
            "buy_industries": _list_scan_run_buy_industries(conn, int(row["id"])),
        }
        for row in rows
    ]


def delete_scan_run(run_id: int) -> dict:
    normalized_run_id = int(run_id)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, status FROM scan_runs WHERE id = ?",
            (normalized_run_id,),
        ).fetchone()
        if not row:
            return {
                "deleted": False,
                "run_id": normalized_run_id,
                "signal_count": 0,
                "message": "扫描结果不存在",
            }
        if row["status"] == "running":
            return {
                "deleted": False,
                "run_id": normalized_run_id,
                "signal_count": 0,
                "message": "扫描正在运行中，完成后再删除",
            }

        signal_row = conn.execute(
            "SELECT COUNT(1) AS cnt FROM scan_signals WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        signal_count = int(signal_row["cnt"] or 0)
        conn.execute("DELETE FROM scan_signals WHERE run_id = ?", (normalized_run_id,))
        cursor = conn.execute("DELETE FROM scan_runs WHERE id = ?", (normalized_run_id,))
        return {
            "deleted": cursor.rowcount > 0,
            "run_id": normalized_run_id,
            "signal_count": signal_count,
            "message": "",
        }


def get_scan_run(run_id: int) -> Optional[dict]:
    normalized_run_id = int(run_id)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, started_at, finished_at, strategy_name, owner_username, trigger_type, candidate_count, scanned_count,
                   signal_count, status, message
            FROM scan_runs
            WHERE id = ?
            """,
            (normalized_run_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "strategy_name": row["strategy_name"],
        "owner_username": row["owner_username"],
        "owner_username": row["owner_username"],
        "trigger_type": row["trigger_type"] or "auto",
        "candidate_count": int(row["candidate_count"] or 0),
        "scanned_count": int(row["scanned_count"] or 0),
        "signal_count": int(row["signal_count"] or 0),
        "status": row["status"],
        "message": row["message"] or "",
    }


def insert_scan_signal(
    code: str,
    name: str,
    direction: str,
    price: float,
    signal_time: str,
    reason: str,
    strategy_name: str,
    period: str,
    run_slot: str,
    run_id: Optional[int] = None,
    owner_username: Optional[str] = None,
) -> Optional[dict]:
    code = str(code).strip().zfill(6)
    detected_at = _now_text()
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        if owner is None and run_id is not None:
            owner_row = conn.execute("SELECT owner_username FROM scan_runs WHERE id = ?", (int(run_id),)).fetchone()
            owner = _normalize_owner_username(owner_row["owner_username"]) if owner_row else None
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO scan_signals
            (run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(run_id) if run_id is not None else None,
                code,
                name or code,
                direction,
                float(price),
                signal_time,
                reason,
                strategy_name,
                owner,
                period,
                detected_at,
                run_slot,
            ),
        )
        if cursor.rowcount == 0:
            conn.execute(
                """
                UPDATE scan_signals
                SET run_id = ?, owner_username = ?, price = ?, reason = ?, detected_at = ?, run_slot = ?
                WHERE code = ? AND direction = ? AND signal_time = ? AND strategy_name = ? AND period = ?
                """,
                (
                    int(run_id) if run_id is not None else None,
                    owner,
                    float(price),
                    reason,
                    detected_at,
                    run_slot,
                    code,
                    direction,
                    signal_time,
                    strategy_name,
                    period,
                ),
            )
            existing = conn.execute(
                """
                SELECT id
                FROM scan_signals
                WHERE code = ? AND direction = ? AND signal_time = ? AND strategy_name = ? AND period = ?
                """,
                (code, direction, signal_time, strategy_name, period),
            ).fetchone()
            if not existing:
                return None
            signal_id = int(existing["id"])
        else:
            signal_id = int(cursor.lastrowid)
    return {
        "id": signal_id,
        "run_id": int(run_id) if run_id is not None else None,
        "code": code,
        "name": name or code,
        "direction": direction,
        "price": round(float(price), 5),
        "signal_time": signal_time,
        "reason": reason,
        "strategy_name": strategy_name,
        "owner_username": owner,
        "period": period,
        "detected_at": detected_at,
        "run_slot": run_slot,
        "is_read": False,
    }


def _scan_signal_row_to_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
        "code": row["code"],
        "name": row["name"],
        "direction": row["direction"],
        "price": round(float(row["price"]), 5),
        "signal_time": row["signal_time"],
        "reason": row["reason"],
        "strategy_name": row["strategy_name"],
        "owner_username": row["owner_username"] if "owner_username" in row.keys() else None,
        "period": row["period"],
        "detected_at": row["detected_at"],
        "run_slot": row["run_slot"],
        "is_read": False,
    }


def list_scan_signals(limit: int = 100, owner_username: Optional[str] = None) -> list[dict]:
    owner_clause, owner_params = _owner_filter_clause(owner_username, "scan_signals")
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot
            FROM scan_signals
            WHERE 1 = 1
            {owner_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*owner_params, int(limit)),
        ).fetchall()
    return [_scan_signal_row_to_dict(row) for row in rows]


def list_scan_signals_after(after_id: int, limit: int = 50) -> tuple[list[dict], int]:
    """水位线增量读取:返回 id > after_id 的扫描信号(id 升序)与当前最大 id。

    供 StockRank 消息总线(quant_signal_bridge)拉取;无副作用、不打投递标记。
    """
    normalized_after = max(0, int(after_id))
    with get_connection() as conn:
        max_row = conn.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM scan_signals").fetchone()
        rows = conn.execute(
            """
            SELECT id, run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot
            FROM scan_signals
            WHERE id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (normalized_after, int(limit)),
        ).fetchall()
    return [_scan_signal_row_to_dict(row) for row in rows], int(max_row["max_id"]) if max_row else 0


def list_scan_signals_by_ids(signal_ids: Iterable[int]) -> list[dict]:
    ids = [int(signal_id) for signal_id in signal_ids]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot
            FROM scan_signals
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    return [_scan_signal_row_to_dict(row) for row in rows]


def list_scan_signals_by_run(run_id: int, owner_username: Optional[str] = None) -> list[dict]:
    normalized_run_id = int(run_id)
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        if owner is None:
            rows = conn.execute(
                """
                SELECT id, run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot
                FROM scan_signals
                WHERE run_id = ?
                ORDER BY detected_at DESC, id DESC
                """,
                (normalized_run_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, run_id, code, name, direction, price, signal_time, reason, strategy_name, owner_username, period, detected_at, run_slot
                FROM scan_signals
                WHERE run_id = ? AND owner_username = ?
                ORDER BY detected_at DESC, id DESC
                """,
                (normalized_run_id, owner),
            ).fetchall()
    return [_scan_signal_row_to_dict(row) for row in rows]


def delete_scan_signals(signal_ids: Iterable[int]):
    ids = [int(signal_id) for signal_id in signal_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM scan_signals WHERE id IN ({placeholders})",
            ids,
        )


def _normalize_bar_time(value) -> Optional[str]:
    if value in ("", None):
        return None

    text = str(value).strip().replace("T", " ")
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.strftime("%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text

    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0 and len(text) <= 10:
        return parsed.strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def upsert_price_history(
    code: str,
    period: str,
    bars: Iterable[dict],
    keep_latest: Optional[int] = None,
) -> int:
    from backend.kline_parquet import upsert_kline_parquet, update_kline_sync_state, get_kline_parquet
    
    code = str(code).strip().zfill(6)
    normalized_rows = []
    for item in bars:
        bar_time = _normalize_bar_time(item.get("bar_time") or item.get("datetime") or item.get("date"))
        if not bar_time:
            continue
        normalized_rows.append(
            {
                "bar_time": bar_time,
                "open": float(item.get("open", 0) or 0),
                "high": float(item.get("high", 0) or 0),
                "low": float(item.get("low", 0) or 0),
                "close": float(item.get("close", 0) or 0),
                "volume": float(item.get("volume", 0) or 0),
                "amount": None if item.get("amount") in ("", None) else float(item.get("amount")),
            }
        )

    if not normalized_rows:
        return 0

    keep_limit = int(keep_latest) if keep_latest else 0
    success = upsert_kline_parquet(code, str(period), normalized_rows, keep_latest=keep_limit)
    if success:
        df = get_kline_parquet(code, str(period))
        if not df.empty:
            time_col = "date" if period == "daily" else "datetime"
            first_bar = df[time_col].iloc[0] if len(df) > 0 else None
            last_bar = df[time_col].iloc[-1] if len(df) > 0 else None
            update_kline_sync_state(
                code,
                str(period),
                len(df),
                first_bar.strftime("%Y-%m-%d") if period == "daily" and first_bar else (first_bar.strftime("%Y-%m-%d %H:%M:%S") if first_bar else None),
                last_bar.strftime("%Y-%m-%d") if period == "daily" and last_bar else (last_bar.strftime("%Y-%m-%d %H:%M:%S") if last_bar else None),
            )
        return len(normalized_rows)
    return 0


def get_price_history(code: str, period: str, limit: Optional[int] = None) -> list[dict]:
    from backend.kline_parquet import get_kline_parquet
    
    code = str(code).strip().zfill(6)
    df = get_kline_parquet(code, str(period), limit=limit)
    if df.empty:
        return []
    
    time_col = "date" if period == "daily" else "datetime"
    records = []
    for _, row in df.iterrows():
        bar_time = row[time_col]
        if period == "daily":
            bar_time_str = pd.Timestamp(bar_time).strftime("%Y-%m-%d")
        else:
            bar_time_str = pd.Timestamp(bar_time).strftime("%Y-%m-%d %H:%M:%S")
        records.append(
            {
                "bar_time": bar_time_str,
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
                "amount": None if pd.isna(row.get("amount")) else float(row.get("amount")),
            }
        )
    return records


def get_price_history_sync(code: str, period: str) -> Optional[dict]:
    from backend.kline_parquet import get_kline_sync_state
    
    code = str(code).strip().zfill(6)
    state = get_kline_sync_state(code, str(period))
    if not state:
        return None
    return {
        "code": code,
        "period": str(period),
        "bar_count": int(state.get("bar_count", 0) or 0),
        "first_bar_time": state.get("first_bar_time"),
        "last_bar_time": state.get("last_bar_time"),
        "last_synced_at": state.get("last_synced_at"),
    }


def count_ready_price_history_codes(
    daily_period: str = "daily",
    daily_min_bars: int = 160,
    minute_period: str = "30min",
    minute_min_bars: int = 180,
) -> int:
    from backend.kline_parquet import list_kline_codes, get_kline_bar_count
    
    daily_codes = set()
    for code in list_kline_codes(str(daily_period)):
        if get_kline_bar_count(code, str(daily_period)) >= daily_min_bars:
            daily_codes.add(code)
    
    minute_codes = set()
    for code in list_kline_codes(str(minute_period)):
        if get_kline_bar_count(code, str(minute_period)) >= minute_min_bars:
            minute_codes.add(code)
    
    return len(daily_codes & minute_codes)


def count_ready_price_history_codes_by_requirements(requirements: dict[str, int]) -> int:
    from backend.kline_parquet import list_kline_codes, get_kline_bar_count
    
    normalized = {str(period): int(min_bars) for period, min_bars in requirements.items() if int(min_bars) > 0}
    if not normalized:
        return 0
    
    code_period_ready: dict[str, set[str]] = {}
    for period in normalized:
        for code in list_kline_codes(period):
            if get_kline_bar_count(code, period) >= normalized[period]:
                if code not in code_period_ready:
                    code_period_ready[code] = set()
                code_period_ready[code].add(period)
    
    count = 0
    for code, ready_periods in code_period_ready.items():
        if ready_periods >= set(normalized.keys()):
            count += 1
    return count


def list_ready_price_history_candidates(
    requirements: dict[str, int],
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
) -> dict:
    from backend.kline_parquet import list_kline_codes, get_kline_bar_count
    
    normalized = {str(period): int(min_bars) for period, min_bars in requirements.items() if int(min_bars) > 0}
    if not normalized:
        return {"items": [], "total": 0, "page": int(page), "page_size": int(page_size)}

    code_period_ready: dict[str, set[str]] = {}
    for period in normalized:
        for code in list_kline_codes(period):
            if get_kline_bar_count(code, period) >= normalized[period]:
                if code not in code_period_ready:
                    code_period_ready[code] = set()
                code_period_ready[code].add(period)
    
    ready_codes = [code for code, ready_periods in code_period_ready.items() if ready_periods >= set(normalized.keys())]

    keyword = str(keyword or "").strip()
    item_cache: dict[str, Optional[dict]] = {}
    if keyword:
        keyword_lower = keyword.lower()
        filtered_codes = []
        for code in ready_codes:
            item = get_stock_pool_item(code)
            item_cache[code] = item
            name = str((item or {}).get("name") or code)
            if keyword in code or keyword_lower in name.lower():
                filtered_codes.append(code)
        ready_codes = filtered_codes
    
    ready_codes = sorted(ready_codes)
    total = len(ready_codes)
    
    page = max(int(page), 1)
    page_size = max(min(int(page_size), 200), 1)
    start = (page - 1) * page_size
    end = start + page_size
    page_codes = ready_codes[start:end]
    
    items = []
    for code in page_codes:
        item = item_cache.get(code)
        if item is None and code not in item_cache:
            item = get_stock_pool_item(code)
        if item:
            items.append({
                "code": code,
                "name": item.get("name", code),
                "market": int(item.get("market", 1)),
            })
        else:
            items.append({"code": code, "name": code, "market": 1})
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _normalize_download_source(value) -> Optional[str]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, str):
        raw_parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_parts = list(value)
    else:
        raw_parts = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_parts:
        tag = str(item or "").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return ",".join(normalized) if normalized else None


def _download_source_tags(value) -> set[str]:
    normalized = _normalize_download_source(value)
    if not normalized:
        return set()
    return {item for item in normalized.split(",") if item}


def _merge_download_source(value, *tags: str) -> Optional[str]:
    merged = _download_source_tags(value)
    for tag in tags:
        normalized_tag = str(tag or "").strip().lower()
        if normalized_tag:
            merged.add(normalized_tag)
    return ",".join(sorted(merged)) if merged else None


def _remove_download_source(value, tag: str) -> Optional[str]:
    normalized_tag = str(tag or "").strip().lower()
    remaining = {item for item in _download_source_tags(value) if item != normalized_tag}
    return ",".join(sorted(remaining)) if remaining else None


def _has_download_source(value, tag: str) -> bool:
    return str(tag or "").strip().lower() in _download_source_tags(value)


def upsert_stock_pool(rows: Iterable[dict]) -> int:
    normalized_map = {}
    now_text = _now_text()

    def nullable_bool_int(item: dict, key: str) -> Optional[int]:
        if key not in item or item.get(key) is None:
            return None
        return int(bool(item.get(key)))

    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code:
            continue
        normalized_map[code] = {
            "code": code,
            "name": str(item.get("name", "") or code),
            "market": int(item.get("market", 1) or 1),
            "security_type": str(item.get("security_type", "stock") or "stock"),
            "total_mv": None if item.get("total_mv") in ("", None) else float(item.get("total_mv")),
            "circ_mv": None if item.get("circ_mv") in ("", None) else float(item.get("circ_mv")),
            "price": None if item.get("price") in ("", None) else float(item.get("price")),
            "change_pct": None if item.get("change_pct") in ("", None) else float(item.get("change_pct")),
            "prev_close": None if item.get("prev_close") in ("", None) else float(item.get("prev_close")),
            "is_st": nullable_bool_int(item, "is_st"),
            "is_delisted": nullable_bool_int(item, "is_delisted"),
            "is_low_mv": nullable_bool_int(item, "is_low_mv"),
            "ma144_passed": nullable_bool_int(item, "ma144_passed"),
            "scan_eligible": nullable_bool_int(item, "scan_eligible"),
            "kline_downloaded": nullable_bool_int(item, "kline_downloaded"),
            "download_source": _normalize_download_source(item.get("download_source")),
            "industry": _normalize_optional_text(item.get("industry")),
        }
    
    if not normalized_map:
        return 0
    
    normalized_rows = [
        (
            v["code"], v["name"], v["market"], v["security_type"],
            v["total_mv"], v["circ_mv"], v["price"], v["change_pct"], v["prev_close"],
            v["is_st"], v["is_delisted"], v["is_low_mv"], v["ma144_passed"],
            v["scan_eligible"], v["kline_downloaded"], v["download_source"], v["industry"],
            now_text,
            v["is_st"], v["is_delisted"], v["is_low_mv"], v["ma144_passed"],
            v["scan_eligible"], v["kline_downloaded"],
        )
        for v in normalized_map.values()
    ]
    
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO stock_pool
            (code, name, market, security_type, total_mv, circ_mv, price, change_pct, prev_close,
             is_st, is_delisted, is_low_mv, ma144_passed, scan_eligible, kline_downloaded, download_source, industry, updated_at)
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE(?, 0), COALESCE(?, 0), COALESCE(?, 0),
                COALESCE(?, 0), COALESCE(?, 1), COALESCE(?, 0),
                ?, ?, ?
            )
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                security_type = excluded.security_type,
                total_mv = COALESCE(excluded.total_mv, stock_pool.total_mv),
                circ_mv = COALESCE(excluded.circ_mv, stock_pool.circ_mv),
                price = COALESCE(excluded.price, stock_pool.price),
                change_pct = COALESCE(excluded.change_pct, stock_pool.change_pct),
                prev_close = COALESCE(excluded.prev_close, stock_pool.prev_close),
                is_st = COALESCE(?, stock_pool.is_st),
                is_delisted = COALESCE(?, stock_pool.is_delisted),
                is_low_mv = COALESCE(?, stock_pool.is_low_mv),
                ma144_passed = COALESCE(?, stock_pool.ma144_passed),
                scan_eligible = COALESCE(?, stock_pool.scan_eligible),
                kline_downloaded = COALESCE(?, stock_pool.kline_downloaded),
                download_source = COALESCE(excluded.download_source, stock_pool.download_source),
                industry = COALESCE(excluded.industry, stock_pool.industry),
                updated_at = excluded.updated_at
            """,
            normalized_rows,
        )
    return len(normalized_rows)


def update_stock_pool_flags(
    code: str,
    is_st: Optional[int] = None,
    is_delisted: Optional[int] = None,
    is_low_mv: Optional[int] = None,
    ma144_passed: Optional[int] = None,
    scan_eligible: Optional[int] = None,
    kline_downloaded: Optional[int] = None,
    download_source: Optional[str] = None,
    kline_periods: Optional[str] = None,
    kline_time_span: Optional[str] = None,
) -> bool:
    code = str(code).strip().zfill(6)
    updates = []
    params = []
    
    if is_st is not None:
        updates.append("is_st = ?")
        params.append(int(is_st))
    if is_delisted is not None:
        updates.append("is_delisted = ?")
        params.append(int(is_delisted))
    if is_low_mv is not None:
        updates.append("is_low_mv = ?")
        params.append(int(is_low_mv))
    if ma144_passed is not None:
        updates.append("ma144_passed = ?")
        params.append(int(ma144_passed))
    if scan_eligible is not None:
        updates.append("scan_eligible = ?")
        params.append(int(scan_eligible))
    if kline_downloaded is not None:
        updates.append("kline_downloaded = ?")
        params.append(int(kline_downloaded))
    if download_source is not None:
        updates.append("download_source = ?")
        params.append(download_source)
    if kline_periods is not None:
        updates.append("kline_periods = ?")
        params.append(kline_periods)
    if kline_time_span is not None:
        updates.append("kline_time_span = ?")
        params.append(kline_time_span)
    
    if not updates:
        return False
    
    updates.append("updated_at = ?")
    params.append(_now_text())
    params.append(code)

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE stock_pool SET {', '.join(updates)} WHERE code = ?",
            params,
        )
        return cursor.rowcount > 0


def refresh_kline_metadata(code: str) -> bool:
    """刷新股票的K线周期元数据（保存了哪些周期、每个周期的数据时间范围）"""
    import json
    from backend.kline_parquet import get_kline_sync_state
    from backend.config import DOWNLOADABLE_KLINE_PERIODS

    code = str(code).strip().zfill(6)
    periods_found = []
    time_span_map = {}

    for period in DOWNLOADABLE_KLINE_PERIODS:
        state = get_kline_sync_state(code, period)
        if state and int(state.get("bar_count") or 0) > 0:
            periods_found.append(period)
            first_bar = state.get("first_bar_time")
            last_bar = state.get("last_bar_time")
            if first_bar and last_bar:
                time_span_map[period] = {
                    "first_bar": first_bar,
                    "last_bar": last_bar,
                    "bar_count": int(state.get("bar_count", 0)),
                }

    kline_periods = json.dumps(periods_found, ensure_ascii=False)
    kline_time_span = json.dumps(time_span_map, ensure_ascii=False)
    kline_downloaded = 1 if periods_found else 0

    return update_stock_pool_flags(
        code=code,
        kline_downloaded=kline_downloaded,
        kline_periods=kline_periods,
        kline_time_span=kline_time_span,
    )


def update_kline_metadata_batch(rows: Iterable[dict]) -> int:
    normalized_rows = []
    now_text = _now_text()
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code:
            continue
        normalized_rows.append(
            (
                int(item.get("kline_downloaded", 0) or 0),
                str(item.get("kline_periods", "[]") or "[]"),
                str(item.get("kline_time_span", "{}") or "{}"),
                None if item.get("ma144_passed") is None else int(bool(item.get("ma144_passed"))),
                now_text,
                code,
            )
        )

    if not normalized_rows:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE stock_pool
            SET kline_downloaded = ?,
                kline_periods = ?,
                kline_time_span = ?,
                ma144_passed = COALESCE(?, ma144_passed),
                updated_at = ?
            WHERE code = ?
            """,
            normalized_rows,
        )
    return len(normalized_rows)


def update_ma144_flags_batch(rows: Iterable[dict]) -> int:
    normalized_rows = []
    now_text = _now_text()
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code or item.get("ma144_passed") is None:
            continue
        normalized_rows.append((int(bool(item.get("ma144_passed"))), now_text, code))

    if not normalized_rows:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE stock_pool
            SET ma144_passed = ?,
                updated_at = ?
            WHERE code = ?
            """,
            normalized_rows,
        )
    return len(normalized_rows)


def update_stock_pool_screening_flags_batch(rows: Iterable[dict]) -> int:
    """每周五全量复检用：批量刷新股票池的名称/总市值/ST/退市/低市值标记。

    只更新快照里有有效市值数据的行（快照缺失的股票保留旧状态，避免误伤）。
    """
    now_text = _now_text()
    normalized_rows = []
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        total_mv = item.get("total_mv")
        name = str(item.get("name") or "").strip()
        if not code or not name or total_mv is None:
            continue
        normalized_rows.append(
            (
                name,
                float(total_mv),
                int(bool(item.get("is_st"))),
                int(bool(item.get("is_delisted"))),
                int(bool(item.get("is_low_mv"))),
                now_text,
                code,
            )
        )

    if not normalized_rows:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE stock_pool
            SET name = ?, total_mv = ?, is_st = ?, is_delisted = ?, is_low_mv = ?, updated_at = ?
            WHERE code = ?
            """,
            normalized_rows,
        )
    return len(normalized_rows)


def recalculate_scan_eligible(code: Optional[str] = None) -> int:
    with get_connection() as conn:
        if code:
            cursor = conn.execute(
                """
                UPDATE stock_pool
                SET scan_eligible = CASE
                    WHEN kline_downloaded = 1 AND is_st = 0 AND is_delisted = 0 AND is_low_mv = 0 AND ma144_passed = 1
                    THEN 1 ELSE 0
                END,
                updated_at = ?
                WHERE code = ?
                """,
                (_now_text(), code),
            )
            return cursor.rowcount
        else:
            cursor = conn.execute(
                """
                UPDATE stock_pool
                SET scan_eligible = CASE
                    WHEN kline_downloaded = 1 AND is_st = 0 AND is_delisted = 0 AND is_low_mv = 0 AND ma144_passed = 1
                    THEN 1 ELSE 0
                END,
                updated_at = ?
                """,
                (_now_text(),),
            )
            return cursor.rowcount


def list_stock_pool(
    scan_eligible_only: bool = False,
    security_type: Optional[str] = None,
    kline_downloaded_only: bool = False,
) -> list[dict]:
    conditions = []
    params: list = []
    
    if scan_eligible_only:
        conditions.append("scan_eligible = 1")
    if security_type:
        conditions.append("security_type = ?")
        params.append(security_type)
    if kline_downloaded_only:
        conditions.append("kline_downloaded = 1")
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM stock_pool
        {where_clause}
        ORDER BY code ASC
    """
    
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_stock_pool_item(code: str) -> Optional[dict]:
    code = str(code).strip().zfill(6)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM stock_pool WHERE code = ?",
            (code,),
        ).fetchone()
    return dict(row) if row else None


def search_stock_pool(keyword: str, limit: int = 20, kline_downloaded_only: bool = True) -> list[dict]:
    keyword = str(keyword or "").strip()
    if not keyword:
        return []

    like = f"%{keyword}%"
    prefix = f"{keyword}%"
    conditions = ["(code LIKE ? OR name LIKE ?)"]
    params: list = [like, like]
    if kline_downloaded_only:
        conditions.insert(0, "kline_downloaded = 1")
    sql = f"""
        SELECT code, name, market, security_type, price, change_pct
        FROM stock_pool
        WHERE {' AND '.join(conditions)}
        ORDER BY
            CASE
                WHEN code = ? THEN 0
                WHEN name = ? THEN 1
                WHEN code LIKE ? THEN 2
                WHEN name LIKE ? THEN 3
                ELSE 4
            END,
            code ASC
        LIMIT ?
    """
    params.extend([keyword.zfill(6) if keyword.isdigit() else keyword, keyword, prefix, prefix, int(limit)])
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_stock_pool(
    scan_eligible_only: bool = False,
    security_type: Optional[str] = None,
) -> int:
    conditions = []
    params: list = []
    
    if scan_eligible_only:
        conditions.append("scan_eligible = 1")
    if security_type:
        conditions.append("security_type = ?")
        params.append(security_type)
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(1) AS cnt FROM stock_pool {where_clause}",
            params,
        ).fetchone()
    return int(row["cnt"] or 0)


def get_stock_pool_stats() -> dict:
    import json
    from statistics import median
    from backend.config import DOWNLOADABLE_KLINE_PERIODS

    def period_bar_count_to_days(period: str, bar_count: int) -> int:
        if bar_count <= 0:
            return 0
        bars_per_day = {
            "1min": 240,
            "5min": 48,
            "15min": 16,
            "30min": 8,
            "60min": 4,
            "daily": 1,
            "weekly": 1,
            "monthly": 1,
        }.get(period, 1)
        return max(1, (bar_count + bars_per_day - 1) // bars_per_day)

    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool").fetchone()["cnt"]
        eligible = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE scan_eligible = 1").fetchone()["cnt"]
        st_count = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE is_st = 1").fetchone()["cnt"]
        delisted_count = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE is_delisted = 1").fetchone()["cnt"]
        low_mv_count = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE is_low_mv = 1").fetchone()["cnt"]
        ma144_failed = conn.execute(
            """
            SELECT COUNT(1) AS cnt
            FROM stock_pool
            WHERE ma144_passed = 0
              AND (
                security_type != 'stock'
                OR (is_st = 0 AND is_delisted = 0 AND is_low_mv = 0)
              )
            """
        ).fetchone()["cnt"]
        kline_ready = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE kline_downloaded = 1").fetchone()["cnt"]
        stocks = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE security_type = 'stock'").fetchone()["cnt"]
        etfs = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE security_type = 'etf'").fetchone()["cnt"]
        indexes = conn.execute("SELECT COUNT(1) AS cnt FROM stock_pool WHERE security_type = 'index'").fetchone()["cnt"]

        downloaded_filtered = conn.execute(
            """
            SELECT COUNT(1) AS cnt
            FROM stock_pool
            WHERE kline_downloaded = 1
              AND (
                security_type != 'stock'
                OR (is_st = 0 AND is_delisted = 0 AND is_low_mv = 0)
              )
            """
        ).fetchone()["cnt"]

        scan_eligible_realtime = conn.execute(
            """
            SELECT COUNT(1) AS cnt
            FROM stock_pool
            WHERE kline_downloaded = 1
              AND (
                security_type != 'stock'
                OR (is_st = 0 AND is_delisted = 0 AND is_low_mv = 0)
              )
              AND ma144_passed = 1
            """
        ).fetchone()["cnt"]

        # 统计各周期K线存量
        kline_counts = {}
        rows = conn.execute(
            "SELECT kline_periods FROM stock_pool WHERE kline_periods IS NOT NULL AND kline_periods != ''"
        ).fetchall()
        for period in DOWNLOADABLE_KLINE_PERIODS:
            kline_counts[period] = 0
        for row in rows:
            try:
                periods_list = json.loads(row["kline_periods"])
                for p in periods_list:
                    if p in kline_counts:
                        kline_counts[p] += 1
            except (json.JSONDecodeError, TypeError):
                pass

        # 统计K线最新日期和各周期历史深度
        kline_latest_date = ""
        kline_period_day_samples = {period: [] for period in DOWNLOADABLE_KLINE_PERIODS}
        try:
            rows_date = conn.execute(
                """
                SELECT kline_time_span FROM stock_pool
                WHERE kline_downloaded = 1 AND kline_time_span IS NOT NULL AND kline_time_span != ''
                """
            ).fetchall()
            for row_date in rows_date:
                span_data = json.loads(row_date["kline_time_span"])
                if not isinstance(span_data, dict):
                    continue
                daily_span = span_data.get("daily", {})
                daily_last_bar = daily_span.get("last_bar", "") if isinstance(daily_span, dict) else ""
                if (
                    daily_last_bar
                    and _is_plausible_bar_date_text(daily_last_bar)
                    and daily_last_bar > kline_latest_date
                ):
                    kline_latest_date = daily_last_bar
                for period, period_span in span_data.items():
                    if period not in kline_period_day_samples or not isinstance(period_span, dict):
                        continue
                    bar_count = int(period_span.get("bar_count") or 0)
                    day_count = period_bar_count_to_days(period, bar_count)
                    if day_count > 0:
                        kline_period_day_samples[period].append(day_count)
        except Exception:
            pass
        kline_period_days = {
            period: int(round(median(samples))) if samples else 0
            for period, samples in kline_period_day_samples.items()
        }

    return {
        "total": int(total or 0),
        "scan_eligible": int(scan_eligible_realtime or 0),
        "is_st": int(st_count or 0),
        "is_delisted": int(delisted_count or 0),
        "is_low_mv": int(low_mv_count or 0),
        "ma144_failed": int(ma144_failed or 0),
        "kline_downloaded": int(downloaded_filtered or 0),
        "stock_count": int(stocks or 0),
        "etf_count": int(etfs or 0),
        "index_count": int(indexes or 0),
        "kline_counts": kline_counts,
        "kline_period_days": kline_period_days,
        "kline_latest_date": kline_latest_date,
        "kline_downloaded_raw": int(kline_ready or 0),
        "scan_eligible_cached": int(eligible or 0),
    }



def replace_a_share_spot_snapshot(rows: Iterable[dict]) -> int:
    return upsert_stock_pool(rows)


def list_a_share_spot_snapshot() -> list[dict]:
    return list_stock_pool()


def replace_rule_download_universe(rows: Iterable[dict]) -> int:
    normalized = []
    row_codes: list[str] = []
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code:
            continue
        row_codes.append(code)
        normalized.append({
            **item,
            "code": code,
            "download_source": _merge_download_source(item.get("download_source"), "rule"),
            "kline_downloaded": 1,
            "scan_eligible": item.get("scan_eligible"),
            "ma144_passed": item.get("ma144_passed"),
        })
    changed = upsert_stock_pool(normalized)
    if row_codes:
        placeholders = ", ".join("?" for _ in row_codes)
        params = [_now_text(), *row_codes]
        with get_connection() as conn:
            conn.execute(
                f"""
                UPDATE stock_pool
                SET download_source = CASE
                        WHEN download_source IS NULL OR TRIM(download_source) = '' THEN NULL
                        ELSE REPLACE(REPLACE(',' || download_source || ',', ',rule,', ','), ',,', ',')
                    END,
                    scan_eligible = CASE
                        WHEN security_type = 'stock' AND (is_st = 1 OR is_delisted = 1 OR is_low_mv = 1 OR ma144_passed = 0) THEN 0
                        ELSE scan_eligible
                    END,
                    updated_at = ?
                WHERE code NOT IN ({placeholders}) AND instr(',' || COALESCE(download_source, '') || ',', ',rule,') > 0
                """,
                params,
            )
            conn.execute(
                """
                UPDATE stock_pool
                SET download_source = NULL
                WHERE download_source IN ('', ',')
                """
            )
    recalculate_scan_eligible()
    return changed


def upsert_manual_download_universe(rows: Iterable[dict]) -> int:
    normalized = []
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code:
            continue
        normalized.append({
            **item,
            "code": code,
            "download_source": _merge_download_source(item.get("download_source"), "manual"),
            "kline_downloaded": 1,
            "scan_eligible": item.get("scan_eligible"),
        })
    return upsert_stock_pool(normalized)


def list_download_universe(rule_only: bool = False) -> list[dict]:
    if rule_only:
        return [
            item for item in list_stock_pool(kline_downloaded_only=True)
            if _has_download_source(item.get("download_source"), "rule")
        ]
    return [
        item for item in list_stock_pool(kline_downloaded_only=True)
        if _download_source_tags(item.get("download_source"))
    ]


def replace_download_source_universe(rows: Iterable[dict]) -> int:
    normalized = []
    row_codes: list[str] = []
    for item in rows:
        code = str(item.get("code", "")).strip().zfill(6)
        if not code:
            continue
        row_codes.append(code)
        normalized_item = {
            **item,
            "code": code,
            "download_source": _merge_download_source(item.get("download_source"), "base"),
        }
        for key in ("kline_downloaded", "kline_periods", "kline_time_span", "ma144_passed", "scan_eligible"):
            normalized_item.pop(key, None)
        normalized.append(normalized_item)
    changed = upsert_stock_pool(normalized)
    if row_codes:
        placeholders = ", ".join("?" for _ in row_codes)
        params = [_now_text(), *row_codes]
        with get_connection() as conn:
            conn.execute(
                f"""
                UPDATE stock_pool
                SET download_source = CASE
                        WHEN download_source IS NULL OR TRIM(download_source) = '' THEN NULL
                        ELSE REPLACE(REPLACE(',' || download_source || ',', ',base,', ','), ',,', ',')
                    END,
                    updated_at = ?
                WHERE code NOT IN ({placeholders}) AND instr(',' || COALESCE(download_source, '') || ',', ',base,') > 0
                """,
                params,
            )
            conn.execute(
                """
                UPDATE stock_pool
                SET download_source = NULL
                WHERE download_source IN ('', ',')
                """
            )
    recalculate_scan_eligible()
    return changed


def list_download_source_universe() -> list[dict]:
    return [
        item for item in list_stock_pool()
        if _has_download_source(item.get("download_source"), "base")
    ]


def save_backtest_result(
    strategy_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    final_capital: float,
    total_return: float = 0,
    max_drawdown: float = 0,
    sharpe_ratio: Optional[float] = None,
    win_rate: Optional[float] = None,
    total_trades: int = 0,
    winning_trades: int = 0,
    params: Optional[dict] = None,
    owner_username: Optional[str] = None,
) -> int:
    now_text = _now_text()
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO backtest_results
            (strategy_name, owner_username, symbol, start_date, end_date, initial_capital, final_capital,
             total_return, max_drawdown, sharpe_ratio, win_rate, total_trades, winning_trades, params, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_name,
                owner,
                symbol,
                start_date,
                end_date,
                initial_capital,
                final_capital,
                total_return,
                max_drawdown,
                sharpe_ratio,
                win_rate,
                total_trades,
                winning_trades,
                json.dumps(params, ensure_ascii=False) if params else None,
                now_text,
            ),
        )
        return int(cursor.lastrowid)


def list_backtest_results(
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list = []
    if strategy_name:
        conditions.append("strategy_name = ?")
        params.append(strategy_name)
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol)
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM backtest_results
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
    """
    params.append(limit)
    
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def save_full_backtest_run(
    strategy_name: str,
    period: str,
    start_date: str,
    end_date: str,
    target_count: int,
    success_count: int,
    failed_count: int,
    profitable_count: int,
    loss_count: int,
    win_rate: float,
    cumulative_return: float,
    average_return: float,
    max_drawdown: float,
    max_gain: float,
    payload: Optional[dict] = None,
    owner_username: Optional[str] = None,
) -> int:
    now_text = _now_text()
    owner = _normalize_owner_username(owner_username)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO full_backtest_runs
            (strategy_name, owner_username, period, start_date, end_date, target_count, success_count, failed_count,
             profitable_count, loss_count, win_rate, cumulative_return, average_return, max_drawdown,
             max_gain, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_name,
                owner,
                period,
                start_date,
                end_date,
                int(target_count),
                int(success_count),
                int(failed_count),
                int(profitable_count),
                int(loss_count),
                float(win_rate),
                float(cumulative_return),
                float(average_return),
                float(max_drawdown),
                float(max_gain),
                json.dumps(payload, ensure_ascii=False) if payload else None,
                now_text,
            ),
        )
        return int(cursor.lastrowid)


def list_full_backtest_runs(
    strategy_name: Optional[str] = None,
    limit: int = 20,
    owner_username: Optional[str] = None,
) -> list[dict]:
    conditions = []
    params: list = []
    if strategy_name:
        conditions.append("strategy_name = ?")
        params.append(strategy_name)
    owner = _normalize_owner_username(owner_username)
    if owner == "vk":
        conditions.append("(owner_username = ? OR owner_username IS NULL OR TRIM(owner_username) = '')")
        params.append(owner)
    elif owner:
        conditions.append("owner_username = ?")
        params.append(owner)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT *
        FROM full_backtest_runs
        {where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """
    params.append(int(limit))

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"]) if item.get("payload") else None
        except Exception:
            item["payload"] = None
        results.append(item)
    return results


def get_full_backtest_run(run_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM full_backtest_runs WHERE id = ?",
            (int(run_id),),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item["payload"]) if item.get("payload") else None
    except Exception:
        item["payload"] = None
    return item


def delete_full_backtest_run(run_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM full_backtest_runs WHERE id = ?",
            (int(run_id),),
        )
        return int(cursor.rowcount or 0) > 0


def get_auth_user(username: str) -> Optional[dict]:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM auth_users WHERE username = ?",
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def upsert_auth_user(
    username: str,
    password_hash: str,
    role: str = "user",
    expires_at: Optional[str] = None,
    status: str = "active",
) -> dict:
    normalized = str(username or "").strip().lower()
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_users (username, password_hash, role, expires_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                role = excluded.role,
                expires_at = excluded.expires_at,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (normalized, password_hash, role, expires_at, status, now_text, now_text),
        )
    return get_auth_user(normalized) or {}


def create_auth_session(token_hash: str, username: str, expires_at: str, now_text: Optional[str] = None):
    now_text = now_text or _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (token_hash, username, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, str(username or "").strip().lower(), now_text, expires_at, now_text),
        )


def get_auth_session(token_hash: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE token_hash = ?",
            (str(token_hash or ""),),
        ).fetchone()
    return dict(row) if row else None


def touch_auth_session(token_hash: str, last_seen_at: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (last_seen_at, str(token_hash or "")),
        )


def delete_auth_session(token_hash: str):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?",
            (str(token_hash or ""),),
        )


def create_auth_captcha(captcha_id: str, code_hash: str, expires_at: str):
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_captchas WHERE expires_at < ?", (now_text,))
        conn.execute(
            """
            INSERT INTO auth_captchas (captcha_id, code_hash, created_at, expires_at, consumed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (captcha_id, code_hash, now_text, expires_at),
        )


def consume_auth_captcha(captcha_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM auth_captchas WHERE captcha_id = ? AND consumed = 0",
            (str(captcha_id or ""),),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE auth_captchas SET consumed = 1 WHERE captcha_id = ?",
            (str(captcha_id or ""),),
        )
    return dict(row)


def create_payment_order(
    order_id: str,
    plan_key: str,
    plan_label: str,
    amount: float,
    duration_days: int,
    status: str = "pending",
    provider: str = "alipay",
) -> dict:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO payment_orders
            (id, plan_key, plan_label, amount, duration_days, status, provider, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, plan_key, plan_label, float(amount), int(duration_days), status, provider, now_text),
        )
    return get_payment_order(order_id) or {}


def get_payment_order(order_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM payment_orders WHERE id = ?",
            (str(order_id or ""),),
        ).fetchone()
    return dict(row) if row else None


def mark_payment_order_paid(
    order_id: str,
    username: str,
    password_plain: str,
    expires_at: str,
    provider_trade_no: str = "",
    paid_at: Optional[str] = None,
) -> Optional[dict]:
    paid_at = paid_at or _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE payment_orders
            SET status = 'paid',
                provider_trade_no = ?,
                username = ?,
                password_plain = ?,
                expires_at = ?,
                paid_at = ?
            WHERE id = ?
            """,
            (provider_trade_no, username, password_plain, expires_at, paid_at, order_id),
        )
    return get_payment_order(order_id)


def get_position(account_id: str, symbol: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM positions WHERE account_id = ? AND symbol = ?
            """,
            (account_id, symbol),
        ).fetchone()
    return dict(row) if row else None


def list_positions(account_id: str = "default") -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM positions WHERE account_id = ? ORDER BY symbol ASC
            """,
            (account_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_position(
    account_id: str,
    symbol: str,
    quantity: float,
    avg_cost: float,
    current_price: Optional[float] = None,
    market_value: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    unrealized_pnl_pct: Optional[float] = None,
) -> dict:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO positions (account_id, symbol, quantity, avg_cost, current_price, market_value, unrealized_pnl, unrealized_pnl_pct, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, symbol) DO UPDATE SET
                quantity = excluded.quantity,
                avg_cost = excluded.avg_cost,
                current_price = excluded.current_price,
                market_value = excluded.market_value,
                unrealized_pnl = excluded.unrealized_pnl,
                unrealized_pnl_pct = excluded.unrealized_pnl_pct,
                updated_at = excluded.updated_at
            """,
            (account_id, symbol, quantity, avg_cost, current_price, market_value, unrealized_pnl, unrealized_pnl_pct, now_text),
        )
    return get_position(account_id, symbol) or {}


def delete_position(account_id: str, symbol: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM positions WHERE account_id = ? AND symbol = ?",
            (account_id, symbol),
        )
        return cursor.rowcount > 0


def save_trade(
    account_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    amount: float,
    commission: float = 0,
    pnl: Optional[float] = None,
    strategy: Optional[str] = None,
    signal_id: Optional[int] = None,
    executed_at: Optional[str] = None,
) -> int:
    now_text = _now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades
            (account_id, symbol, side, quantity, price, amount, commission, pnl, strategy, signal_id, executed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                symbol,
                side,
                quantity,
                price,
                amount,
                commission,
                pnl,
                strategy,
                signal_id,
                executed_at or now_text,
                now_text,
            ),
        )
        return int(cursor.lastrowid)


def list_trades(
    account_id: str = "default",
    symbol: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    conditions = ["account_id = ?"]
    params: list = [account_id]
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol)
    
    sql = f"""
        SELECT * FROM trades
        WHERE {' AND '.join(conditions)}
        ORDER BY executed_at DESC
        LIMIT ?
    """
    params.append(limit)
    
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_strategy_param(strategy_name: str, param_key: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM strategy_params WHERE strategy_name = ? AND param_key = ?
            """,
            (strategy_name, param_key),
        ).fetchone()
    return dict(row) if row else None


def list_strategy_params(strategy_name: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM strategy_params WHERE strategy_name = ? ORDER BY param_key ASC
            """,
            (strategy_name,),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_strategy_param(
    strategy_name: str,
    param_key: str,
    param_value: str,
    param_type: str = "string",
    description: Optional[str] = None,
) -> dict:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO strategy_params (strategy_name, param_key, param_value, param_type, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy_name, param_key) DO UPDATE SET
                param_value = excluded.param_value,
                param_type = excluded.param_type,
                description = excluded.description,
                updated_at = excluded.updated_at
            """,
            (strategy_name, param_key, param_value, param_type, description, now_text),
        )
    return get_strategy_param(strategy_name, param_key) or {}


def delete_strategy_param(strategy_name: str, param_key: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM strategy_params WHERE strategy_name = ? AND param_key = ?",
            (strategy_name, param_key),
        )
        return cursor.rowcount > 0


def get_auth_user(username: str) -> Optional[dict]:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT username, password_hash, role, expires_at, status, must_change_credentials,
                   created_at, updated_at, last_login_at
            FROM auth_users
            WHERE username = ?
            """,
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def list_auth_users_for_admin() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.username,
                   u.role,
                   u.expires_at,
                   u.status,
                   u.must_change_credentials,
                   u.created_at,
                   u.updated_at,
                   COALESCE(u.last_login_at, MAX(s.last_seen_at), MAX(s.created_at)) AS last_login_at
            FROM auth_users u
            LEFT JOIN auth_sessions s ON s.username = u.username
            GROUP BY u.username, u.role, u.expires_at, u.status, u.must_change_credentials,
                     u.created_at, u.updated_at, u.last_login_at
            ORDER BY
                CASE WHEN u.username = 'vk' THEN 0 ELSE 1 END,
                u.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_auth_user_admin(
    username: str,
    expires_at: Optional[str],
    status: str,
    new_username: Optional[str] = None,
    password_hash: Optional[str] = None,
) -> Optional[dict]:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return None
    new_normalized = str(new_username or normalized).strip().lower()
    if not new_normalized:
        return None
    now_text = _now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE auth_users
            SET username = ?,
                password_hash = COALESCE(?, password_hash),
                expires_at = ?,
                status = ?,
                updated_at = ?
            WHERE username = ?
            """,
            (new_normalized, password_hash, expires_at, status, now_text, normalized),
        )
        if int(cursor.rowcount or 0) <= 0:
            return None
        if new_normalized != normalized:
            conn.execute("UPDATE auth_sessions SET username = ? WHERE username = ?", (new_normalized, normalized))
            conn.execute("UPDATE payment_orders SET buyer_username = ? WHERE buyer_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE payment_orders SET username = ? WHERE username = ?", (new_normalized, normalized))
            conn.execute("UPDATE scan_settings SET strategy_owner_username = ? WHERE strategy_owner_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE scan_runs SET owner_username = ? WHERE owner_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE scan_signals SET owner_username = ? WHERE owner_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE backtest_results SET owner_username = ? WHERE owner_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE full_backtest_runs SET owner_username = ? WHERE owner_username = ?", (new_normalized, normalized))
            conn.execute("UPDATE watchlist SET owner_username = ? WHERE owner_username = ?", (new_normalized, normalized))
        if status != "active":
            conn.execute("DELETE FROM auth_sessions WHERE username = ?", (new_normalized,))
    return get_auth_user(new_normalized)


def mark_auth_user_login(username: str, login_at: Optional[str] = None) -> bool:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return False
    login_at = login_at or _now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE auth_users
            SET last_login_at = ?,
                updated_at = ?
            WHERE username = ?
            """,
            (login_at, login_at, normalized),
        )
        return int(cursor.rowcount or 0) > 0


def create_auth_user_if_missing(
    username: str,
    password_hash: str,
    role: str = "user",
    expires_at: Optional[str] = None,
) -> bool:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return False
    now_text = _now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO auth_users (username, password_hash, role, expires_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (normalized, password_hash, role or "user", expires_at, now_text, now_text),
        )
        return int(cursor.rowcount or 0) > 0


def create_auth_user(
    username: str,
    password_hash: str,
    role: str = "user",
    expires_at: Optional[str] = None,
    must_change_credentials: bool = False,
) -> dict:
    normalized = str(username or "").strip().lower()
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_users
            (username, password_hash, role, expires_at, status, must_change_credentials, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (normalized, password_hash, role or "user", expires_at, 1 if must_change_credentials else 0, now_text, now_text),
        )
    return get_auth_user(normalized) or {}


def update_auth_user_vip(
    username: str,
    role: str,
    expires_at: str,
    must_change_credentials: bool,
) -> Optional[dict]:
    normalized = str(username or "").strip().lower()
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE auth_users
            SET role = ?,
                expires_at = ?,
                status = 'active',
                must_change_credentials = ?,
                updated_at = ?
            WHERE username = ?
            """,
            (role or "vip", expires_at, 1 if must_change_credentials else 0, now_text, normalized),
        )
    return get_auth_user(normalized)


def update_auth_user_credentials(
    old_username: str,
    new_username: str,
    password_hash: str,
) -> Optional[dict]:
    old_normalized = str(old_username or "").strip().lower()
    new_normalized = str(new_username or "").strip().lower()
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE auth_users
            SET username = ?,
                password_hash = ?,
                must_change_credentials = 0,
                updated_at = ?
            WHERE username = ?
            """,
            (new_normalized, password_hash, now_text, old_normalized),
        )
        conn.execute(
            "UPDATE auth_sessions SET username = ? WHERE username = ?",
            (new_normalized, old_normalized),
        )
        conn.execute(
            "UPDATE payment_orders SET buyer_username = ? WHERE buyer_username = ?",
            (new_normalized, old_normalized),
        )
        conn.execute(
            "UPDATE payment_orders SET username = ? WHERE username = ?",
            (new_normalized, old_normalized),
        )
        conn.execute(
            "UPDATE watchlist SET owner_username = ? WHERE owner_username = ?",
            (new_normalized, old_normalized),
        )
    return get_auth_user(new_normalized)


def create_auth_session(token_hash: str, username: str, expires_at: str) -> dict:
    normalized = str(username or "").strip().lower()
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (token_hash, username, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, normalized, now_text, expires_at, now_text),
        )
    return {
        "token_hash": token_hash,
        "username": normalized,
        "created_at": now_text,
        "expires_at": expires_at,
        "last_seen_at": now_text,
    }


def get_auth_session(token_hash: str) -> Optional[dict]:
    now_text = _now_text()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT s.token_hash, s.username, s.created_at, s.expires_at, s.last_seen_at,
                   u.role
            FROM auth_sessions s
            JOIN auth_users u ON u.username = s.username
            WHERE s.token_hash = ?
              AND s.expires_at > ?
              AND u.status = 'active'
              AND (u.expires_at IS NULL OR u.expires_at > ?)
            """,
            (token_hash, now_text, now_text),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE auth_sessions
                SET last_seen_at = ?
                WHERE token_hash = ?
                """,
                (now_text, token_hash),
            )
    return dict(row) if row else None


def has_active_auth_session_for_user(username: str) -> bool:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return False
    now_text = _now_text()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 AS active
            FROM auth_sessions
            JOIN auth_users ON auth_users.username = auth_sessions.username
            WHERE auth_sessions.username = ?
              AND auth_sessions.expires_at > ?
              AND auth_users.status = 'active'
              AND (auth_users.expires_at IS NULL OR auth_users.expires_at > ?)
            LIMIT 1
            """,
            (normalized, now_text, now_text),
        ).fetchone()
    return bool(row)


def delete_auth_session(token_hash: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
        return int(cursor.rowcount or 0) > 0


def delete_trial_user(username: str) -> bool:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return False
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE username = ?", (normalized,))
        conn.execute(
            """
            UPDATE payment_orders
            SET status = 'cancelled'
            WHERE buyer_username = ? AND status = 'pending'
            """,
            (normalized,),
        )
        cursor = conn.execute(
            "DELETE FROM auth_users WHERE username = ? AND role = 'trial'",
            (normalized,),
        )
        return int(cursor.rowcount or 0) > 0


def delete_auth_user_for_admin(username: str) -> bool:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return False
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE username = ?", (normalized,))
        conn.execute(
            """
            UPDATE payment_orders
            SET status = 'cancelled'
            WHERE buyer_username = ? AND status = 'pending'
            """,
            (normalized,),
        )
        conn.execute("DELETE FROM watchlist WHERE owner_username = ?", (normalized,))
        cursor = conn.execute(
            "DELETE FROM auth_users WHERE username = ?",
            (normalized,),
        )
        return int(cursor.rowcount or 0) > 0


def delete_expired_auth_records():
    now_text = _now_text()
    trial_cutoff = (now_beijing() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now_text,))
        conn.execute("DELETE FROM auth_captchas WHERE expires_at <= ? OR consumed = 1", (now_text,))
        conn.execute(
            """
            UPDATE payment_orders
            SET status = 'cancelled'
            WHERE status = 'pending'
              AND buyer_username IN (
                  SELECT username
                  FROM auth_users
                  WHERE role = 'trial' AND created_at <= ?
              )
            """,
            (trial_cutoff,),
        )
        conn.execute(
            """
            DELETE FROM auth_sessions
            WHERE username IN (
                SELECT username
                FROM auth_users
                WHERE role = 'trial' AND created_at <= ?
            )
            """,
            (trial_cutoff,),
        )
        conn.execute(
            """
            DELETE FROM auth_users
            WHERE role = 'trial' AND created_at <= ?
            """,
            (trial_cutoff,),
        )
        conn.execute(
            """
            UPDATE auth_users
            SET status = 'expired', updated_at = ?
            WHERE expires_at IS NOT NULL
              AND expires_at <= ?
              AND status = 'active'
              AND role != 'trial'
            """,
            (now_text, now_text),
        )


def create_auth_captcha(captcha_id: str, code_hash: str, expires_at: str) -> dict:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_captchas (captcha_id, code_hash, created_at, expires_at, consumed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (captcha_id, code_hash, now_text, expires_at),
        )
    return {
        "captcha_id": captcha_id,
        "code_hash": code_hash,
        "created_at": now_text,
        "expires_at": expires_at,
        "consumed": False,
    }


def consume_auth_captcha(captcha_id: str) -> Optional[dict]:
    now_text = _now_text()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT captcha_id, code_hash, created_at, expires_at, consumed
            FROM auth_captchas
            WHERE captcha_id = ? AND consumed = 0 AND expires_at > ?
            """,
            (captcha_id, now_text),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE auth_captchas
                SET consumed = 1
                WHERE captcha_id = ?
                """,
                (captcha_id,),
            )
    if not row:
        return None
    item = dict(row)
    item["consumed"] = bool(item.get("consumed"))
    return item


def create_payment_order(
    order_id: str,
    plan_key: str,
    plan_label: str,
    amount: float,
    duration_days: int,
    provider: str = "alipay",
    buyer_username: str = "",
) -> dict:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO payment_orders
            (id, plan_key, plan_label, amount, duration_days, status, provider, buyer_username, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                order_id,
                plan_key,
                plan_label,
                float(amount),
                int(duration_days),
                provider,
                str(buyer_username or "").strip().lower(),
                now_text,
            ),
        )
    return get_payment_order(order_id) or {}


def get_payment_order(order_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM payment_orders WHERE id = ?",
            (str(order_id or "").strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_pending_payment_order_for_buyer(username: str) -> Optional[dict]:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM payment_orders
            WHERE buyer_username = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def list_payment_orders_for_buyer(username: str, limit: int = 20) -> list[dict]:
    normalized = str(username or "").strip().lower()
    if not normalized:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM payment_orders
            WHERE buyer_username = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (normalized, int(limit or 20)),
        ).fetchall()
    return [dict(row) for row in rows]


def cancel_pending_payment_order(order_id: str, buyer_username: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE payment_orders
            SET status = 'cancelled'
            WHERE id = ? AND buyer_username = ? AND status = 'pending'
            """,
            (str(order_id or "").strip(), str(buyer_username or "").strip().lower()),
        )
        return int(cursor.rowcount or 0) > 0


def mark_payment_order_paid(
    order_id: str,
    provider_trade_no: Optional[str],
    username: str,
    password_plain: str,
    expires_at: str,
) -> Optional[dict]:
    now_text = _now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE payment_orders
            SET status = 'paid',
                provider_trade_no = ?,
                username = ?,
                password_plain = ?,
                expires_at = ?,
                paid_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (provider_trade_no, username, password_plain, expires_at, now_text, order_id),
        )
    return get_payment_order(order_id)
