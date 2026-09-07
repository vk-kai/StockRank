import os
import time
import traceback
from datetime import datetime, timedelta
from data.news_processor import get_news_data, save_news_data, cleanup_old_news, load_today_news, get_recent_news, NEWS_DIR
from analysis.ai_analyzer import batch_analyze_news, is_important_news, set_heartbeat_callback, analyze_news, save_news_analysis, get_news_analysis, load_news_analysis_cache, clear_news_analysis_cache, summarize_daily_news
from pushers.notification_pusher import (
    ALL_AI_FILTER,
    ALL_DIRECT,
    IMPORTANT_AI_FILTER,
    IMPORTANT_DIRECT,
    get_enabled_news_channels,
    is_push_enabled,
    send_news_item_to_channels,
)
from monitors.stock_monitor import should_push_news
from core.logger import get_logger, cleanup_old_logs
from monitors.thread_monitor import heartbeat, register_thread, set_busy
import json

error_logger = get_logger('error')
news_logger = get_logger('news')
news_add_logger = get_logger('news_add')
news_important_logger = get_logger('news_important')
ai_logger = get_logger('ai')
cleanup_logger = get_logger('cleanup_news')

_last_cleanup_date = None
_last_news_summary_date = None


def _get_pushed_channels(news_item):
    pushed_channels = news_item.get('pushed_channels')
    if isinstance(pushed_channels, list):
        return set(pushed_channels)
    return set()


def _has_channel_pushed(news_item, channel_key):
    pushed_channels = news_item.get('pushed_channels')
    if isinstance(pushed_channels, list):
        return channel_key in pushed_channels
    return bool(news_item.get('pushed'))


def _mark_channel_pushed(news_item, channel_key):
    pushed_channels = _get_pushed_channels(news_item)
    pushed_channels.add(channel_key)
    news_item['pushed_channels'] = sorted(pushed_channels)
    news_item['pushed'] = True


def _record_push_results(news_item, results):
    for channel_key, _channel_name, success in results:
        if success:
            _mark_channel_pushed(news_item, channel_key)
    return any(success for _, _, success in results)

def ai_heartbeat():
    heartbeat('news_collector')

set_heartbeat_callback(ai_heartbeat)

# —— load_all_news_status 的 mtime 缓存 ——
# news_collection_thread 每 30 秒调用一次，原实现每次全量遍历解析 NEWS_DIR 下所有 JSON，
# 新闻文件多时 IO 开销显著。改为按目录签名(max_mtime, 文件数)缓存：签名不变即命中。
_news_status_cache = None
_news_status_signature = None


def _news_dir_signature():
    """返回 NEWS_DIR 的变更签名 (max_mtime, file_count)；目录无效/为空返回 (0, 0)。"""
    try:
        if not os.path.exists(NEWS_DIR):
            return (0, 0)
        files = [f for f in os.listdir(NEWS_DIR)
                 if f.endswith('.json')
                 and os.path.getsize(os.path.join(NEWS_DIR, f)) > 0]
        if not files:
            return (0, 0)
        max_mtime = max(os.path.getmtime(os.path.join(NEWS_DIR, f)) for f in files)
        return (max_mtime, len(files))
    except Exception:
        return (0, 0)


def _load_all_news_status_from_disk():
    """全量遍历 NEWS_DIR 所有 JSON，合并去重得到 {news_key: status}。"""
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
                                            'ai_analyzed': item.get('ai_analyzed', False),
                                            'pushed_channels': item.get('pushed_channels', [])
                                        }
                                    else:
                                        if item.get('pushed', False):
                                            all_status[key]['pushed'] = True
                                        if item.get('ai_analyzed', False):
                                            all_status[key]['ai_analyzed'] = True
                                        pushed_channels = item.get('pushed_channels', [])
                                        if isinstance(pushed_channels, list):
                                            merged_channels = set(all_status[key].get('pushed_channels', []))
                                            merged_channels.update(pushed_channels)
                                            all_status[key]['pushed_channels'] = sorted(merged_channels)
                except (json.JSONDecodeError, Exception) as e:
                    continue
    except Exception as e:
        error_logger.error(f"加载所有新闻状态失败: {e}")
    return all_status


def load_all_news_status(force_reload=False):
    """获取所有新闻的去重状态(被推送/AI分析标记)。

    带目录签名缓存：NEWS_DIR 文件 mtime/数量不变时直接返回缓存，避免每 30 秒全量重读。
    force_reload=True 时绕过缓存强制读盘（用于主动写入后立即可见）。
    """
    global _news_status_cache, _news_status_signature
    sig = _news_dir_signature()
    if not force_reload and _news_status_cache is not None and sig == _news_status_signature:
        return _news_status_cache
    all_status = _load_all_news_status_from_disk()
    _news_status_cache = all_status
    _news_status_signature = sig
    return all_status

def process_news_with_ai_and_push(news_list):
    try:
        from analysis.ai_analyzer import load_ai_config
        
        ai_config = load_ai_config()
        ai_enabled = ai_config and ai_config.get('enabled', False)
        push_enabled = is_push_enabled()
        
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
                news_item['pushed_channels'] = status.get('pushed_channels', [])
                news_item['core_event'] = ''
                normal_items.append(news_item)
                continue
            
            news_item['ai_analyzed'] = False
            news_item['pushed'] = False
            news_item['pushed_channels'] = []
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
            return list(existing_dict.values()), [], [], [], []
        
        pushed_items = []
        ignored_items = []
        pushed_recorded_ids = set()
        ignored_recorded_keys = set()

        def record_pushed(news_item, reason, core_event=''):
            news_id = news_item.get('id') or news_item.get('title', '')
            if news_id in pushed_recorded_ids:
                return
            pushed_recorded_ids.add(news_id)
            pushed_items.append({
                'title': news_item.get('title', ''),
                'reason': reason,
                'core_event': core_event
            })

        def record_ignored(news_item, reason, level=''):
            key = (news_item.get('id') or news_item.get('title', ''), reason, level)
            if key in ignored_recorded_keys:
                return
            ignored_recorded_keys.add(key)
            ignored_items.append({
                'title': news_item.get('title', ''),
                'reason': reason,
                'level': level
            })
        
        # 如果消息推送未启用，跳过所有推送逻辑
        if not push_enabled:
            ai_logger.info(f"消息推送已关闭，跳过重要新闻推送逻辑")
            # 重要新闻仍然进行AI分析，但不推送
            if important_items and ai_enabled:
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
                        # 不推送，只记录分析结果
                        record_ignored(news_item, f'{analysis.get("reason", "")}（消息推送已关闭）', analysis.get('level', ''))
                    else:
                        record_ignored(news_item, 'AI分析失败（消息推送已关闭）', '未知')
                
                for news_item in important_items[5:]:
                    news_item['ai_analyzed'] = False
                    news_item['core_event'] = ''
        else:
            channels = get_enabled_news_channels()
            analysis_target_map = {}
            if ai_enabled:
                for channel in channels:
                    if channel['mode'] == ALL_AI_FILTER:
                        for item in new_items:
                            news_id = item.get('id')
                            if news_id:
                                analysis_target_map[news_id] = item
                    elif channel['mode'] == IMPORTANT_AI_FILTER:
                        for item in important_items:
                            news_id = item.get('id')
                            if news_id:
                                analysis_target_map[news_id] = item
            elif any(channel['mode'] == ALL_AI_FILTER for channel in channels):
                ai_logger.warning("存在“全部新闻AI筛选”推送模式，但AI未开启，相关渠道将跳过新闻推送")

            analysis_results = {}
            items_to_analyze = list(analysis_target_map.values())
            if items_to_analyze:
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

            for news_item in new_items:
                source_important = news_item.get('importance') == '3'
                analysis = analysis_results.get(news_item.get('id'))
                direct_channels = []
                ai_channels = []

                for channel in channels:
                    if _has_channel_pushed(news_item, channel['key']):
                        continue

                    mode = channel['mode']
                    if mode == ALL_DIRECT:
                        direct_channels.append(channel)
                    elif mode == IMPORTANT_DIRECT and source_important:
                        direct_channels.append(channel)
                    elif mode == IMPORTANT_AI_FILTER and source_important:
                        if ai_enabled:
                            ai_channels.append(channel)
                        else:
                            direct_channels.append(channel)
                    elif mode == ALL_AI_FILTER:
                        if ai_enabled:
                            ai_channels.append(channel)
                        else:
                            record_ignored(news_item, 'AI未开启，无法执行全部新闻AI筛选', '未分析')

                # WebSocket实时推送：所有新闻都推送到前端，前端根据设置过滤
                try:
                    from ws import push_event
                    push_event('news', news_item)
                except Exception:
                    pass

                if direct_channels:
                    reason = '全部新闻直接推送' if any(channel['mode'] == ALL_DIRECT for channel in direct_channels) else '重要新闻直接推送'
                    results = send_news_item_to_channels(news_item, None, direct_channels)
                    if _record_push_results(news_item, results):
                        record_pushed(news_item, reason, news_item.get('core_event', ''))

                if ai_channels:
                    news_item['ai_analyzed'] = True
                    if analysis:
                        if is_important_news(analysis):
                            results = send_news_item_to_channels(news_item, analysis, ai_channels)
                            if _record_push_results(news_item, results):
                                record_pushed(news_item, analysis.get('reason', ''), analysis.get('core_event', ''))
                        else:
                            record_ignored(news_item, analysis.get('reason', ''), analysis.get('level', ''))
                    else:
                        record_ignored(news_item, 'AI分析失败', '未知')
        
        # 股票匹配推送（仅在消息推送启用时执行）
        if push_enabled:
            channels = get_enabled_news_channels()
            for news_item in new_items:
                should_push, matched_stocks = should_push_news(news_item)
                target_channels = [
                    channel for channel in channels
                    if not _has_channel_pushed(news_item, channel['key'])
                ]
                if should_push and target_channels:
                    stock_names = "、".join([s['name'] for s in matched_stocks])
                    parts = [f"匹配股票：{stock_names}"]
                    results = send_news_item_to_channels(news_item, news_item.get('ai_analysis'), target_channels, prefix_lines=parts)
                    if _record_push_results(news_item, results):
                        record_pushed(news_item, f"匹配股票：{stock_names}", news_item.get('core_event', ''))
        else:
            ai_logger.info(f"消息推送已关闭，跳过股票匹配推送逻辑")
        
        normal_items = [item for item in normal_items if not item.get('pushed')]
        return list(existing_dict.values()), normal_items, pushed_items, ignored_items, new_items
                
    except Exception as e:
        error_logger.error(f"处理新闻AI分析和推送异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        return news_list, [], [], [], []

def _background_analyze_news(new_items):
    """后台批量分析新新闻"""
    try:
        set_busy('news_collector', True)
        
        from analysis.ai_analyzer import clean_text, truncate_text
        
        for item in new_items:
            news_id = item.get('id')
            title = item.get('title', '')
            content = item.get('content', '')
            
            if not news_id or not title:
                continue
            
            # 检查是否已有缓存
            cached = get_news_analysis(news_id)
            if cached:
                continue
            
            heartbeat('news_collector')
            
            title_clean = clean_text(title)
            content_clean = truncate_text(clean_text(content), 1500)
            
            result = analyze_news(title_clean, content_clean)

            # 预算超限时立即停止后续分析(call_ai_api 抛 AIBudgetExceeded → analyze_news 返回失败 message)
            _msg = str(result.get('message', ''))
            if '预算' in _msg or 'budget' in _msg.lower():
                error_logger.warning(f"后台新闻AI分析因预算超限停止: {_msg}")
                break

            if result.get('success') and result.get('analysis'):
                save_news_analysis(news_id, result['analysis'], result.get('duration', 0))
                news_add_logger.debug(f"新闻AI分析完成: {title[:30]}")
            else:
                news_add_logger.debug(f"新闻AI分析失败: {title[:30]} - {result.get('message', '')}")
            
    except Exception as e:
        error_logger.error(f"后台新闻AI分析异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
    finally:
        set_busy('news_collector', False)


def _run_news_summary(auto=False):
    """执行新闻热点总结（同步，在后台线程中调用）"""
    from core.config import AI_NEWS_SUMMARY_RESULT_FILE, AI_NEWS_SUMMARY_STATUS_FILE
    import json as _json

    now = datetime.now()
    today = now.strftime('%Y-%m-%d')

    # 加载所有本地保存的新闻
    all_news_result = get_recent_news(1, 10000)
    news_items = all_news_result.get('news', [])

    if not news_items:
        ai_logger.info("新闻热点总结：无新闻可总结")
        return

    ai_logger.info(f"新闻热点总结：开始总结 {len(news_items)} 条新闻（{'自动' if auto else '手动'}）")

    # 保存运行状态
    status_data = {
        'status': 'running',
        'start_time': now.astimezone().isoformat(),
        'date': today,
        'auto': auto
    }
    try:
        with open(AI_NEWS_SUMMARY_STATUS_FILE, 'w', encoding='utf-8') as f:
            _json.dump(status_data, f, ensure_ascii=False)
    except Exception:
        pass

    result = summarize_daily_news(news_items)

    if result.get('success') and result.get('analysis'):
        # 保存总结结果（只保留最近一次）
        try:
            with open(AI_NEWS_SUMMARY_RESULT_FILE, 'w', encoding='utf-8') as f:
                f.write(result['analysis'])
        except Exception as e:
            error_logger.error(f"保存新闻总结结果失败: {e}")

        # 保存完成状态
        status_data = {
            'status': 'completed',
            'end_time': datetime.now().astimezone().isoformat(),
            'date': today,
            'auto': auto
        }
        try:
            with open(AI_NEWS_SUMMARY_STATUS_FILE, 'w', encoding='utf-8') as f:
                _json.dump(status_data, f, ensure_ascii=False)
        except Exception:
            pass

        ai_logger.info(f"新闻热点总结完成（{'自动' if auto else '手动'}），日期: {today}")

        # 推送到飞书/微信
        try:
            _push_news_summary(result['analysis'], today)
        except Exception as e:
            error_logger.error(f"新闻总结推送失败: {e}")
    else:
        # 保存失败状态
        status_data = {
            'status': 'failed',
            'message': result.get('message', '总结失败'),
            'end_time': datetime.now().astimezone().isoformat(),
            'date': today,
            'auto': auto
        }
        try:
            with open(AI_NEWS_SUMMARY_STATUS_FILE, 'w', encoding='utf-8') as f:
                _json.dump(status_data, f, ensure_ascii=False)
        except Exception:
            pass

        ai_logger.error(f"新闻热点总结失败: {result.get('message', '未知错误')}")


def _push_news_summary(analysis_content, date_str):
    """将新闻总结推送到飞书和微信"""
    from pushers.feishu_pusher import send_feishu_message
    from pushers.wechat_pusher import send_wechat_message

    title = f"明日热点前瞻（{date_str}）"

    # 截取前2000字符作为推送内容（避免过长）
    content = analysis_content[:2000] if len(analysis_content) > 2000 else analysis_content

    # 推送飞书
    try:
        send_feishu_message(title, content)
        ai_logger.info("新闻总结已推送到飞书")
    except Exception as e:
        error_logger.error(f"新闻总结推送飞书失败: {e}")

    # 推送微信
    try:
        send_wechat_message(title, content)
        ai_logger.info("新闻总结已推送到微信")
    except Exception as e:
        error_logger.error(f"新闻总结推送微信失败: {e}")


def news_collection_thread():
    global _last_cleanup_date, _last_news_summary_date
    register_thread('news_collector')

    while True:
        try:
            heartbeat('news_collector')
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            current_hour = now.hour
            current_minute = now.minute

            # 每晚20点自动触发新闻热点总结（留有一定的容差范围）
            if current_hour == 20:
                if _last_news_summary_date != today:
                    _last_news_summary_date = today
                    try:
                        _run_news_summary(auto=True)
                    except Exception as e:
                        error_logger.error(f"每晚20点自动新闻总结失败: {e}")

            # 每天 0 点清理任务（通过日期变更触发）
            if _last_cleanup_date != today:
                cleanup_logger.info("开始执行每日清理任务...")
                
                # 清理新闻数据
                news_cleanup_result = cleanup_old_news()
                if news_cleanup_result['cleaned']:
                    cleanup_logger.info(f"新闻数据清理完成: 删除 {news_cleanup_result['deleted_count']} 个文件，"
                                      f"释放空间 {news_cleanup_result['freed_bytes']} 字节")
                else:
                    cleanup_logger.info(f"新闻数据无需清理: {news_cleanup_result['reason']}")
                
                # 清理新闻AI分析缓存（每天凌晨清空）
                ai_cache_cleaned = clear_news_analysis_cache()
                if ai_cache_cleaned:
                    cleanup_logger.info("新闻AI分析缓存已清空，第二天将重新分析")
                else:
                    cleanup_logger.info("新闻AI分析缓存清理失败或无需清理")
                
                # 清理日志文件
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
            all_new_items = result[4]
            
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
            
            # 有新新闻时，触发后台AI分析（所有新增新闻，含重要新闻）
            if actual_new_count > 0 and all_new_items:
                from analysis.ai_analyzer import load_ai_config
                ai_config = load_ai_config()
                if ai_config and ai_config.get('enabled'):
                    import threading as _threading
                    items_to_analyze = [item for item in all_new_items if item.get('id') and item.get('title')]
                    if items_to_analyze:
                        thread = _threading.Thread(target=_background_analyze_news, args=(items_to_analyze,))
                        thread.daemon = True
                        thread.start()
            
        except Exception as e:
            error_logger.error(f"新闻采集线程异常: {e}")
            error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        
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
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
