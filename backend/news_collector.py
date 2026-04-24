import os
import time
from datetime import datetime, timedelta
from news_processor import get_news_data, save_news_data, cleanup_old_news, load_today_news, get_recent_news, NEWS_DIR
from ai_analyzer import batch_analyze_news, is_important_news, set_heartbeat_callback
from feishu_pusher import push_important_news
from stock_monitor import should_push_news
from logger import get_logger, cleanup_old_logs
from thread_monitor import heartbeat, register_thread, set_busy
import json

error_logger = get_logger('error')
news_logger = get_logger('news')
news_add_logger = get_logger('news_add')
news_important_logger = get_logger('news_important')
ai_logger = get_logger('ai')
cleanup_logger = get_logger('cleanup_news')

_last_cleanup_date = None

def ai_heartbeat():
    heartbeat('news_collector')

set_heartbeat_callback(ai_heartbeat)

def load_all_news_status():
    all_status = {}
    try:
        if not os.path.exists(NEWS_DIR):
            return all_status
        for filename in os.listdir(NEWS_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(NEWS_DIR, filename)
                try:
                    if os.path.getsize(file_path) == 0:
                        continue
                    with open(file_path, 'r', encoding='utf-8') as f:
                        news_data = json.load(f)
                        if isinstance(news_data, list):
                            for item in news_data:
                                news_title = item.get('title', '').strip()
                                news_content = item.get('content', '').strip()
                                if news_title and news_content:
                                    key = (news_title, news_content)
                                    if key not in all_status:
                                        all_status[key] = {
                                            'pushed': item.get('pushed', False),
                                            'ai_analyzed': item.get('ai_analyzed', False)
                                        }
                                    else:
                                        if item.get('pushed', False):
                                            all_status[key]['pushed'] = True
                                        if item.get('ai_analyzed', False):
                                            all_status[key]['ai_analyzed'] = True
                except (json.JSONDecodeError, Exception) as e:
                    continue
    except Exception as e:
        error_logger.error(f"加载所有新闻状态失败: {e}")
    return all_status

def process_news_with_ai_and_push(news_list):
    try:
        existing_news = load_today_news()
        existing_keys = {(item.get('title', '').strip(), item.get('content', '').strip()): item for item in existing_news}
        existing_dict = {item['id']: item for item in existing_news}
        all_news_status = load_all_news_status()
        
        new_items = []
        normal_items = []
        important_items = []
        
        for news_item in news_list:
            news_id = news_item.get('id')
            news_title = news_item.get('title', '').strip()
            news_content = news_item.get('content', '').strip()
            news_key = (news_title, news_content)
            
            if news_title and news_content and news_key in existing_keys:
                existing_item = existing_keys[news_key]
                existing_item['url'] = news_item.get('url', existing_item.get('url', ''))
                existing_item['time'] = news_item.get('time', existing_item.get('time', ''))
                existing_item['importance'] = news_item.get('importance', existing_item.get('importance', '0'))
                continue
            
            if news_key in all_news_status:
                status = all_news_status[news_key]
                news_item['ai_analyzed'] = status.get('ai_analyzed', False)
                news_item['pushed'] = status.get('pushed', False)
                news_item['core_event'] = ''
                normal_items.append(news_item)
                continue
            
            news_item['ai_analyzed'] = False
            news_item['pushed'] = False
            news_item['core_event'] = ''
            
            if news_item.get('importance') == '3':
                important_items.append(news_item)
            else:
                normal_items.append(news_item)
                news_item['ai_analyzed'] = True
            
            new_items.append(news_item)
            existing_dict[news_id] = news_item
            if news_title and news_content:
                existing_keys[news_key] = news_item
        
        if not new_items:
            return list(existing_dict.values()), [], [], []
        
        pushed_items = []
        ignored_items = []
        
        if important_items:
            items_to_analyze = important_items[:5]
            if len(important_items) > 5:
                ai_logger.info(f"重要新闻数量较多({len(important_items)}条)，本次仅分析前5条")
            
            set_busy('news_collector', True)
            try:
                analysis_results = batch_analyze_news(items_to_analyze)
            finally:
                set_busy('news_collector', False)
            
            for news_item in items_to_analyze:
                news_id = news_item.get('id')
                analysis = analysis_results.get(news_id)
                news_item['ai_analyzed'] = True
                
                if analysis:
                    news_item['ai_analysis'] = analysis
                    news_item['core_event'] = analysis.get('core_event', '')
                    
                    if is_important_news(analysis):
                        if not news_item.get('pushed', False):
                            push_important_news(news_item, analysis)
                            news_item['pushed'] = True
                            pushed_items.append({
                                'title': news_item.get('title', ''),
                                'reason': analysis.get('reason', ''),
                                'core_event': analysis.get('core_event', '')
                            })
                        else:
                            ai_logger.info(f"新闻已推送过，跳过重复推送: {news_item.get('title', '')}")
                    else:
                        ignored_items.append({
                            'title': news_item.get('title', ''),
                            'reason': analysis.get('reason', ''),
                            'level': analysis.get('level', '')
                        })
                else:
                    ignored_items.append({
                        'title': news_item.get('title', ''),
                        'reason': 'AI分析失败',
                        'level': '未知'
                    })
            
            for news_item in important_items[5:]:
                news_item['ai_analyzed'] = False
                news_item['core_event'] = ''
        
        for news_item in new_items:
            should_push, matched_stocks = should_push_news(news_item)
            if should_push and not news_item.get('pushed'):
                from feishu_pusher import send_feishu_message
                from datetime import datetime as dt
                
                stock_names = "、".join([s['name'] for s in matched_stocks])
                news_title = news_item.get('title', '')
                news_content = news_item.get('content', '')
                news_time = news_item.get('time', '')
                
                if news_time:
                    try:
                        ts = int(news_time)
                        news_time = dt.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError, OSError):
                        pass
                
                parts = [f"匹配股票：{stock_names}"]
                if news_time:
                    parts.append(news_time)
                parts.append(f"<font color='red'>{news_content}</font>")
                content = "\n\n".join(parts)
                url = news_item.get('url')
                send_feishu_message(news_title, content, url=url)
                news_item['pushed'] = True
        
        return list(existing_dict.values()), normal_items, pushed_items, ignored_items
                
    except Exception as e:
        error_logger.error(f"处理新闻AI分析和推送异常: {e}")
        return news_list, [], [], []

def news_collection_thread():
    global _last_cleanup_date
    register_thread('news_collector')
    
    while True:
        try:
            heartbeat('news_collector')
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            current_hour = now.hour
            current_minute = now.minute
            
            if current_hour == 0 and current_minute == 0:
                if _last_cleanup_date != today:
                    cleanup_logger.info("开始执行每日清理任务...")
                    
                    news_cleanup_result = cleanup_old_news()
                    if news_cleanup_result['cleaned']:
                        cleanup_logger.info(f"新闻数据清理完成: 删除 {news_cleanup_result['deleted_count']} 个文件，"
                                          f"释放空间 {news_cleanup_result['freed_bytes']} 字节")
                    else:
                        cleanup_logger.info(f"新闻数据无需清理: {news_cleanup_result['reason']}")
                    
                    log_cleanup_result = cleanup_old_logs(hours=48)
                    if log_cleanup_result:
                        cleanup_logger.info(f"日志文件清理完成: 删除 {len(log_cleanup_result)} 个文件: {', '.join(log_cleanup_result)}")
                    else:
                        cleanup_logger.info("日志文件无需清理: 无过期文件")
                    
                    _last_cleanup_date = today
                    cleanup_logger.info("每日清理任务执行完成")
            
            news_data = get_news_data(page=1, pagesize=30)
            
            result = process_news_with_ai_and_push(news_data or [])
            all_news = result[0]
            normal_items = result[1]
            pushed_items = result[2]
            ignored_items = result[3]
            
            actual_new_count = save_news_data(all_news)
            
            total_new = len(normal_items) + len(pushed_items) + len(ignored_items)
            if actual_new_count > 0:
                for item in normal_items:
                    news_add_logger.debug(f"新增普通新闻，标题: {item.get('title', '')}")
                
                for item in pushed_items:
                    news_important_logger.info(f"新增重要新闻并推送，标题: 《{item['title']}》，推送理由: {item['reason']}")
                
                for item in ignored_items:
                    news_important_logger.info(f"新增重要新闻但忽略，标题: 《{item['title']}》，忽略理由: {item['reason']} (级别: {item['level']})")
                
                normal_count = len(normal_items)
                important_count = len(pushed_items) + len(ignored_items)
                pushed_count = len(pushed_items)
                
                all_titles = []
                for item in normal_items[:5]:
                    all_titles.append(item.get('title', '')[:30])
                for item in pushed_items[:5]:
                    all_titles.append(item['title'][:30])
                for item in ignored_items[:5]:
                    all_titles.append(item['title'][:30])
                
                if len(normal_items) + len(pushed_items) + len(ignored_items) > 5:
                    all_titles.append(f"...等{total_new}条")
                
                if actual_new_count == total_new:
                    summary = f"本轮新增 {total_new} 条"
                else:
                    summary = f"本轮采集 {total_new} 条，实际新增 {actual_new_count} 条"
                
                type_parts = []
                if normal_count > 0:
                    type_parts.append(f"普通 {normal_count} 条")
                if important_count > 0:
                    type_parts.append(f"重要 {important_count} 条")
                if type_parts:
                    summary += f"（{', '.join(type_parts)}）"
                
                if pushed_count > 0:
                    summary += f"，推送 {pushed_count} 条"
                
                if all_titles:
                    summary += f" 标题：{'|'.join(all_titles)}"
                
                recent_news_result = get_recent_news(1, 10000)
                summary += f"，当前共 {recent_news_result['total']} 条"
                
                news_logger.info(summary)
            
        except Exception as e:
            error_logger.error(f"新闻采集线程异常: {e}")
        
        time.sleep(30)
        
def init_news_data():
    try:
        news_data = get_news_data(page=1, pagesize=30)
        if news_data:
            normal_count = sum(1 for item in news_data if item.get('importance') != '3')
            important_count = sum(1 for item in news_data if item.get('importance') == '3')
            for item in news_data:
                item['ai_analyzed'] = True
                item['pushed'] = True
                if 'core_event' not in item:
                    item['core_event'] = ''
            save_news_data(news_data)
            news_logger.info(f"初始化 {len(news_data)} 条数据成功，普通{normal_count}条，重要{important_count}条")
        else:
            news_logger.info("初始化新闻数据：API未返回数据")
    except Exception as e:
        error_logger.error(f"初始化新闻数据失败: {e}")
