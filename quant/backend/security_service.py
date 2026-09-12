from __future__ import annotations

from backend import db
from backend.config import T0_ETF_LIST
from backend.paths import LEGACY_CUSTOM_ETF_PATH, LEGACY_REMOVED_ETF_PATH, ensure_runtime_storage_ready

_SH_INDEX_CODES = frozenset({
    "000001", "000300", "000905", "000852",
    "000016", "000903", "000819", "000849",
    "000922", "000932", "000991", "000993",
})


def ensure_runtime_db_ready():
    ensure_runtime_storage_ready()
    if not db._db_initialized:
        db.init_db(
            default_watchlist=T0_ETF_LIST,
            legacy_custom_path=str(LEGACY_CUSTOM_ETF_PATH),
            legacy_removed_path=str(LEGACY_REMOVED_ETF_PATH),
        )
    from backend.auth_service import ensure_default_users

    ensure_default_users()


def get_market_code(code: str) -> int:
    code = str(code).strip().zfill(6)
    if code in _SH_INDEX_CODES:
        return 1
    if code.startswith(("00", "15", "16", "18", "20", "30", "39")):
        return 0
    if code.startswith(("50", "51", "52", "56", "58", "60", "68", "90", "110", "113", "118", "132", "204")):
        return 1
    return 1


def infer_t0_flag(code: str, name: str = "") -> bool:
    if any(item["code"] == code for item in T0_ETF_LIST):
        return True

    code = str(code).strip().zfill(6)
    name_upper = (name or "").upper()
    return code.startswith(("15", "50", "51", "52", "56", "58")) or "ETF" in name_upper or "LOF" in name_upper


def get_watchlist_security(code: str, owner_username: str | None = None):
    if not db._db_initialized:
        ensure_runtime_db_ready()
    return db.get_watchlist_item(code, owner_username)


def list_watchlist_securities(owner_username: str | None = None) -> list:
    if not db._db_initialized:
        ensure_runtime_db_ready()
    return db.list_watchlist(owner_username)


def get_search_candidates() -> list:
    return list_watchlist_securities()


def add_watchlist_security(code: str, name: str = "", market=None, t0=None, owner_username: str | None = None) -> dict:
    if not db._db_initialized:
        ensure_runtime_db_ready()
    raw_input = str(code).strip()
    code = raw_input.zfill(6) if raw_input.isdigit() else raw_input

    if not raw_input.isdigit():
        try:
            from backend.market.akshare_data import search_major_indices

            index_matches = search_major_indices(raw_input, limit=10)
            exact_match = next((item for item in index_matches if item.get("name") == raw_input), None)
            if not exact_match and index_matches:
                exact_match = index_matches[0]
            if exact_match:
                code = exact_match["code"]
                if not name:
                    name = exact_match["name"]
                if market is None:
                    market = exact_match.get("market")
        except Exception as e:
            print(f"Error fetching major index by name: {e}")

    code = str(code).strip().zfill(6)
    all_items = list_watchlist_securities(owner_username)
    for item in all_items:
        if item["code"] == code:
            return {"success": False, "message": "标的已存在"}

    if not name:
        try:
            from backend.market.akshare_data import get_major_index_quotes

            index_quotes = get_major_index_quotes([code])
            if index_quotes:
                index_quote = index_quotes[0]
                name = index_quote.get("name") or name
                market = index_quote.get("market", market)
        except Exception as e:
            print(f"Error fetching name via AkShare major index quote: {e}")

    if not name:
        try:
            from backend.market import pytdx_data

            quotes = pytdx_data.get_realtime_quotes([code])
            if quotes:
                quote = quotes[0]
                if quote.get("name") and quote["name"] != code:
                    name = quote["name"]
        except Exception as e:
            print(f"Error fetching name via pytdx quote: {e}")

    if not name:
        try:
            from backend.market import pytdx_data

            matches = pytdx_data.search_etf(code, limit=10)
            exact_match = next((item for item in matches if item.get("code") == code), None)
            if exact_match and exact_match.get("name"):
                name = exact_match["name"]
                market = exact_match.get("market", market)
        except Exception as e:
            print(f"Error fetching name via pytdx search: {e}")

    if not name:
        try:
            from backend.market.akshare_data import get_stock_name_by_code

            stock_name = get_stock_name_by_code(code)
            if stock_name:
                name = stock_name
        except Exception as e:
            print(f"Error fetching name via AkShare stock list: {e}")

    if not name:
        try:
            from backend.market.akshare_data import get_cached_etf_detail, get_etf_detail

            detail = get_cached_etf_detail(code) or get_etf_detail(code, timeout=2)
            if detail and detail.get("name") and detail["name"] != code:
                name = detail["name"]
        except Exception as e:
            print(f"Error fetching name via AkShare detail: {e}")

    if not name:
        try:
            from backend.market.akshare_data import search_etf_akshare

            matches = search_etf_akshare(code, limit=10)
            exact_match = next((item for item in matches if item.get("code") == code), None)
            if exact_match and exact_match.get("name"):
                name = exact_match["name"]
                market = exact_match.get("market", market)
        except Exception as e:
            print(f"Error fetching name via AkShare search: {e}")

    if not name:
        name = code

    market = get_market_code(code) if market is None else market
    t0 = infer_t0_flag(code, name) if t0 is None else t0
    new_item = db.upsert_watchlist_item(code, name, int(market), bool(t0), owner_username)
    return {"success": True, "data": new_item}


def remove_watchlist_security(code: str, owner_username: str | None = None) -> dict:
    if not db._db_initialized:
        ensure_runtime_db_ready()
    db.delete_watchlist_item(code, owner_username)
    return {"success": True}


def get_etf_info(code: str):
    return get_watchlist_security(code)


def get_all_etfs() -> list:
    return list_watchlist_securities()


def add_custom_etf(code: str, name: str = "", market=None, t0=None) -> dict:
    return add_watchlist_security(code, name=name, market=market, t0=t0)


def remove_custom_etf(code: str) -> dict:
    return remove_watchlist_security(code)
