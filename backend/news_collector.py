import time
from datetime import datetime
from news_processor import get_news_data, save_news_data, cleanup_old_news
from logger import setup_logging

error_logger, data_logger, system_logger = setup_logging()

def news_collection_thread():
    system_logger.info("启动新闻采集线程，每15秒采集一次新闻...")
    
    cleanup_old_news()
    
    while True:
        try:
            data_logger.info("开始采集新闻数据...")
            
            news_data = get_news_data(page=1, pagesize=400)
            
            if news_data:
                success = save_news_data(news_data)
                if success:
                    data_logger.info(f"新闻采集成功，获取 {len(news_data)} 条新闻")
                else:
                    data_logger.error("保存新闻数据失败")
            else:
                data_logger.warning("未获取到新闻数据")
            
            cleanup_old_news()
            
        except Exception as e:
            error_logger.error(f"新闻采集线程异常: {e}")
        
        time.sleep(15)
