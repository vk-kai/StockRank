from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
import threading
import json
import os
import re
from config import DAILY_DIR, REALTIME_DIR, AI_DAILY_RESULT_FILE, AI_DAILY_STATUS_FILE
from data_processor import (
    load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, latest_data, load_daily_data, 
    load_realtime_data, error_logger, get_market_overview, get_accumulated_top_sectors,
    get_top5_comparison_data, get_sector_stocks, load_market_summary_cache,
    refresh_market_summary_cache, is_market_summary_complete, get_global_market_indices, get_ai_chain_indicators,
    get_market_map_sectors, get_market_map_stocks, get_market_map_all, get_market_map_tree, refresh_market_map_cache
)
from data_collector import is_trading_day, is_trading_time, is_morning_close, is_afternoon_close
from anomaly_detector import (
    detect_for_snapshot, detect_full_day, list_alerts,
    load_config as load_anomaly_config, save_config as save_anomaly_config,
    get_baseline, build_baseline
)
from margin_collector import get_stock_margin_series, trigger_ondemand_update_async, get_all_latest_margin_net_inflow
from ai_analyzer import analyze_daily_flow, analyze_news, get_news_analysis as get_cached_news_analysis
from intraday_timeline import get_stock_hover_summary
from market_map_snapshot import get_points_status, get_snapshot as get_market_map_snapshot, SNAPSHOT_TIMES
from market_map_push_store import load_market_map_push, save_market_map_push, clear_market_map_push
import stock_scorer
from logger import get_logger

flow_bp = Blueprint('flow', __name__, url_prefix='/api/flow')
system_logger = get_logger('system')

# AI分析状态
ai_analysis_status = {
    'status': 'idle',  # idle, running, completed, failed
    'message': '',
    'progress': 0,  # 0-100
    'step': '',  # 当前步骤描述
    'start_time': None,
    'end_time': None
}
ai_analysis_lock = threading.Lock()

@flow_bp.route('/global-indices', methods=['GET'])
def global_indices():
    """获取全球主要股市指数（东方财富为主，新浪兜底）"""
    try:
        data = get_global_market_indices()
        if data:
            return jsonify({'success': True, 'data': data})
        return jsonify({'success': False, 'error': '获取全球指数数据失败'}), 500
    except Exception as e:
        error_msg = f"全球指数接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/global-indices]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/ai-chain', methods=['GET'])
def ai_chain():
    """获取AI产业链外部环境温度计（7个领先指标：英伟达/费城半导体/台积电/SK海力士/三星/美元指数/美债10年）"""
    try:
        data = get_ai_chain_indicators()
        if data:
            return jsonify({'success': True, 'data': data})
        return jsonify({'success': False, 'error': '获取AI产业链指标失败'}), 500
    except Exception as e:
        error_msg = f"AI产业链接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/ai-chain]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map', methods=['GET'])
def market_map():
    """获取大盘云图三级嵌套数据（申万一级→二级→个股）。
    行业+市值来自东方财富缓存（低频），涨跌幅来自新浪实时行情。"""
    try:
        data = get_market_map_tree()
        if data:
            return jsonify({'success': True, 'data': data})
        return jsonify({'success': False, 'error': '获取大盘云图数据失败'}), 500
    except Exception as e:
        error_msg = f"大盘云图接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/market-map]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-structure', methods=['GET'])
def market_map_structure():
    """大盘云图首屏骨架：只读行业+市值本地缓存，涨跌幅全部0%（不请求新浪），秒开。
    前端拿到后先渲染灰色云图，再调 /market-map 取实时涨跌幅二次上色。"""
    try:
        data = get_market_map_tree(include_changes=False)
        if data:
            return jsonify({'success': True, 'data': data})
        return jsonify({'success': False, 'error': '暂无行业缓存，请先点击「行业库」更新'})
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/market-map-structure]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-refresh-cache', methods=['POST'])
def market_map_refresh():
    """手动刷新大盘云图行业+市值缓存（东方财富，低频调用）"""
    try:
        cache = refresh_market_map_cache()
        if cache:
            return jsonify({'success': True, 'message': f'缓存已更新，共{cache["count"]}只股票', 'count': cache['count']})
        return jsonify({'success': False, 'error': '缓存刷新失败'}), 500
    except Exception as e:
        error_logger.error(f"大盘云图缓存刷新错误: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-push', methods=['GET'])
def market_map_push_get():
    doc = load_market_map_push()
    return jsonify({
        'success': True,
        'data': {
            'source': doc.get('source') or '',
            'run_id': int(doc.get('run_id') or 0),
            'updated_at': doc.get('updated_at'),
            'count': len(doc.get('stocks') or []),
            'stocks': doc.get('stocks') or [],
        }
    })


@flow_bp.route('/market-map-push', methods=['POST'])
def market_map_push_save():
    try:
        payload = request.get_json() or {}
        doc = save_market_map_push(payload)
        return jsonify({
            'success': True,
            'message': '已保存最新推送股票',
            'data': {
                'source': doc.get('source') or '',
                'run_id': int(doc.get('run_id') or 0),
                'updated_at': doc.get('updated_at'),
                'count': len(doc.get('stocks') or []),
            }
        })
    except Exception as e:
        error_logger.error(f"大盘云图推送保存失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-push', methods=['DELETE'])
def market_map_push_clear():
    clear_market_map_push()
    return jsonify({'success': True, 'message': '已清空推送股票'})


@flow_bp.route('/market-map-stocks', methods=['GET'])
def market_map_stocks():
    """获取指定板块下的个股（云图下钻，新浪数据源）"""
    sector_code = request.args.get('sector', '').strip()
    if not sector_code:
        return jsonify({'success': False, 'error': '缺少板块代码参数 sector'}), 400
    try:
        data = get_market_map_stocks(sector_code)
        if data:
            return jsonify({'success': True, 'data': data})
        return jsonify({'success': False, 'error': '获取板块个股数据失败'}), 500
    except Exception as e:
        error_msg = f"板块个股接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/market-map-stocks]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-snapshots', methods=['GET'])
def market_map_snapshots_list():
    """大盘云图复盘：返回今天 10 个半小时整点的抓取状态（前端时间按钮亮/灰用）。"""
    try:
        date_str, points = get_points_status()
        return jsonify({'success': True, 'date': date_str, 'points': points})
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/market-map-snapshots]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-snapshot', methods=['GET'])
def market_map_snapshot_by_time():
    """大盘云图复盘：返回某时间点(如 10:00)的完整快照 data，结构同 /market-map。"""
    t = (request.args.get('time') or '').strip()
    if t not in SNAPSHOT_TIMES:
        return jsonify({'success': False, 'error': '缺少或非法的 time 参数'}), 400
    try:
        data = get_market_map_snapshot(t)
        if data:
            return jsonify({'success': True, 'data': data, 'time': t})
        return jsonify({'success': False, 'message': '该时间点暂无快照'}), 404
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/market-map-snapshot]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/stock-financing', methods=['GET'])
def stock_financing():
    """获取个股近期融资净买入额时间序列（云图单击弹窗柱状图用）。
    数据来自上交所/深交所官方（akshare），每日 09:05 缓存。
    若请求时该股票无数据，则后台触发一次当日按需更新（每天最多一次），
    前端据 updating 字段决定是否提示"更新中"并稍后重试。"""
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'success': False, 'error': '缺少参数 code'}), 400
    try:
        data = get_stock_margin_series(code)
        updating = False
        if not data.get('series'):
            updating = trigger_ondemand_update_async()
        return jsonify({'success': True, 'data': data, 'updating': bool(updating)})
    except Exception as e:
        error_msg = f"个股融资数据接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/stock-financing]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/market-map-margin', methods=['GET'])
def market_map_margin():
    """大盘云图融资净流入着色：全市场每只标的最新一日融资净买入额(Δ融资余额)。
    只读融资融券每日缓存，不触发抓取。返回 {success, latest_date, map:{裸6位code: 净流入额}}。"""
    try:
        res = get_all_latest_margin_net_inflow()
        return jsonify({'success': True, 'latest_date': res['latest_date'], 'map': res['map']})
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/market-map-margin]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# AI 批量股票打分（大盘云图第三着色维度）
# ============================================================
@flow_bp.route('/stock-scores', methods=['GET'])
def stock_scores_map():
    """大盘云图 AI 打分着色：返回 {success, run_id, scored_at, count, map:{裸6位code:{score,label,reason}}, buckets}。
    只读 data/stock_scores/scores.json，不触发打分。前端有打分数据时下拉框可切换'着色：AI打分'。"""
    try:
        return jsonify(stock_scorer.get_scores_payload())
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/stock-scores]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/stock-scores/start', methods=['POST'])
def stock_scores_start():
    """启动一轮 AI 批量打分（异步后台线程）。body 可选 {scope:'all'|'missing'|'insufficient'}。
    scope=missing 只补未评分；insufficient 只重评 reason 含"信息不足"的。兼容旧 {only_failed:bool}。
    running 中且线程存活 → 返回当前进度，不重复启动。"""
    try:
        payload = request.get_json(silent=True) or {}
        scope = (payload.get('scope') or '').strip()
        if not scope:
            scope = 'missing' if payload.get('only_failed') else 'all'
        return jsonify(stock_scorer.start_scoring(scope=scope))
    except Exception as e:
        error_logger.error(f"启动股票打分失败: {e}")
        return jsonify({'success': False, 'message': f'启动失败: {str(e)[:100]}'}), 500


@flow_bp.route('/stock-scores/status', methods=['GET'])
def stock_scores_status():
    """查询打分进度：{status: idle|running|completed|failed|interrupted, progress, step, total, done, failed, ...}。
    interrupted=上次未完成（进程重启）；completed/failed 终态带 ended_at、message。"""
    try:
        return jsonify({'success': True, **stock_scorer.get_status()})
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/stock-scores/status]: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@flow_bp.route('/stock-scores/stop', methods=['POST'])
def stock_scores_stop():
    """协作式停止：set 取消标志，当前批次完成后退出，已评分结果保留。"""
    try:
        return jsonify(stock_scorer.stop_scoring())
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@flow_bp.route('/intraday-timeline', methods=['GET'])
def intraday_timeline():
    """盘中事件时间轴：基于资金流快照、新闻缓存生成结构化事件。"""
    date_str = request.args.get('date', '').strip() or None
    try:
        return jsonify(get_intraday_timeline(date_str))
    except Exception as e:
        error_msg = f"盘中事件轴接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/intraday-timeline]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flow_bp.route('/stock-hover-summary', methods=['GET'])
def stock_hover_summary():
    """大盘云图/板块个股 hover 摘要。"""
    code = request.args.get('code', '').strip()
    sector = request.args.get('sector', '').strip()
    name = request.args.get('name', '').strip()
    sector_name = request.args.get('sector_name', '').strip()
    if not code:
        return jsonify({'success': False, 'error': '缺少参数 code'}), 400
    try:
        return jsonify(get_stock_hover_summary(code, sector, name, sector_name))
    except Exception as e:
        error_msg = f"个股 hover 摘要接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/stock-hover-summary]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _update_ai_status(status, message, progress, step):
    """更新AI分析状态"""
    global ai_analysis_status
    with ai_analysis_lock:
        ai_analysis_status['status'] = status
        ai_analysis_status['message'] = message
        ai_analysis_status['progress'] = progress
        ai_analysis_status['step'] = step
        if status == 'completed' or status == 'failed':
            ai_analysis_status['end_time'] = datetime.now().astimezone().isoformat()

def _is_realtime_data_invalid(realtime_data):
    if not realtime_data:
        return True
    if realtime_data.get('_invalid'):
        return True
    time_keys = [k for k in realtime_data.keys() if not k.startswith('_')]
    if not time_keys:
        return True
    return False

def _get_latest_from_realtime_data(realtime_data):
    if not realtime_data or realtime_data.get('_invalid'):
        return None, None
    time_keys = sorted([k for k in realtime_data.keys() if not k.startswith('_')], reverse=True)
    if not time_keys:
        return None, None
    last_time_key = time_keys[0]
    last_record = realtime_data[last_time_key]
    if last_record and 'data' in last_record:
        return last_record['data'], last_record.get('timestamp')
    return None, None

def _get_latest_available_cached_flow(exclude_date=None):
    recent_history = load_recent_daily_data(7)
    if not recent_history:
        return None, None

    for latest_date in sorted(recent_history.keys(), reverse=True):
        if exclude_date and latest_date == exclude_date:
            continue
        latest_record = recent_history[latest_date]
        if latest_record and isinstance(latest_record, list) and len(latest_record) > 0:
            return latest_record, latest_date

    return None, None

def _has_today_market_summary(summary, now):
    if not is_market_summary_complete(summary):
        return False

    timestamp_text = summary.get('turnover_timestamp') or summary.get('timestamp')
    if not timestamp_text:
        return False

    try:
        timestamp = datetime.fromisoformat(timestamp_text)
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        return timestamp.astimezone(now.tzinfo).date() == now.date()
    except Exception:
        return False

@flow_bp.route('/current', methods=['GET'])
def get_current_flow():
    try:
        now = datetime.now().astimezone()
        today = now.strftime('%Y-%m-%d')
        
        if not is_trading_day(now) or not is_trading_time(now):
            today_daily_record = load_daily_data(today)
            if today_daily_record and 'data' in today_daily_record:
                period_msg = ''
                if is_afternoon_close(now):
                    period_msg = '下午收盘后，'
                elif is_morning_close(now):
                    period_msg = '上午收盘后，'
                return jsonify({
                    'success': True,
                    'data': today_daily_record['data'],
                    'timestamp': today_daily_record.get('timestamp', datetime.now().astimezone().isoformat()),
                    'message': f'{period_msg}返回今日汇总数据'
                })
            
            realtime_data = load_realtime_data(today)
            data, timestamp = _get_latest_from_realtime_data(realtime_data)
            if data:
                period_msg = '非交易时间，'
                if is_afternoon_close(now):
                    period_msg = '下午收盘后，'
                elif is_morning_close(now):
                    period_msg = '上午收盘后，'
                return jsonify({
                    'success': True,
                    'data': data,
                    'timestamp': timestamp or datetime.now().astimezone().isoformat(),
                    'message': f'{period_msg}返回今日最新数据'
                })
            
            if latest_data:
                return jsonify({
                    'success': True,
                    'data': latest_data,
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'message': '非交易时间，返回缓存数据'
                })
            recent_history = load_recent_daily_data(7)
            if recent_history:
                dates_sorted = sorted(recent_history.keys(), reverse=True)
                if dates_sorted:
                    latest_date = dates_sorted[0]
                    latest_record = recent_history[latest_date]
                    if latest_record and isinstance(latest_record, list) and len(latest_record) > 0:
                        return jsonify({
                            'success': True,
                            'data': latest_record,
                            'timestamp': datetime.now().astimezone().isoformat(),
                            'message': f'非交易时间，返回最近历史数据({latest_date})'
                        })
            
            return jsonify({
                'success': True,
                'data': [],
                'timestamp': datetime.now().astimezone().isoformat(),
                'message': '非交易时间，无可用数据'
            })
        else:
            realtime_data = load_realtime_data(today)
            data, timestamp = _get_latest_from_realtime_data(realtime_data)
            if data:
                time_keys = sorted([k for k in realtime_data.keys() if not k.startswith('_')], reverse=True)
                last_time_key = time_keys[0] if time_keys else ''
                return jsonify({
                    'success': True,
                    'data': data,
                    'timestamp': timestamp or datetime.now().astimezone().isoformat(),
                    'message': f'交易时间，返回最新实时数据({last_time_key})'
                })
            
            today_daily_record = load_daily_data(today)
            if today_daily_record and 'data' in today_daily_record:
                return jsonify({
                    'success': True,
                    'data': today_daily_record['data'],
                    'timestamp': today_daily_record.get('timestamp', datetime.now().astimezone().isoformat()),
                    'message': '交易时间，返回今日汇总数据'
                })
            
            if latest_data:
                return jsonify({
                    'success': True,
                    'data': latest_data,
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'message': '交易时间，返回缓存数据'
                })
            
            system_logger.info("交易时间且无当天缓存数据，跳过同步抓取并返回历史缓存")
            latest_record, latest_date = _get_latest_available_cached_flow(exclude_date=today)
            if latest_record:
                return jsonify({
                    'success': True,
                    'data': latest_record,
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'message': f'No current-day cache; returning cached flow data from {latest_date}'
                })

            system_logger.warning("No cached flow data; skipped synchronous crawl in /api/flow/current")
            new_data = []
            if new_data:
                return jsonify({
                    'success': True,
                    'data': new_data,
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'message': '交易时间，成功获取最新板块数据'
                })
            else:
                return jsonify({
                    'success': True,
                    'data': [],
                    'timestamp': datetime.now().astimezone().isoformat(),
                    'message': '交易时间，无可用数据'
                })
    except Exception as e:
        error_logger.error(f"API /api/flow/current 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/current]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/history', methods=['GET'])
def get_history():
    try:
        days = request.args.get('days', '7', type=int)
        days = min(days, 30)
        
        history = load_recent_daily_data_with_accumulation(days)
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_daily_record = load_daily_data(today)
        
        if today_daily_record and 'data' in today_daily_record and today not in history:
            if today not in history:
                history[today] = []
            for i, item in enumerate(today_daily_record['data']):
                history[today].append({
                    'rank': i + 1,
                    'name': item.get('name', ''),
                    'flow': item.get('flow', 0),
                    'net_flow': item.get('net_flow', 0),
                    'change': item.get('change', 0),
                    'total_flow': item.get('flow', 0),
                    'accumulated_change_percent': item.get('change', 0),
                    'appearances': 1
                })
        
        return jsonify({
            'success': True,
            'data': history
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/history 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/history]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/minute', methods=['GET'])
def get_minute_data():
    try:
        hours = request.args.get('hours', '24', type=int)
        hours = min(hours, 24)
        
        minute_data = load_recent_realtime_data(hours)
        
        return jsonify({
            'success': True,
            'data': minute_data
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/minute 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/minute]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/minute-by-date', methods=['GET'])
def get_minute_data_by_date():
    try:
        date_str = request.args.get('date', None)
        
        if not date_str:
            return jsonify({
                'success': False,
                'message': '缺少日期参数'
            }), 400
        
        minute_data = load_realtime_data(date_str)
        
        if minute_data.get('_invalid'):
            return jsonify({
                'success': False,
                'message': f'无法加载 {date_str} 的实时数据'
            }), 404
        
        return jsonify({
            'success': True,
            'data': minute_data,
            'date': date_str
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/minute-by-date 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/minute-by-date]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/market', methods=['GET'])
def get_market():
    try:
        now = datetime.now().astimezone()
        if not is_trading_day(now) or not is_trading_time(now):
            return jsonify({
                'success': True,
                'data': load_market_summary_cache(),
                'timestamp': datetime.now().astimezone().isoformat(),
                'message': '非交易时间，返回缓存行情数据'
            })

        market_data = get_market_overview()
        
        if market_data:
            return jsonify({
                'success': True,
                'data': market_data,
                'timestamp': datetime.now().astimezone().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'message': '获取大盘数据失败'
            }), 500
    except Exception as e:
        error_logger.error(f"API /api/flow/market 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/market]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/market-summary', methods=['GET'])
def get_market_summary_route():
    try:
        now = datetime.now().astimezone()
        market_summary = load_market_summary_cache()
        if not _has_today_market_summary(market_summary, now):
            market_summary = refresh_market_summary_cache()
        return jsonify({
            'success': True,
            'data': market_summary,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/market-summary 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/market-summary]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/accumulated', methods=['GET'])
def get_accumulated_flow():
    try:
        days = request.args.get('days', '7', type=int)
        days = min(days, 30)
        
        top_sectors = get_accumulated_top_sectors(days)
        
        return jsonify({
            'success': True,
            'data': top_sectors,
            'days': days,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/accumulated 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/accumulated]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/daily-report', methods=['GET'])
def get_daily_report():
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        # 获取当日数据
        today_data = load_daily_data(date_str)
        if not today_data or 'data' not in today_data:
            return jsonify({
                'success': False,
                'message': f'未找到{date_str}的数据'
            }), 404
        
        # 获取TOP5对比数据
        comparison_data = get_top5_comparison_data(date_str)
        
        # 获取昨日数据用于对比
        yesterday = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_data = load_daily_data(yesterday)
        
        return jsonify({
            'success': True,
            'data': {
                'date': date_str,
                'today': today_data['data'],
                'comparison': comparison_data,
                'yesterday_exists': yesterday_data is not None
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/daily-report 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/daily-report]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/sector-stocks', methods=['GET'])
def get_sector_stocks_api():
    try:
        sector_url = request.args.get('url', '')
        
        if not sector_url:
            return jsonify({
                'success': False,
                'message': '缺少板块URL参数'
            }), 400
        
        stocks = get_sector_stocks(sector_url)
        
        if stocks:
            return jsonify({
                'success': True,
                'data': stocks,
                'timestamp': datetime.now().astimezone().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'message': '获取个股数据失败'
            }), 500
    except Exception as e:
        error_logger.error(f"API /api/flow/sector-stocks 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

def _run_ai_analysis_background():
    """后台线程执行AI分析"""
    global ai_analysis_status
    
    try:
        now = datetime.now().astimezone()
        today = now.strftime('%Y-%m-%d')
        
        # 步骤1: 获取分钟级数据
        _update_ai_status('running', '正在获取数据', 10, '获取分钟级数据')
        minute_data = load_realtime_data(today)
        if minute_data.get('_invalid'):
            minute_data = {}
        
        # 步骤2: 获取板块数据
        _update_ai_status('running', '正在获取数据', 20, '获取板块数据')
        realtime_data = load_realtime_data(today)
        data, timestamp = _get_latest_from_realtime_data(realtime_data)
        
        # 如果没有实时数据，尝试获取今日汇总数据
        if not data:
            today_daily_record = load_daily_data(today)
            if today_daily_record and 'data' in today_daily_record:
                data = today_daily_record['data']
        
        # 步骤3: 整理TOP板块数据
        _update_ai_status('running', '正在整理数据', 30, '整理板块数据')
        top_sectors = []
        if data:
            # 按净流入排序
            inflow_sectors = sorted(
                [s for s in data if s.get('net_flow', 0) > 0],
                key=lambda x: x.get('net_flow', 0),
                reverse=True
            )[:5]
            outflow_sectors = sorted(
                [s for s in data if s.get('net_flow', 0) < 0],
                key=lambda x: x.get('net_flow', 0)
            )[:5]
            
            for i, s in enumerate(inflow_sectors, 1):
                top_sectors.append({
                    'name': s.get('name', ''),
                    'net_flow': s.get('net_flow', 0),
                    'flow': s.get('flow', 0),
                    'change': s.get('change', 0),
                    'flow_direction': 'in',
                    'rank': i
                })
            
            for i, s in enumerate(outflow_sectors, 1):
                top_sectors.append({
                    'name': s.get('name', ''),
                    'net_flow': s.get('net_flow', 0),
                    'flow': s.get('flow', 0),
                    'change': s.get('change', 0),
                    'flow_direction': 'out',
                    'rank': i
                })
        
        # 步骤4: 获取大盘摘要数据
        _update_ai_status('running', '正在整理数据', 40, '获取大盘摘要')
        market_summary = load_market_summary_cache()
        
        # 步骤5: 调用AI分析
        _update_ai_status('running', '正在调用AI', 50, '发送数据给AI')
        result = analyze_daily_flow(minute_data, top_sectors, market_summary)

        # AI返回失败（超时/限流/异常等）：抛异常走下面的失败分支，写 failed 状态。
        # 这样前端能立即看到"请求失败"并支持重新点击，而不是被误当成 completed。
        if not result.get('success'):
            raise RuntimeError(result.get('message') or 'AI分析失败')

        # 步骤6: 保存结果
        _update_ai_status('running', '正在保存结果', 80, '保存分析结果')
        if result.get('success') and result.get('analysis'):
            with open(AI_DAILY_RESULT_FILE, 'w', encoding='utf-8') as f:
                f.write(result.get('analysis', ''))
        
        # 步骤7: 保存状态
        _update_ai_status('running', '正在保存结果', 90, '保存状态信息')
        status_data = {
            'status': 'completed',
            'success': result.get('success', False),
            'message': result.get('message', ''),
            'end_time': datetime.now().astimezone().isoformat(),
            'date': today
        }
        
        with open(AI_DAILY_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False)
        
        # 完成
        _update_ai_status('completed', result.get('message', '分析完成'), 100, '完成')
        
    except Exception as e:
        error_logger.error(f"AI分析后台任务异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        
        # 保存失败状态
        status_data = {
            'status': 'failed',
            'success': False,
            'message': str(e),
            'end_time': datetime.now().astimezone().isoformat()
        }
        
        with open(AI_DAILY_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False)
        
        _update_ai_status('failed', str(e), 0, '失败')


@flow_bp.route('/analyze-daily/start', methods=['POST'])
def analyze_daily_flow_start():
    """发起AI分析全天走势（异步）"""
    global ai_analysis_status
    
    try:
        with ai_analysis_lock:
            # 如果已经在运行，返回当前状态
            if ai_analysis_status['status'] == 'running':
                return jsonify({
                    'success': True,
                    'status': 'running',
                    'message': '分析任务正在执行中，请稍后查询结果'
                })
            
            # 重置状态
            ai_analysis_status = {
                'status': 'running',
                'message': '分析任务已启动',
                'start_time': datetime.now().astimezone().isoformat(),
                'end_time': None
            }
        
        # 清空旧的结果文件和状态文件
        if os.path.exists(AI_DAILY_RESULT_FILE):
            os.remove(AI_DAILY_RESULT_FILE)
        if os.path.exists(AI_DAILY_STATUS_FILE):
            os.remove(AI_DAILY_STATUS_FILE)
        
        # 启动后台线程
        thread = threading.Thread(target=_run_ai_analysis_background)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'status': 'running',
            'message': '分析任务已启动，请稍后查询结果'
        })
        
    except Exception as e:
        error_logger.error(f"API /api/flow/analyze-daily/start 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': '启动分析任务失败'
        }), 500


@flow_bp.route('/analyze-daily/status', methods=['GET'])
def analyze_daily_flow_status():
    """查询AI分析状态和结果"""
    global ai_analysis_status
    
    try:
        # 先检查状态文件
        if os.path.exists(AI_DAILY_STATUS_FILE):
            with open(AI_DAILY_STATUS_FILE, 'r', encoding='utf-8') as f:
                status_data = json.load(f)
            
            # 如果结果已完成，读取md文件内容返回
            if status_data.get('status') == 'completed':
                analysis_content = ''
                if os.path.exists(AI_DAILY_RESULT_FILE):
                    with open(AI_DAILY_RESULT_FILE, 'r', encoding='utf-8') as f:
                        analysis_content = f.read()
                
                return jsonify({
                    'success': True,
                    'status': 'completed',
                    'progress': 100,
                    'step': '完成',
                    'analysis': analysis_content,
                    'message': status_data.get('message', ''),
                    'date': status_data.get('date', '')
                })
            elif status_data.get('status') == 'failed':
                return jsonify({
                    'success': False,
                    'status': 'failed',
                    'progress': 0,
                    'step': '失败',
                    'message': status_data.get('message', '分析失败')
                })
        
        # 检查当前状态（正在运行中）
        with ai_analysis_lock:
            current_status = ai_analysis_status.copy()
        
        return jsonify({
            'success': True,
            'status': current_status['status'],
            'progress': current_status.get('progress', 0),
            'step': current_status.get('step', ''),
            'message': current_status['message'],
            'start_time': current_status.get('start_time')
        })
        
    except Exception as e:
        error_logger.error(f"API /api/flow/analyze-daily/status 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': '查询状态失败'
        }), 500


@flow_bp.route('/analyze-news', methods=['POST'])
def analyze_single_news():
    """分析单条新闻（优先返回缓存，无缓存则实时分析并缓存）"""
    try:
        data = request.get_json() or {}
        title = data.get('title', '')
        content = data.get('content', '')
        news_id = data.get('id', '')

        if not title:
            return jsonify({
                'success': False,
                'message': '新闻标题不能为空'
            }), 400

        # 优先返回缓存结果
        if news_id:
            cached = get_cached_news_analysis(news_id)
            if cached and cached.get('analysis'):
                return jsonify({
                    'success': True,
                    'analysis': cached['analysis'],
                    'duration': cached.get('duration', 0),
                    'cached': True
                })

        # 无缓存，实时分析
        result = analyze_news(title, content)
        
        # 分析成功则缓存
        if result.get('success') and result.get('analysis') and news_id:
            from ai_analyzer import save_news_analysis
            save_news_analysis(news_id, result['analysis'], result.get('duration', 0))
        
        return jsonify(result)

    except Exception as e:
        error_logger.error(f"API /api/flow/analyze-news 异常: {e}")
        return jsonify({
            'success': False,
            'message': f'分析失败: {str(e)[:100]}'
        }), 500


# ============================================================
# 通用：有数据的交易日列表（异动预警等页面用）
# ============================================================
@flow_bp.route('/dates', methods=['GET'])
def flow_dates():
    """列出有实时数据的交易日（降序），给前端日期选择器。"""
    try:
        files = sorted({f.replace('.json', '') for f in os.listdir(REALTIME_DIR)
                        if re.match(r'^\d{4}-\d{2}-\d{2}\.json$', f)}, reverse=True)
        return jsonify({'success': True, 'data': files})
    except Exception as e:
        error_logger.error(f"API /api/flow/dates 异常: {e}")
        return jsonify({'success': False, 'message': f'查询失败: {str(e)[:100]}'}), 500


# ============================================================
# 资金异动预警
# ============================================================
@flow_bp.route('/anomaly/run', methods=['GET'])
def anomaly_run():
    """资金异动检测：默认扫描全天所有 5 分钟时点，返回当日整体异动；
    传入 date + time 时仅检测该单一时点。"""
    try:
        date_str = request.args.get('date')
        time_key = request.args.get('time')
        if date_str and time_key:
            findings = detect_for_snapshot(date_str, time_key, push=False)
            snapshot = {'date': date_str, 'time': time_key}
        else:
            findings, snapshot = detect_full_day(date_str=date_str, push=False)
        return jsonify({'success': True, 'data': findings, 'count': len(findings), 'snapshot': snapshot})
    except Exception as e:
        error_logger.error(f"API /api/flow/anomaly/run 异常: {e}")
        error_logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'检测失败: {str(e)[:100]}'}), 500


@flow_bp.route('/anomaly/alerts', methods=['GET'])
def anomaly_alerts():
    """已推送的异动记录（可选按日期过滤）。"""
    try:
        date_str = request.args.get('date')
        alerts = list_alerts(date_str=date_str)
        return jsonify({'success': True, 'data': alerts, 'count': len(alerts)})
    except Exception as e:
        error_logger.error(f"API /api/flow/anomaly/alerts 异常: {e}")
        return jsonify({'success': False, 'message': f'查询失败: {str(e)[:100]}'}), 500


@flow_bp.route('/anomaly/config', methods=['GET'])
def anomaly_config_get():
    """读取异动检测阈值配置。"""
    return jsonify({'success': True, 'data': load_anomaly_config()})


@flow_bp.route('/anomaly/config', methods=['POST'])
def anomaly_config_set():
    """更新异动检测阈值配置。"""
    try:
        data = request.get_json() or {}
        cfg = save_anomaly_config(data)
        system_logger.info("异动检测配置已更新")
        return jsonify({'success': True, 'data': cfg})
    except Exception as e:
        error_logger.error(f"API /api/flow/anomaly/config POST 异常: {e}")
        return jsonify({'success': False, 'message': f'保存失败: {str(e)[:100]}'}), 500


@flow_bp.route('/anomaly/baseline', methods=['GET'])
def anomaly_baseline_get():
    """读取 z-score 基线状态。"""
    try:
        bl = get_baseline()
        sectors = (bl or {}).get('sectors', {})
        return jsonify({'success': True, 'data': {
            'built_at': (bl or {}).get('built_at'),
            'baseline_days': (bl or {}).get('baseline_days'),
            'sector_count': len(sectors),
            'sectors': sectors,
        }})
    except Exception as e:
        error_logger.error(f"API /api/flow/anomaly/baseline 异常: {e}")
        return jsonify({'success': False, 'message': f'查询失败: {str(e)[:100]}'}), 500


@flow_bp.route('/anomaly/baseline/rebuild', methods=['POST'])
def anomaly_baseline_rebuild():
    """手动重建 z-score 基线。"""
    try:
        days = request.args.get('days', type=int)
        bl = build_baseline(days=days) if days else build_baseline()
        return jsonify({'success': True, 'data': {
            'built_at': bl.get('built_at'),
            'baseline_days': bl.get('baseline_days'),
            'sector_count': len(bl.get('sectors', {})),
        }})
    except Exception as e:
        error_logger.error(f"API /api/flow/anomaly/baseline/rebuild 异常: {e}")
        return jsonify({'success': False, 'message': f'重建失败: {str(e)[:100]}'}), 500
