import time
from datetime import datetime
from news_processor import get_news_data, save_news_data, cleanup_old_news
from logger import setup_logging

error_logger, _, _ = setup_logging()

def news_collection_thread():
    cleanup_old_news()
    
    while True:
        try:
            news_data = get_news_data(page=1, pagesize=400)
            
            if news_data:
                save_news_data(news_data)
            
            cleanup_old_news()
            
        except Exception as e:
            error_logger.error(f"新闻采集线程异常: {e}")
        
        time.sleep(15)
