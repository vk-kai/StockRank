import os
import time
from datetime import datetime, timedelta
import calendar
from data_processor import get_sector_flow_data, save_realtime_data, load_realtime_data, cleanup_old_data, generate_daily_summary_for_date, load_daily_data, error_logger, data_logger, system_logger, get_top5_comparison_data
from thread_monitor import heartbeat, register_thread
from logger import get_logger

_last_morning_summary_date = None
_last_afternoon_summary_date = None
cleanup_logger = get_logger('cleanup_flow')

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

def is_morning_close(now):
    hour = now.hour
    minute = now.minute
    return hour == 11 and minute > 30 or hour == 12

def is_afternoon_close(now):
    return now.hour >= 15

def should_generate_morning_summary(now):
    global _last_morning_summary_date
    
    today = now.strftime('%Y-%m-%d')
    
    if _last_morning_summary_date == today:
        return False
    
    if is_morning_close(now):
        realtime_data = load_realtime_data(today)
        if realtime_data:
            return True
    
    return False

def should_generate_afternoon_summary(now):
    global _last_afternoon_summary_date
    
    today = now.strftime('%Y-%m-%d')
    
    if _last_afternoon_summary_date == today:
        return False
    
    if is_afternoon_close(now):
        realtime_data = load_realtime_data(today)
        if realtime_data:
            return True
    
    return False

def data_collection_thread():
    global _last_morning_summary_date, _last_afternoon_summary_date
    register_thread('data_collector')
    system_logger.info("启动数据采集线程，每5分钟采集一次数据...")
    
    while True:
        try:
            heartbeat('data_collector')
            now = datetime.now().astimezone()
            today = now.strftime('%Y-%m-%d')
            current_minute = now.minute
            current_hour = now.hour
            
            if current_hour == 0 and current_minute == 0:
                yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
                
                if _last_afternoon_summary_date != yesterday:
                    realtime_data = load_realtime_data(yesterday)
                    if realtime_data:
                        system_logger.info(f"生成昨天({yesterday})的每日汇总...")
                        success = generate_daily_summary_for_date(yesterday)
                        if success:
                            system_logger.info(f"成功生成昨天({yesterday})的每日汇总")
                            _last_afternoon_summary_date = yesterday
                        else:
                            system_logger.error(f"生成昨天({yesterday})的每日汇总失败")
                    
                    cleanup_result = cleanup_old_data()
                    if cleanup_result['cleaned']:
                        cleanup_logger.info(f"资金流向数据清理完成: 每日数据 {cleanup_result['daily_deleted']} 个, "
                                          f"实时数据 {cleanup_result['realtime_deleted']} 个, "
                                          f"释放空间 {cleanup_result['freed_bytes']} 字节")
                    else:
                        cleanup_logger.info(f"资金流向数据无需清理: {cleanup_result['reason']}")
            
            if should_generate_morning_summary(now):
                system_logger.info(f"上午收盘后生成今日({today})的上午汇总...")
                success = generate_daily_summary_for_date(today)
                if success:
                    system_logger.info(f"成功生成今日({today})的上午汇总")
                    _last_morning_summary_date = today
                    
                    # 发送飞书推送
                    try:
                        from feishu_pusher import push_daily_summary_feishu
                        comparison_data = get_top5_comparison_data(today)
                        if comparison_data:
                            push_result = push_daily_summary_feishu(comparison_data, period='上午')
                            if push_result:
                                system_logger.info(f"上午汇总飞书推送成功")
                            else:
                                system_logger.error(f"上午汇总飞书推送失败")
                    except Exception as e:
                        error_logger.error(f"上午汇总飞书推送异常: {e}")
                else:
                    system_logger.error(f"生成今日({today})的上午汇总失败")
            
            if should_generate_afternoon_summary(now):
                system_logger.info(f"下午收盘后生成今日({today})的每日汇总...")
                success = generate_daily_summary_for_date(today)
                if success:
                    system_logger.info(f"成功生成今日({today})的每日汇总")
                    _last_afternoon_summary_date = today
                    
                    # 发送飞书推送
                    try:
                        from feishu_pusher import push_daily_summary_feishu
                        comparison_data = get_top5_comparison_data(today)
                        if comparison_data:
                            push_result = push_daily_summary_feishu(comparison_data, period='下午')
                            if push_result:
                                system_logger.info(f"下午汇总飞书推送成功")
                            else:
                                system_logger.error(f"下午汇总飞书推送失败")
                    except Exception as e:
                        error_logger.error(f"下午汇总飞书推送异常: {e}")
                else:
                    system_logger.error(f"生成今日({today})的每日汇总失败")
            
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
                    data_logger.debug(f"非交易时间，跳过数据采集")
        except Exception as e:
            error_logger.error(f"数据采集线程异常: {e}")
        
        time.sleep(60)
