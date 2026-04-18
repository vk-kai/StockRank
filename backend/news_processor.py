import requests
import json
from datetime import datetime, timedelta
import os
from config import NEWS_DIR, NEWS_URL, MAX_NEWS_HOURS
from logger import setup_logging

error_logger, _, _ = setup_logging()

def get_news_data(page=1, pagesize=400):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://news.10jqka.com.cn/',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }
    
    params = {
        'page': page,
        'tag': '',
        'track': 'website',
        'pagesize': pagesize
    }
    
    try:
        response = requests.get(NEWS_URL, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if data and 'data' in data and 'list' in data['data']:
            news_list = []
            news_data = data['data']['list']
            
            if isinstance(news_data, list):
                for item in news_data:
                    if isinstance(item, dict):
                        news_item = {
                            'id': str(item.get('id', '')),
                            'title': item.get('title', ''),
                            'content': item.get('digest', item.get('content', '')),
                            'source': item.get('source', '同花顺'),
                            'time': item.get('time', item.get('ctime', '')),
                            'url': item.get('url', ''),
                            'type': item.get('type', 'stock'),
                            'importance': item.get('import', '0'),
                            'timestamp': datetime.now().isoformat()
                        }
                        news_list.append(news_item)
            
            return news_list
        return []
    except Exception as e:
        error_logger.error(f"获取新闻数据失败: {e}")
        return []

def get_news_file_path():
    today = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(NEWS_DIR, f'{today}.json')

def ensure_news_dir():
    if not os.path.exists(NEWS_DIR):
        os.makedirs(NEWS_DIR)

def load_today_news():
    ensure_news_dir()
    file_path = get_news_file_path()
    
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            error_logger.error(f"加载新闻数据失败: {e}")
            return []
    return []

def save_news_data(news_list):
    ensure_news_dir()
    file_path = get_news_file_path()
    
    try:
        existing_news = load_today_news()
        existing_ids = {item['id'] for item in existing_news}
        
        new_news = [item for item in news_list if item['id'] not in existing_ids]
        
        all_news = new_news + existing_news
        
        all_news.sort(key=lambda x: x.get('time', ''), reverse=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(all_news, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        error_logger.error(f"保存新闻数据失败: {e}")
        return False

def cleanup_old_news():
    try:
        ensure_news_dir()
        cutoff_time = datetime.now() - timedelta(hours=MAX_NEWS_HOURS)
        
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(NEWS_DIR, filename)
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                if file_time < cutoff_time:
                    os.remove(file_path)
        
        return True
    except Exception as e:
        error_logger.error(f"清理过期新闻失败: {e}")
        return False

def get_recent_news(limit=50):
    ensure_news_dir()
    
    all_news = []
    cutoff_time = datetime.now() - timedelta(hours=MAX_NEWS_HOURS)
    
    try:
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(NEWS_DIR, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        news_data = json.load(f)
                        
                        filtered_news = [
                            item for item in news_data 
                            if datetime.fromisoformat(item.get('timestamp', datetime.now().isoformat())) >= cutoff_time
                        ]
                        all_news.extend(filtered_news)
                except Exception as e:
                    error_logger.error(f"读取新闻文件失败 ({filename}): {e}")
                    continue
        
        all_news.sort(key=lambda x: x.get('time', ''), reverse=True)
        
        return all_news[:limit]
    except Exception as e:
        error_logger.error(f"获取最近新闻失败: {e}")
        return []
