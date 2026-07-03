from __future__ import annotations

from datetime import datetime
from typing import Any

from data_processor import get_market_map_stocks, load_market_summary_cache, load_realtime_data
from margin_collector import get_stock_margin_series
from news_processor import get_recent_news


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _compact_code(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())[-6:]


def _event_id(*parts: Any) -> str:
    return "|".join(str(part) for part in parts if part not in (None, ""))


def _sector_flow(item: dict) -> float:
    if "net_flow" in item:
        return _safe_float(item.get("net_flow"))
    return _safe_float(item.get("flow"))


def _sector_snapshot(record: Any) -> list[dict]:
    if isinstance(record, dict):
        data = record.get("data", [])
    else:
        data = record
    if not isinstance(data, list):
        return []
    ranked = [item for item in data if isinstance(item, dict) and item.get("name")]
    ranked.sort(key=_sector_flow, reverse=True)
    return ranked


def _format_amount(value: float) -> str:
    amount = abs(value)
    sign = "+" if value > 0 else "-" if value < 0 else ""
    if amount >= 100000000:
        return f"{sign}{amount / 100000000:.2f}亿"
    if amount >= 10000:
        return f"{sign}{amount / 10000:.2f}万"
    return f"{sign}{amount:.0f}"


def _news_time_to_hhmm(news_item: dict, fallback_date: str) -> str:
    raw_time = news_item.get("time") or news_item.get("timestamp")
    if isinstance(raw_time, (int, float)) or (isinstance(raw_time, str) and raw_time.isdigit()):
        try:
            return datetime.fromtimestamp(int(raw_time)).strftime("%H:%M")
        except Exception:
            pass
    if isinstance(raw_time, str) and len(raw_time) >= 16:
        try:
            return datetime.fromisoformat(raw_time).strftime("%H:%M")
        except Exception:
            pass
    return "00:00" if fallback_date else "--:--"


def _build_sector_events(realtime_data: dict, max_events: int = 120) -> list[dict]:
    events: list[dict] = []
    previous_ranks: dict[str, int] = {}
    previous_flows: dict[str, float] = {}

    time_keys = sorted(k for k in realtime_data.keys() if isinstance(k, str) and not k.startswith("_"))
    for minute_key in time_keys:
        snapshot = _sector_snapshot(realtime_data.get(minute_key))
        for idx, item in enumerate(snapshot[:30], start=1):
            name = str(item.get("name") or "")
            code = str(item.get("code") or "")
            flow = _sector_flow(item)
            change = _safe_float(item.get("change"))
            previous_rank = previous_ranks.get(name)
            previous_flow = previous_flows.get(name)

            if idx == 1 and previous_rank not in (None, 1):
                events.append({
                    "id": _event_id("sector_top_rank", minute_key, name),
                    "time": minute_key,
                    "type": "sector_top_rank",
                    "category": "sector",
                    "importance": 4,
                    "target": name,
                    "target_code": code,
                    "title": f"{name}板块资金流升至第1",
                    "detail": f"当前净流入{_format_amount(flow)}，涨跌幅{change * 100:.2f}%，前一排名第{previous_rank}",
                    "source": "StockRank",
                })

            if previous_rank is not None and previous_rank > idx and idx <= 5:
                events.append({
                    "id": _event_id("sector_rank_jump", minute_key, name, previous_rank, idx),
                    "time": minute_key,
                    "type": "sector_rank_jump",
                    "category": "sector",
                    "importance": 3,
                    "target": name,
                    "target_code": code,
                    "title": f"{name}板块排名快速上升",
                    "detail": f"资金流排名从第{previous_rank}升至第{idx}，当前净流入{_format_amount(flow)}",
                    "source": "StockRank",
                })

            if previous_flow is not None and flow > 0:
                delta = flow - previous_flow
                if delta >= 100000000 or (previous_flow > 0 and delta / max(previous_flow, 1) >= 1.5):
                    events.append({
                        "id": _event_id("sector_flow_surge", minute_key, name),
                        "time": minute_key,
                        "type": "sector_flow_surge",
                        "category": "sector",
                        "importance": 3,
                        "target": name,
                        "target_code": code,
                        "title": f"{name}板块资金突然放大",
                        "detail": f"较上一快照增加{_format_amount(delta)}，当前净流入{_format_amount(flow)}",
                        "source": "StockRank",
                    })

            previous_ranks[name] = idx
            previous_flows[name] = flow

        if len(events) >= max_events:
            break
    return events


def _build_news_events(news_items: list[dict], date_str: str, max_events: int = 80) -> list[dict]:
    events = []
    for item in news_items[:max_events]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        important = str(item.get("importance") or "") == "3"
        events.append({
            "id": _event_id("important_news" if important else "news", item.get("id") or title),
            "time": _news_time_to_hhmm(item, date_str),
            "type": "important_news" if important else "news",
            "category": "news",
            "importance": 4 if important else 2,
            "target": "",
            "target_code": "",
            "title": title,
            "detail": str(item.get("core_event") or item.get("content") or "")[:120],
            "source": "News",
            "url": item.get("url") or "",
        })
    return events


def build_timeline_events(
    realtime_data: dict,
    news_items: list[dict],
    date_str: str,
    market_summary: dict | None = None,
) -> list[dict]:
    events = []
    if isinstance(realtime_data, dict) and not realtime_data.get("_invalid"):
        events.extend(_build_sector_events(realtime_data))
    if isinstance(news_items, list):
        events.extend(_build_news_events(news_items, date_str))

    events.sort(key=lambda item: (item.get("time") or "", -int(item.get("importance") or 0)))
    return events


def get_intraday_timeline(date_str: str | None = None) -> dict:
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    realtime_data = load_realtime_data(target_date)
    news = get_recent_news(page=1, page_size=120).get("news", [])
    events = build_timeline_events(
        realtime_data=realtime_data,
        news_items=news,
        date_str=target_date,
        market_summary=load_market_summary_cache(),
    )
    return {
        "success": True,
        "date": target_date,
        "events": events,
        "count": len(events),
    }


def _latest_sector_rank(sector_name: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    realtime_data = load_realtime_data(today)
    if not isinstance(realtime_data, dict) or realtime_data.get("_invalid"):
        return {}
    time_keys = sorted(k for k in realtime_data.keys() if isinstance(k, str) and not k.startswith("_"))
    if not time_keys:
        return {}
    latest_key = time_keys[-1]
    snapshot = _sector_snapshot(realtime_data.get(latest_key))
    for idx, item in enumerate(snapshot, start=1):
        if str(item.get("name") or "") == sector_name:
            return {
                "rank": idx,
                "net_flow": _sector_flow(item),
                "change": _safe_float(item.get("change")),
                "time": latest_key,
            }
    return {}


def _match_recent_news(code: str, name: str, sector_name: str) -> list[dict]:
    terms = [term for term in {_compact_code(code), name, sector_name} if term]
    matches = []
    for item in get_recent_news(page=1, page_size=80).get("news", []):
        text = f"{item.get('title', '')} {item.get('content', '')} {item.get('core_event', '')}"
        if any(term and term in text for term in terms):
            matches.append({
                "title": item.get("title") or "",
                "time": _news_time_to_hhmm(item, ""),
                "importance": item.get("importance") or "",
                "url": item.get("url") or "",
            })
        if len(matches) >= 3:
            break
    return matches


def _find_stock_in_sector(code: str, sector_code: str) -> dict:
    if not sector_code:
        return {}
    sector_data = get_market_map_stocks(sector_code)
    stocks = (sector_data or {}).get("stocks") or []
    compact = _compact_code(code)
    for item in stocks:
        item_code = _compact_code(item.get("code") or item.get("symbol") or item.get("stock_code"))
        if item_code == compact:
            return dict(item)
    return {}


def get_stock_hover_summary(code: str, sector_code: str = "", name: str = "", sector_name_hint: str = "") -> dict:
    stock = _find_stock_in_sector(code, sector_code)
    stock_name = str(stock.get("name") or name or code)
    sector_name = str(stock.get("industry") or stock.get("sector") or stock.get("sector_name") or sector_name_hint or "")
    sector_rank = _latest_sector_rank(sector_name)
    margin_data = get_stock_margin_series(code)
    latest_margin = (margin_data.get("series") or [])[-1] if margin_data.get("series") else {}

    data = {
        "code": _compact_code(code) or code,
        "name": stock_name,
        "sector_code": sector_code,
        "sector_name": sector_name,
        "sector_rank": sector_rank.get("rank"),
        "sector_net_flow": sector_rank.get("net_flow"),
        "sector_change": sector_rank.get("change"),
        "sector_time": sector_rank.get("time"),
        "change": stock.get("change"),
        "turnover": stock.get("turnover") or stock.get("turnover_rate"),
        "market_cap": stock.get("market_cap") or stock.get("value"),
        "margin": {
            "latest_date": margin_data.get("latest_balance_date") or margin_data.get("latest_date"),
            "latest_balance": margin_data.get("latest_balance"),
            "latest_net_inflow": latest_margin.get("j"),
        },
        "recent_news": _match_recent_news(code, stock_name, sector_name),
    }
    return {"success": True, "data": data}
