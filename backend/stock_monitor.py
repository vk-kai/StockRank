import json
from config import STOCK_MONITOR_CONFIG_FILE
from logger import setup_logging

error_logger, _, _ = setup_logging()

def load_stock_monitor_config():
    try:
        with open(STOCK_MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error_logger.error(f"加载股票监控配置失败: {e}")
        return None

def check_news_for_stocks(news_item):
    config = load_stock_monitor_config()
    
    if not config or not config.get('enabled'):
        return []
    
    stocks = config.get('stocks', [])
    matched_stocks = []
    
    title = news_item.get('title', '')
    content = news_item.get('content', '')
    text = f"{title} {content}"
    
    for stock in stocks:
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
