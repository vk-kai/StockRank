import json
import time
import os
from config import STOCK_MONITOR_CONFIG_FILE
from logger import get_logger

error_logger = get_logger('error')

_cached_config = None
_cache_time = 0
CACHE_TTL = 60

def load_stock_monitor_config():
    global _cached_config, _cache_time
    
    now = time.time()
    if _cached_config is not None and (now - _cache_time) < CACHE_TTL:
        return _cached_config
    
    try:
        if not os.path.exists(STOCK_MONITOR_CONFIG_FILE):
            return None
        
        with open(STOCK_MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
            _cached_config = json.load(f)
            _cache_time = now
            return _cached_config
    except Exception as e:
        error_logger.error(f"加载股票监控配置失败: {e}")
        return None

def check_news_for_stocks(news_item):
    config = load_stock_monitor_config()

    if not config or not config.get('enabled'):
        return []

    matched_stocks = []

    title = news_item.get('title', '')
    content = news_item.get('content', '')
    text = f"{title} {content}"

    # 优先读新 schema: watchlist[].news_alerts(只对 news_alerts.enabled=true 的项匹配)
    watchlist = config.get('watchlist', [])
    if watchlist:
        for w in watchlist:
            if not w.get('enabled'):
                continue
            na = w.get('news_alerts')
            if isinstance(na, dict):
                if not na.get('enabled'):
                    continue
                keywords = na.get('keywords') or []
            elif w.get('type') == 'keyword':
                # 旧 watchlist 无 news_alerts 字段:keyword 类型按 value 兜底匹配
                keywords = [w.get('value', '')]
            else:
                continue
            stock_name = (w.get('resolved_name') or
                          (w.get('value', '') if w.get('type') != 'keyword' else '')).strip()
            stock_code = (w.get('resolved_code') or '').strip()
            for keyword in keywords:
                kw = (keyword or '').strip()
                if kw and kw in text:
                    matched_stocks.append({
                        'name': stock_name or w.get('value', ''),
                        'code': stock_code,
                        'keyword': kw,
                    })
                    break
        return matched_stocks

    # 回退:旧 schema stocks[].keywords
    for stock in config.get('stocks', []):
        if not stock.get('enabled'):
            continue

        stock_name = stock.get('name', '')
        keywords = stock.get('keywords', [])

        for keyword in keywords:
            if keyword in text:
                matched_stocks.append({
                    'name': stock_name,
                    'code': stock.get('code', ''),
                    'keyword': keyword
                })
                break

    return matched_stocks

def should_push_news(news_item):
    matched_stocks = check_news_for_stocks(news_item)
    return len(matched_stocks) > 0, matched_stocks
