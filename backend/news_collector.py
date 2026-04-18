import time
from datetime import datetime
from news_processor import get_news_data, save_news_data, cleanup_old_news, load_today_news
from ai_analyzer import analyze_news_with_ai, is_important_news
from feishu_pusher import push_important_news
from stock_monitor import should_push_news
from logger import setup_logging

error_logger, info_logger, _ = setup_logging()

def process_news_with_ai_and_push(news_list):
    try:
        existing_news = load_today_news()
        existing_ids = {item['id'] for item in existing_news}
        existing_dict = {item['id']: item for item in existing_news}
        new_count = 0
        
        for news_item in news_list:
            news_id = news_item.get('id')
            
            if news_id in existing_ids:
                existing_dict[news_id] = existing_dict.get(news_id, news_item)
                continue
            
            new_count += 1
            news_item['ai_analyzed'] = False
            news_item['pushed'] = False
            news_item['core_event'] = ''
            
            if news_item.get('importance') == '3':
                news_title = news_item.get('title', '')[:30]
                info_logger.info(f"新增重要新闻「{news_title}」，开始AI分析")
                
                analysis_result = analyze_news_with_ai(news_item)
                news_item['ai_analyzed'] = True
                
                if analysis_result:
                    news_item['ai_analysis'] = analysis_result
                    news_item['core_event'] = analysis_result.get('core_event', '')
                    
                    if is_important_news(analysis_result):
                        push_important_news(news_item, analysis_result)
                        news_item['pushed'] = True
                        info_logger.info(f"新闻「{news_title}」AI分析完成，已推送")
                    else:
                        reason = analysis_result.get('reason', '影响级别不足')
                        info_logger.info(f"新闻「{news_title}」AI分析完成，忽略推送，理由：{reason[:50]}")
                else:
                    info_logger.info(f"新闻「{news_title}」AI分析返回空结果")
            else:
                news_item['ai_analyzed'] = True
            
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
            
            existing_dict[news_id] = news_item
        
        return list(existing_dict.values()), new_count
                
    except Exception as e:
        error_logger.error(f"处理新闻AI分析和推送异常: {e}")
        return news_list

def news_collection_thread():
    cleanup_old_news()
    
    while True:
        try:
            info_logger.info("开始采集新闻数据...")
            news_data = get_news_data(page=1, pagesize=30)
            
            all_news, new_count = process_news_with_ai_and_push(news_data or [])
            save_news_data(all_news)
            info_logger.info(f"新增 {new_count} 条新闻，保存数据完成共 {len(all_news)} 条")
            
            cleanup_old_news()
            
        except Exception as e:
            error_logger.error(f"新闻采集线程异常: {e}")
        
        info_logger.info("等待30秒后进行下一次采集...")
        time.sleep(30)
        
def init_news_data():
    try:
        news_data = get_news_data(page=1, pagesize=30)
        if news_data:
            for item in news_data:
                item['ai_analyzed'] = True
                item['pushed'] = True
                if 'core_event' not in item:
                    item['core_event'] = ''
            save_news_data(news_data)
            info_logger.info(f"初始化新闻数据完成，共 {len(news_data)} 条（全部标记为已分析）")
        else:
            info_logger.info("初始化新闻数据：API未返回数据")
    except Exception as e:
        error_logger.error(f"初始化新闻数据失败: {e}")
