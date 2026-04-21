import requests
import json
from datetime import datetime, timedelta
import os
from config import NEWS_DIR, NEWS_URL, MAX_NEWS_HOURS, is_dev_mode, DEV_NEWS_URL, get_random_user_agent
from logger import get_logger

error_logger = get_logger('error')
info_logger = get_logger('news')

def get_news_data(page=1, pagesize=400):
    dev_mode = is_dev_mode()
    api_url = DEV_NEWS_URL if dev_mode else NEWS_URL
    if dev_mode:
        info_logger.info(f"[DEV模式] 使用模拟服务: {api_url}")
    headers = {
        'User-Agent': get_random_user_agent(),
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
        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            error_logger.error(f"新闻API请求失败: HTTP {response.status_code}")
            return []
        
        try:
            data = response.json()
            if dev_mode:
                info_logger.debug(f"[DEV模式] 新闻API响应: {json.dumps(data, ensure_ascii=False)}")
        except Exception as e:
            error_logger.error(f"新闻API返回非JSON: {response.text[:200]}")
            return []
        
        if not data:
            info_logger.info(f"新闻API返回空数据: {response.text[:100]}")
            return []
        
        if 'data' not in data:
            info_logger.info(f"新闻API无data字段: {list(data.keys())}")
            return []
        
        inner_data = data['data']
        if not isinstance(inner_data, dict) or 'list' not in inner_data:
            info_logger.info(f"新闻API data格式异常")
            return []
        
        news_list = []
        news_data = inner_data['list']
        
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
            if os.path.getsize(file_path) == 0:
                return []
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except json.JSONDecodeError:
            return []
        except Exception as e:
            error_logger.error(f"加载新闻数据失败: {e}")
            return []
    return []

def save_news_data(news_list):
    ensure_news_dir()
    file_path = get_news_file_path()
    
    try:
        existing_news = load_today_news()
        existing_dict = {item['id']: item for item in existing_news}
        
        for item in news_list:
            if 'ai_analyzed' not in item:
                item['ai_analyzed'] = False
            if 'pushed' not in item:
                item['pushed'] = False
            if 'core_event' not in item:
                item['core_event'] = ''
            existing_dict[item['id']] = item
        
        all_news = list(existing_dict.values())
        
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
        cutoff_date = cutoff_time.strftime('%Y-%m-%d')
        
        deleted_files = []
        kept_files = []
        total_files = 0
        
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                total_files += 1
                file_path = os.path.join(NEWS_DIR, filename)
                file_date = filename.replace('.json', '')
                
                if file_date < cutoff_date:
                    try:
                        file_size = os.path.getsize(file_path)
                        os.remove(file_path)
                        deleted_files.append({'name': filename, 'size': file_size})
                        info_logger.info(f"清理过期新闻文件: {filename} (大小: {file_size} 字节)")
                    except Exception as e:
                        error_logger.error(f"删除新闻文件失败 ({filename}): {e}")
                else:
                    kept_files.append(filename)
        
        if deleted_files:
            total_deleted_size = sum(f['size'] for f in deleted_files)
            info_logger.info(f"新闻清理完成: 共扫描 {total_files} 个文件, 删除 {len(deleted_files)} 个过期文件, "
                           f"保留 {len(kept_files)} 个文件, 释放空间 {total_deleted_size} 字节")
        else:
            info_logger.debug(f"新闻清理检查: 共 {total_files} 个文件, 无过期文件需要删除")
        
        return True
    except Exception as e:
        error_logger.error(f"清理过期新闻失败: {e}")
        return False

def get_recent_news(page=1, page_size=40):
    ensure_news_dir()
    
    all_news = []
    cutoff_time = datetime.now() - timedelta(hours=MAX_NEWS_HOURS)
    
    try:
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(NEWS_DIR, filename)
                try:
                    if os.path.getsize(file_path) == 0:
                        continue
                    with open(file_path, 'r', encoding='utf-8') as f:
                        news_data = json.load(f)
                        
                        if not isinstance(news_data, list):
                            continue
                        
                        filtered_news = []
                        for item in news_data:
                            news_time = item.get('time', '')
                            if news_time:
                                try:
                                    if isinstance(news_time, str) and news_time.isdigit():
                                        news_datetime = datetime.fromtimestamp(int(news_time))
                                    elif isinstance(news_time, (int, float)):
                                        news_datetime = datetime.fromtimestamp(news_time)
                                    else:
                                        continue
                                    
                                    if news_datetime >= cutoff_time:
                                        filtered_news.append(item)
                                except (ValueError, OSError):
                                    continue
                        
                        all_news.extend(filtered_news)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    error_logger.error(f"读取新闻文件失败 ({filename}): {e}")
                    continue
        
        seen_ids = set()
        unique_news = []
        for news in all_news:
            news_id = news.get('id')
            if news_id and news_id not in seen_ids:
                seen_ids.add(news_id)
                unique_news.append(news)
        
        unique_news.sort(key=lambda x: x.get('time', ''), reverse=True)
        
        total_count = len(unique_news)
        
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        
        return {
            'news': unique_news[start_index:end_index],
            'total': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        }
    except Exception as e:
        error_logger.error(f"获取最近新闻失败: {e}")
        return {
            'news': [],
            'total': 0,
            'page': page,
            'page_size': page_size,
            'total_pages': 0
        }

def search_news(keyword, page=1, page_size=40):
    ensure_news_dir()
    
    if not keyword or not keyword.strip():
        return {
            'news': [],
            'total': 0,
            'page': page,
            'page_size': page_size,
            'total_pages': 0
        }
    
    keyword = keyword.strip().lower()
    all_news = []
    cutoff_time = datetime.now() - timedelta(hours=MAX_NEWS_HOURS)
    
    try:
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(NEWS_DIR, filename)
                try:
                    if os.path.getsize(file_path) == 0:
                        continue
                    with open(file_path, 'r', encoding='utf-8') as f:
                        news_data = json.load(f)
                        
                        if not isinstance(news_data, list):
                            continue
                        
                        filtered_news = []
                        for item in news_data:
                            news_time = item.get('time', '')
                            if news_time:
                                try:
                                    if isinstance(news_time, str) and news_time.isdigit():
                                        news_datetime = datetime.fromtimestamp(int(news_time))
                                    elif isinstance(news_time, (int, float)):
                                        news_datetime = datetime.fromtimestamp(news_time)
                                    else:
                                        continue
                                    
                                    if news_datetime >= cutoff_time:
                                        filtered_news.append(item)
                                except (ValueError, OSError):
                                    continue
                        
                        all_news.extend(filtered_news)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    error_logger.error(f"读取新闻文件失败 ({filename}): {e}")
                    continue
        
        seen_ids = set()
        unique_news = []
        for news in all_news:
            news_id = news.get('id')
            if news_id and news_id not in seen_ids:
                seen_ids.add(news_id)
                unique_news.append(news)
        
        search_results = []
        for news in unique_news:
            title = news.get('title', '').lower()
            content = news.get('content', '').lower()
            
            if keyword in title or keyword in content:
                search_results.append(news)
        
        search_results.sort(key=lambda x: x.get('time', ''), reverse=True)
        
        total_count = len(search_results)
        
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        
        return {
            'news': search_results[start_index:end_index],
            'total': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        }
    except Exception as e:
        error_logger.error(f"搜索新闻失败: {e}")
        return {
            'news': [],
            'total': 0,
            'page': page,
            'page_size': page_size,
            'total_pages': 0
        }
