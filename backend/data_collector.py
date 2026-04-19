import os
import time
from datetime import datetime, timedelta
import calendar
from data_processor import get_sector_flow_data, save_realtime_data, load_realtime_data, cleanup_old_data, generate_daily_summary_for_date, error_logger, data_logger, system_logger
from thread_monitor import heartbeat, register_thread

def is_trading_day(date):
    if date.weekday() >= 5:
        return False
    return True

def is_trading_time(time):
    hour = time.hour
    minute = time.minute
    
    if hour == 9 and minute >= 30:
        return True
    if 10 <= hour < 11:
        return True
    if hour == 11 and minute <= 30:
        return True
    if 13 <= hour < 15:
        return True
    
    return False

def data_collection_thread():
    register_thread('data_collector')
    system_logger.info("启动数据采集线程，每5分钟采集一次数据...")
    
    cleanup_old_data()
    
    while True:
        try:
            heartbeat('data_collector')
            now = datetime.now().astimezone()
            today = now.strftime('%Y-%m-%d')
            current_minute = now.minute
            
            if now.hour == 0 and current_minute == 0:
                yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
                realtime_data = load_realtime_data(yesterday)
                if realtime_data:
                    system_logger.info(f"生成昨天({yesterday})的每日汇总...")
                    success = generate_daily_summary_for_date(yesterday)
                    if success:
                        system_logger.info(f"成功生成昨天({yesterday})的每日汇总")
                    else:
                        system_logger.error(f"生成昨天({yesterday})的每日汇总失败")
                cleanup_success = cleanup_old_data()
                if cleanup_success:
                    system_logger.info("清理过期数据成功")
                else:
                    system_logger.error("清理过期数据失败")
            
            if current_minute % 5 == 0:
                if is_trading_day(now) and is_trading_time(now):
                    data = get_sector_flow_data()
                    if data:
                        minute_key = now.strftime('%H:%M')
                        success = save_realtime_data(today, minute_key, data)
                        if success:
                            data_logger.info(f"数据采集成功，获取{len(data)}个板块")
                        else:
                            data_logger.error(f"保存实时数据失败")
                    else:
                        data_logger.error("获取数据失败")
                else:
                    data_logger.info(f"非交易时间，跳过数据采集")
        except Exception as e:
            error_logger.error(f"数据采集线程异常: {e}")
        
        time.sleep(60)
