import os
import time
from datetime import datetime
from news_processor import get_news_data, save_news_data, cleanup_old_news, load_today_news
from ai_analyzer import batch_analyze_news, is_important_news
from feishu_pusher import push_important_news
from stock_monitor import should_push_news
from logger import setup_logging
from thread_monitor import heartbeat, register_thread

error_logger, info_logger, _ = setup_logging()

def process_news_with_ai_and_push(news_list):
    try:
        existing_news = load_today_news()
        existing_ids = {item['id'] for item in existing_news}
        existing_dict = {item['id']: item for item in existing_news}
        
        new_items = []
        normal_items = []
        important_items = []
        
        for news_item in news_list:
            news_id = news_item.get('id')
            
            if news_id in existing_ids:
                existing_dict[news_id] = existing_dict.get(news_id, news_item)
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
        
        if not new_items:
            return list(existing_dict.values()), [], [], []
        
        pushed_items = []
        ignored_items = []
        
        if important_items:
            analysis_results = batch_analyze_news(important_items)
            
            for news_item in important_items:
                news_id = news_item.get('id')
                analysis = analysis_results.get(news_id)
                news_item['ai_analyzed'] = True
                
                if analysis:
                    news_item['ai_analysis'] = analysis
                    news_item['core_event'] = analysis.get('core_event', '')
                    
                    if is_important_news(analysis):
                        push_important_news(news_item, analysis)
                        news_item['pushed'] = True
                        pushed_items.append({
                            'title': news_item.get('title', ''),
                            'reason': analysis.get('reason', ''),
                            'core_event': analysis.get('core_event', '')
                        })
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
    register_thread('news_collector')
    cleanup_old_news()
    
    while True:
        try:
            heartbeat('news_collector')
            news_data = get_news_data(page=1, pagesize=30)
            
            result = process_news_with_ai_and_push(news_data or [])
            all_news = result[0]
            normal_items = result[1]
            pushed_items = result[2]
            ignored_items = result[3]
            
            save_news_data(all_news)
            
            total_new = len(normal_items) + len(pushed_items) + len(ignored_items)
            if total_new > 0:
                for item in normal_items:
                    info_logger.info(f"新增普通新闻，标题: {item.get('title', '')}")
                
                for item in pushed_items:
                    info_logger.info(f"新增重要新闻并推送，标题: {item['title']}，推送理由: {item['reason']}")
                
                for item in ignored_items:
                    info_logger.info(f"新增重要新闻但忽略，标题: {item['title']}，忽略理由: {item['reason']} (级别: {item['level']})")
                
                info_logger.info(f"本轮新增 {total_new} 条，当前共 {len(all_news)} 条")
            
            cleanup_old_news()
            
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
            info_logger.info(f"初始化 {len(news_data)} 条数据成功，普通{normal_count}条，重要{important_count}条")
        else:
            info_logger.info("初始化新闻数据：API未返回数据")
    except Exception as e:
        error_logger.error(f"初始化新闻数据失败: {e}")
