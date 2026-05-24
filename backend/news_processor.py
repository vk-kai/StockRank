import requests
import json
from datetime import datetime, timedelta
import os
from config import NEWS_DIR, NEWS_URL, MAX_NEWS_HOURS, is_dev_mode, DEV_NEWS_URL, get_random_user_agent
from logger import get_logger

error_logger = get_logger('error')
info_logger = get_logger('news')

def get_news_data(page=1, pagesize=400):
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle, get_news_headers
    
    dev_mode = is_dev_mode()
    api_url = DEV_NEWS_URL if dev_mode else NEWS_URL
    if dev_mode:
        info_logger.info(f"[DEV模式] 使用模拟服务: {api_url}")
    
    set_crawler_working('news')
    headers = get_news_headers()
    
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
            set_crawler_idle('news')
            return []
        
        try:
            data = response.json()
            if dev_mode:
                info_logger.debug(f"[DEV模式] 新闻API响应: {json.dumps(data, ensure_ascii=False)}")
        except Exception as e:
            error_logger.error(f"新闻API返回非JSON: {response.text[:200]}")
            set_crawler_idle('news')
            return []
        
        if not data:
            info_logger.info(f"新闻API返回空数据: {response.text[:100]}")
            set_crawler_idle('news')
            return []
        
        if 'data' not in data:
            info_logger.info(f"新闻API无data字段: {list(data.keys())}")
            set_crawler_idle('news')
            return []
        
        inner_data = data['data']
        if not isinstance(inner_data, dict) or 'list' not in inner_data:
            info_logger.info(f"新闻API data格式异常")
            set_crawler_idle('news')
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
        
        set_crawler_idle('news')
        return news_list
    except Exception as e:
        error_logger.error(f"获取新闻数据失败: {e}")
        set_crawler_idle('news')
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
        all_existing_keys = set()
        
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                other_file_path = os.path.join(NEWS_DIR, filename)
                try:
                    if os.path.getsize(other_file_path) == 0:
                        continue
                    with open(other_file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            for item in data:
                                news_title = item.get('title', '').strip()
                                news_content = item.get('content', '').strip()
                                if news_title and news_content:
                                    # 处理标题中的细微差异（如“初盘”和“盘初”）
                                    normalized_title = news_title.replace('初盘', '盘初').replace('开盘', '盘初').replace('早盘', '盘初')
                                    normalized_title = normalized_title.replace('午后', '盘后').replace('尾盘', '盘后')
                                    all_existing_keys.add((normalized_title, news_content))
                except (json.JSONDecodeError, Exception) as e:
                    continue
        
        existing_news = load_today_news()
        existing_dict = {item['id']: item for item in existing_news}
        
        new_count = 0
        for item in news_list:
            if 'ai_analyzed' not in item:
                item['ai_analyzed'] = False
            if 'pushed' not in item:
                item['pushed'] = False
            if 'core_event' not in item:
                item['core_event'] = ''
            
            news_id = item.get('id')
            news_title = item.get('title', '').strip()
            news_content = item.get('content', '').strip()
            
            # 处理标题中的细微差异（如“初盘”和“盘初”）
            normalized_title = news_title.replace('初盘', '盘初').replace('开盘', '盘初').replace('早盘', '盘初')
            normalized_title = normalized_title.replace('午后', '盘后').replace('尾盘', '盘后')
            
            if news_title and news_content:
                news_key = (normalized_title, news_content)
                if news_key not in all_existing_keys:
                    existing_dict[news_id] = item
                    new_count += 1
                    all_existing_keys.add(news_key)
                else:
                    for existing_id, existing_item in existing_dict.items():
                        existing_title = existing_item.get('title', '').strip()
                        existing_content = existing_item.get('content', '').strip()
                        
                        # 处理标题中的细微差异（如“初盘”和“盘初”）
                        normalized_existing_title = existing_title.replace('初盘', '盘初').replace('开盘', '盘初').replace('早盘', '盘初')
                        normalized_existing_title = normalized_existing_title.replace('午后', '盘后').replace('尾盘', '盘后')
                        
                        if normalized_existing_title == normalized_title and existing_content == news_content:
                            existing_item['url'] = item.get('url', existing_item.get('url', ''))
                            existing_item['time'] = item.get('time', existing_item.get('time', ''))
                            existing_item['importance'] = item.get('importance', existing_item.get('importance', '0'))
                            if item.get('ai_analyzed', False):
                                existing_item['ai_analyzed'] = True
                            if item.get('pushed', False):
                                existing_item['pushed'] = True
                            if item.get('core_event'):
                                existing_item['core_event'] = item.get('core_event')
                            if item.get('ai_analysis'):
                                existing_item['ai_analysis'] = item.get('ai_analysis')
                            break
        
        all_news = list(existing_dict.values())
        
        def get_sort_time(news):
            time_val = news.get('time', 0)
            if isinstance(time_val, str) and time_val.isdigit():
                return int(time_val)
            elif isinstance(time_val, (int, float)):
                return int(time_val)
            return 0
        
        all_news.sort(key=get_sort_time, reverse=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(all_news, f, ensure_ascii=False, indent=2)
        
        return new_count
    except Exception as e:
        error_logger.error(f"保存新闻数据失败: {e}")
        return 0

def cleanup_old_news():
    result = {
        'cleaned': False,
        'deleted_count': 0,
        'freed_bytes': 0,
        'deleted_files': [],
        'kept_count': 0,
        'reason': ''
    }
    
    try:
        ensure_news_dir()
        cutoff_time = datetime.now() - timedelta(hours=MAX_NEWS_HOURS)
        cutoff_date = cutoff_time.strftime('%Y-%m-%d')
        
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
                        result['deleted_files'].append(filename)
                        result['deleted_count'] += 1
                        result['freed_bytes'] += file_size
                    except Exception as e:
                        error_logger.error(f"删除新闻文件失败 ({filename}): {e}")
                else:
                    result['kept_count'] += 1
        
        if result['deleted_count'] > 0:
            result['cleaned'] = True
        else:
            result['reason'] = f"当前共 {total_files} 个文件，均在 {MAX_NEWS_HOURS} 小时保留期内"
        
        return result
    except Exception as e:
        error_logger.error(f"清理过期新闻失败: {e}")
        result['reason'] = f"清理失败: {str(e)}"
        return result

def get_recent_news(page=1, page_size=40, importance=None):
    ensure_news_dir()
    
    all_news = []
    
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
                        
                        all_news.extend(news_data)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    error_logger.error(f"读取新闻文件失败 ({filename}): {e}")
                    continue
        
        seen_keys = set()
        unique_news = []
        for news in all_news:
            news_title = news.get('title', '').strip()
            news_content = news.get('content', '').strip()
            if news_title and news_content:
                news_key = (news_title, news_content)
                if news_key not in seen_keys:
                    seen_keys.add(news_key)
                    unique_news.append(news)
        
        def get_sort_time(news):
            time_val = news.get('time', 0)
            if isinstance(time_val, str) and time_val.isdigit():
                return int(time_val)
            elif isinstance(time_val, (int, float)):
                return int(time_val)
            return 0
        
        unique_news.sort(key=get_sort_time, reverse=True)
        
        if importance is not None:
            unique_news = [news for news in unique_news if news.get('importance') == importance]
        
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

def search_news(keyword, page=1, page_size=40, importance=None):
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
                        
                        all_news.extend(news_data)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    error_logger.error(f"读取新闻文件失败 ({filename}): {e}")
                    continue
        
        seen_keys = set()
        unique_news = []
        for news in all_news:
            news_title = news.get('title', '').strip()
            news_content = news.get('content', '').strip()
            if news_title and news_content:
                news_key = (news_title, news_content)
                if news_key not in seen_keys:
                    seen_keys.add(news_key)
                    unique_news.append(news)
        
        search_results = []
        for news in unique_news:
            title = news.get('title', '').lower()
            content = news.get('content', '').lower()
            
            # 检查关键词匹配
            if keyword in title or keyword in content:
                # 检查重要性筛选
                if importance is None or news.get('importance') == importance:
                    search_results.append(news)
        
        def get_sort_time(news):
            time_val = news.get('time', 0)
            if isinstance(time_val, str) and time_val.isdigit():
                return int(time_val)
            elif isinstance(time_val, (int, float)):
                return int(time_val)
            return 0
        
        search_results.sort(key=get_sort_time, reverse=True)
        
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
