import os
import time
from datetime import datetime, timedelta
import calendar
from data_processor import get_sector_flow_data, save_realtime_data, load_realtime_data, cleanup_old_data, generate_daily_summary_for_date, load_daily_data, error_logger, data_logger, system_logger, get_top5_comparison_data, is_pushed, update_push_status, refresh_market_summary_cache, MARKET_FAST_REFRESH_SECONDS
from thread_monitor import heartbeat, register_thread
from core.logger import get_logger

_last_morning_summary_date = None
_last_afternoon_summary_date = None
_last_sector_collect_key = None
cleanup_logger = get_logger('cleanup_flow')
data_summary_logger = get_logger('data_summary')

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
    if hour == 15 and minute == 0:
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
    global _last_morning_summary_date, _last_afternoon_summary_date, _last_sector_collect_key
    register_thread('data_collector')
    system_logger.info("启动数据采集线程，每5分钟采集一次数据...")
    
    trading_now = False

    while True:
        try:
            heartbeat('data_collector')
            now = datetime.now().astimezone()
            today = now.strftime('%Y-%m-%d')
            current_minute = now.minute
            current_hour = now.hour
            trading_now = is_trading_day(now) and is_trading_time(now)

            if trading_now:
                refresh_market_summary_cache()
            
            if current_hour == 0 and current_minute == 0:
                yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
                
                if _last_afternoon_summary_date != yesterday:
                    realtime_data = load_realtime_data(yesterday)
                    if realtime_data:
                        data_summary_logger.info(f"生成昨天({yesterday})的每日汇总...")
                        success = generate_daily_summary_for_date(yesterday)
                        if success:
                            data_summary_logger.info(f"成功生成昨天({yesterday})的每日汇总")
                            _last_afternoon_summary_date = yesterday
                        else:
                            data_summary_logger.error(f"生成昨天({yesterday})的每日汇总失败")
                    
                    cleanup_result = cleanup_old_data()
                    if cleanup_result['cleaned']:
                        cleanup_logger.info(f"资金流向数据清理完成: 每日数据 {cleanup_result['daily_deleted']} 个, "
                                          f"实时数据 {cleanup_result['realtime_deleted']} 个, "
                                          f"释放空间 {cleanup_result['freed_bytes']} 字节")
                    else:
                        cleanup_logger.info(f"资金流向数据无需清理: {cleanup_result['reason']}")
            
            if should_generate_morning_summary(now):
                data_summary_logger.info(f"上午收盘后生成今日({today})的上午汇总...")
                success = generate_daily_summary_for_date(today)
                if success:
                    data_summary_logger.info(f"成功生成今日({today})的上午汇总")
                    _last_morning_summary_date = today
                    
                    if not is_pushed(today, '上午'):
                        try:
                            from notification_pusher import push_daily_summary
                            comparison_data = get_top5_comparison_data(today)
                            if comparison_data:
                                push_result = push_daily_summary(comparison_data, period='上午')
                                if push_result:
                                    data_summary_logger.info(f"上午汇总飞书推送成功")
                                    update_push_status(today, '上午')
                                else:
                                    data_summary_logger.error(f"上午汇总飞书推送失败")
                            else:
                                data_summary_logger.error(f"获取TOP5对比数据失败")
                        except Exception as e:
                            error_logger.error(f"上午汇总消息推送异常: {e}")
                    else:
                        data_summary_logger.info(f"今日上午汇总已推送过，跳过重复推送")
                else:
                    data_summary_logger.error(f"生成今日({today})的上午汇总失败")
            
            if should_generate_afternoon_summary(now):
                data_summary_logger.info(f"下午收盘后生成今日({today})的每日汇总...")
                success = generate_daily_summary_for_date(today)
                if success:
                    data_summary_logger.info(f"成功生成今日({today})的每日汇总")
                    _last_afternoon_summary_date = today
                    
                    if not is_pushed(today, '下午'):
                        try:
                            from notification_pusher import push_daily_summary
                            comparison_data = get_top5_comparison_data(today)
                            if comparison_data:
                                push_result = push_daily_summary(comparison_data, period='下午')
                                if push_result:
                                    data_summary_logger.info(f"下午汇总飞书推送成功")
                                    update_push_status(today, '下午')
                                else:
                                    data_summary_logger.error(f"下午汇总飞书推送失败")
                            else:
                                data_summary_logger.error(f"获取TOP5对比数据失败")
                        except Exception as e:
                            error_logger.error(f"下午汇总消息推送异常: {e}")
                    else:
                        data_summary_logger.info(f"今日下午汇总已推送过，跳过重复推送")
                else:
                    data_summary_logger.error(f"生成今日({today})的每日汇总失败")
            
            sector_collect_key = now.strftime('%Y-%m-%d %H:%M')
            if current_minute % 5 == 0 and _last_sector_collect_key != sector_collect_key:
                _last_sector_collect_key = sector_collect_key
                if trading_now:
                    data = get_sector_flow_data()
                    if data:
                        minute_key = now.strftime('%H:%M')
                        success = save_realtime_data(today, minute_key, data)
                        if success:
                            data_logger.info(f"数据采集成功，获取{len(data)}个板块")
                            # WebSocket通知前端数据已刷新
                            try:
                                from ws import push_event
                                push_event('data_update', {'type': 'sector_flow', 'date': today, 'time': minute_key, 'count': len(data)})
                            except Exception:
                                pass
                            # 资金异动检测（独立模块，异常绝不影响采集主循环）
                            try:
                                from anomaly_detector import detect_and_push
                                detect_and_push(today, minute_key, data)
                            except Exception as _ae:
                                error_logger.error(f"异动检测调用失败（不影响采集）: {_ae}")
                        else:
                            data_logger.error(f"保存实时数据失败")
                    else:
                        data_logger.error("获取数据失败")
                else:
                    data_logger.debug(f"非交易时间，跳过数据采集")
        except Exception as e:
            error_logger.error(f"数据采集线程异常: {e}")
        
        time.sleep(MARKET_FAST_REFRESH_SECONDS if trading_now else 60)
