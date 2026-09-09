import os
import time
from datetime import datetime, timedelta
import calendar
from data.data_processor import get_sector_flow_data, save_realtime_data, load_realtime_data, cleanup_old_data, generate_daily_summary_for_date, load_daily_data, error_logger, data_logger, system_logger, get_top5_comparison_data, is_pushed, update_push_status, refresh_market_summary_cache, MARKET_FAST_REFRESH_SECONDS
from monitors.thread_monitor import heartbeat, register_thread, set_busy
from core.logger import get_logger

_last_morning_summary_date = None
_last_afternoon_summary_date = None
_last_cleanup_date = None
# 板块资金采集窗口机制：每个5分钟区间(如 9:40-9:45)内，首轮失败后每分钟再试一次，
# 每次内部仍尝试3次。只有进入下一个区间，上一个区间才算真正失败。
_last_sector_window_start = None   # 当前正在重试的区间起点(整5分钟, 'YYYY-MM-DD HH:MM')
_sector_window_last_attempt = None  # 当前区间内最后一次发起尝试的时间(整分钟, datetime)，用于控制重试节奏
_sector_window_attempt_count = 0    # 当前区间内已实际发起的尝试轮数(每次真正调用采集后 +1)
_sector_window_succeeded = False    # 当前区间是否已成功拿到数据
SECTOR_WINDOW_RETRY_MINUTES = 1     # 同一区间内失败后，隔多少分钟再试
SECTOR_WINDOW_MAX_ATTEMPTS = 5      # 一个5分钟区间内最多尝试多少轮(含首轮)

# ── 自适应采集频率（异动加密采样）──
# 平稳时维持5分钟一采；某板块相邻采样间净流入出现"大规模异动"（量级突变，
# 如 +15亿 → -80亿；稳定有规律的 10→15→20亿不算）时，采集区间切到1分钟，
# 首页折线在异动时段自动加密；连续 CALM_ROUNS 轮采样无新异动后回落回5分钟。
ADAPTIVE_FAST_WINDOW_MINUTES = 1    # 异动态采集间隔(分钟)——vk 定的硬上限，不许更快
ADAPTIVE_CALM_ROUNDS_TO_RELAX = 3   # 连续N轮平静采样后回落到5分钟
ADAPTIVE_JUMP_ABS_FLOOR = 20.0      # 单板块相邻采样 |Δ净流入| 绝对地板(亿)，低于此绝不判异动
ADAPTIVE_JUMP_RATIO = 4.0           # |Δ| 还需大于该板块当日近期 |Δ| 中位数的该倍数(有历史时)
ADAPTIVE_RHYTHM_SAMPLES = 8         # 参与节奏中位数计算的近期采样步数
_fast_mode = False                  # 当前是否处于1分钟加密采样态
_fast_calm_rounds = 0               # 加密态下连续"平静"的采样轮数
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

def _sector_net(sec):
    """取板块净流入(亿)，字段缺失/脏值返回 None。"""
    for key in ('net_flow', 'flow', 'total_flow'):
        try:
            value = float(sec.get(key))
        except (TypeError, ValueError):
            continue
        if value == value:  # 排除 NaN
            return value
    return None


def _evaluate_flow_jump(data, today, minute_key):
    """本轮采样相对上一采样是否出现"大规模资金异动"。

    口径对齐 vk 的描述：稳定有规律(10→15→20亿，步长接近)不算；
    量级突变(15亿→-80亿)算。任一板块满足：
      |Δ净流入| ≥ ADAPTIVE_JUMP_ABS_FLOOR(绝对地板)
      且 (当日节奏历史不足，或 |Δ| > ADAPTIVE_JUMP_RATIO × 近期|Δ|中位数)
    即判异动。返回 (是否异动, 描述文本)；任何异常都按"无异动"处理，绝不影响采集。
    """
    try:
        realtime = load_realtime_data(today)
        if not realtime or realtime.get('_invalid'):
            return False, ''
        keys = sorted(
            k for k in realtime.keys()
            if isinstance(k, str) and ':' in k and k != minute_key and isinstance(realtime.get(k), dict)
        )
        if not keys:
            return False, ''

        # 各板块当日 (时间, 净流入) 有序序列——节奏(近期步长)与上一采样都从这里取
        history = {}
        for k in keys:
            for sec in (realtime[k].get('data') or []):
                name = sec.get('name')
                if name:
                    history.setdefault(name, []).append((k, _sector_net(sec)))
        prev_key = keys[-1]
        cur_map = {}
        for sec in (data or []):
            name = sec.get('name')
            if name:
                cur_map[name] = _sector_net(sec)

        worst = None  # (板块名, |Δ|, 上一值, 当前值)
        for name, cur in cur_map.items():
            series = history.get(name) or []
            prev = series[-1][1] if series else None
            if cur is None or prev is None:
                continue
            abs_d = abs(cur - prev)
            if abs_d < ADAPTIVE_JUMP_ABS_FLOOR:
                continue
            rhythm = []
            for (_, v1), (_, v2) in zip(series, series[1:]):
                if v1 is None or v2 is None:
                    continue
                rhythm.append(abs(v2 - v1))
            rhythm = rhythm[-ADAPTIVE_RHYTHM_SAMPLES:]
            median = sorted(rhythm)[len(rhythm) // 2] if rhythm else 0.0
            if abs_d > ADAPTIVE_JUMP_RATIO * max(median, 1e-9):
                if worst is None or abs_d > worst[1]:
                    worst = (name, abs_d, prev, cur)
        if worst is None:
            return False, ''
        name, abs_d, prev, cur = worst
        return True, f"{name} 净流入 {prev:+.2f}亿 → {cur:+.2f}亿(变动 {abs_d:.2f}亿)"
    except Exception as e:
        error_logger.error(f"异动判频评估异常(不影响采集): {e}")
        return False, ''


def data_collection_thread():
    global _last_morning_summary_date, _last_afternoon_summary_date, _last_cleanup_date
    global _last_sector_window_start, _sector_window_last_attempt, _sector_window_attempt_count, _sector_window_succeeded
    global _fast_mode, _fast_calm_rounds
    register_thread('data_collector')
    system_logger.info("启动数据采集线程，每5分钟采集一次(检测到大规模资金异动时自动加密到1分钟)，区间内失败每隔1分钟重试直到下一个采集点...")

    trading_now = False

    while True:
        try:
            heartbeat('data_collector')
            now = datetime.now().astimezone()
            today = now.strftime('%Y-%m-%d')
            current_minute = now.minute
            current_hour = now.hour
            trading_now = is_trading_day(now) and is_trading_time(now)

            # 收盘/非交易日退出加密态（跨日不残留）
            if not trading_now and _fast_mode:
                _fast_mode = False
                _fast_calm_rounds = 0

            if trading_now:
                refresh_market_summary_cache()
            
            # 每天 0 点清理任务（通过日期变更触发）
            if _last_cleanup_date != today:
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
                _last_cleanup_date = today
            
            if should_generate_morning_summary(now):
                data_summary_logger.info(f"上午收盘后生成今日({today})的上午汇总...")
                success = generate_daily_summary_for_date(today)
                if success:
                    data_summary_logger.info(f"成功生成今日({today})的上午汇总")
                    _last_morning_summary_date = today
                    
                    if not is_pushed(today, '上午'):
                        try:
                            from pushers.notification_pusher import push_daily_summary
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
                            from pushers.notification_pusher import push_daily_summary
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
            
            # ── 板块资金采集窗口机制 ──
            # 当前时间所属采集区间的起点：平稳态5分钟一格(如 9:40-9:45 起点 9:40)；
            # 异动态1分钟一格(每分钟自成新区间 → 首轮立即采集，实现1分钟加密采样)
            window_minutes = ADAPTIVE_FAST_WINDOW_MINUTES if _fast_mode else 5
            window_start_minute = current_minute - (current_minute % window_minutes)
            window_start_key = now.replace(minute=window_start_minute, second=0, microsecond=0)
            window_start_str = window_start_key.strftime('%Y-%m-%d %H:%M')

            # 进入新区间：重置窗口状态，上个区间到此才算真正结束(无论成败)
            if _last_sector_window_start != window_start_str:
                _last_sector_window_start = window_start_str
                _sector_window_last_attempt = None
                _sector_window_attempt_count = 0
                _sector_window_succeeded = False

            # 已实际发起的尝试轮数(0 表示尚未在本区间尝试)
            attempt_index = _sector_window_attempt_count
            window_exhausted = attempt_index >= SECTOR_WINDOW_MAX_ATTEMPTS
            should_attempt = trading_now and not _sector_window_succeeded and not window_exhausted

            # 控制重试节奏：首轮立即触发；之后每 SECTOR_WINDOW_RETRY_MINUTES 分钟试一次。
            # 用「上次尝试时刻 + 间隔」与「当前整分钟」比较，避免被15s轮询误触发。
            if should_attempt and _sector_window_last_attempt is not None:
                next_allowed = _sector_window_last_attempt + timedelta(minutes=SECTOR_WINDOW_RETRY_MINUTES)
                # 对齐到整分钟比较，防止在间隔分钟内反复触发
                if now.replace(second=0, microsecond=0) < next_allowed.replace(second=0, microsecond=0):
                    should_attempt = False

            if should_attempt:
                _sector_window_attempt_count += 1
                _sector_window_last_attempt = now.replace(second=0, microsecond=0)
                if attempt_index == 0:
                    data_logger.info(f"进入板块采集区间 {window_start_str}，开始第1轮获取")
                else:
                    data_logger.info(f"板块采集区间 {window_start_str} 上轮失败，开始第{attempt_index + 1}轮重试")
                # THS 板块采集可能耗时很长(cookie刷新45s + 多次重试最坏约200s),
                # 期间打 busy,让 thread_monitor 用 BUSY_TIMEOUT(600s) 而非 DEFAULT_TIMEOUT(120s),
                # 否则监控会误判线程"stopped"并触发无意义的 /api/system/restart(还会因鉴权401刷屏)。
                set_busy('data_collector', True)
                try:
                    # 第1轮(attempt_index==0)本机直连(含cookie刷新);
                    # 第2轮起(attempt_index>=1)本机疑似被风控,切代理重试。
                    use_proxy = (attempt_index >= 1)
                    if use_proxy:
                        data_logger.info(f"本轮启用代理回退（本机IP疑似被风控）")
                    data = get_sector_flow_data(use_proxy=use_proxy)
                finally:
                    set_busy('data_collector', False)
                if data:
                    _sector_window_succeeded = True
                    minute_key = now.strftime('%H:%M')
                    success = save_realtime_data(today, minute_key, data)
                    if success:
                        retry_note = f"(区间{window_start_str}第{attempt_index + 1}轮成功)" if attempt_index > 0 else ""
                        data_logger.info(f"数据采集成功，获取{len(data)}个板块 {retry_note}")
                        # WebSocket通知前端数据已刷新
                        try:
                            from ws import push_event
                            push_event('data_update', {'type': 'sector_flow', 'date': today, 'time': minute_key, 'count': len(data)})
                        except Exception:
                            pass
                        # 资金异动检测（独立模块，异常绝不影响采集主循环）
                        try:
                            from analysis.anomaly_detector import detect_and_push
                            detect_and_push(today, minute_key, data)
                        except Exception as _ae:
                            error_logger.error(f"异动检测调用失败（不影响采集）: {_ae}")
                        # ── 自适应频率状态机：异动 → 1分钟加密采样；连续平静 → 回落5分钟 ──
                        try:
                            is_jump, jump_desc = _evaluate_flow_jump(data, today, minute_key)
                        except Exception:
                            is_jump, jump_desc = False, ''
                        if is_jump:
                            if not _fast_mode:
                                data_logger.info(f"检测到资金大规模异动（{jump_desc}），采集频率 5分钟 → 1分钟")
                            _fast_mode = True
                            _fast_calm_rounds = 0
                        elif _fast_mode:
                            _fast_calm_rounds += 1
                            if _fast_calm_rounds >= ADAPTIVE_CALM_ROUNDS_TO_RELAX:
                                data_logger.info("资金流恢复平稳，采集频率回落 1分钟 → 5分钟")
                                _fast_mode = False
                                _fast_calm_rounds = 0
                    else:
                        data_logger.error(f"保存实时数据失败")
                else:
                    data_logger.error(f"获取数据失败（区间{window_start_str}第{attempt_index + 1}轮）")
            elif trading_now and _sector_window_succeeded:
                data_logger.debug(f"板块采集区间 {window_start_str} 已成功，本轮跳过")
            elif trading_now and window_exhausted and not _sector_window_succeeded:
                data_logger.debug(f"板块采集区间 {window_start_str} 已尝试{SECTOR_WINDOW_MAX_ATTEMPTS}轮仍失败，等待下一区间")
            elif not trading_now:
                data_logger.debug(f"非交易时间，跳过数据采集")
        except Exception as e:
            error_logger.error(f"数据采集线程异常: {e}")
        
        time.sleep(MARKET_FAST_REFRESH_SECONDS if trading_now else 60)
