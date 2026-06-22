from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
import threading
import json
import os
from config import DAILY_DIR, REALTIME_DIR, AI_DAILY_RESULT_FILE, AI_DAILY_STATUS_FILE
from data_processor import (
    load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, latest_data, load_daily_data, 
    load_realtime_data, error_logger, get_market_overview, get_accumulated_top_sectors,
    get_top5_comparison_data, get_sector_stocks, load_market_summary_cache,
    refresh_market_summary_cache, is_market_summary_complete
)
from data_collector import is_trading_day, is_trading_time, is_morning_close, is_afternoon_close
from ai_analyzer import analyze_daily_flow, analyze_news
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
    """同步分析单条新闻"""
    try:
        data = request.get_json() or {}
        title = data.get('title', '')
        content = data.get('content', '')

        if not title:
            return jsonify({
                'success': False,
                'message': '新闻标题不能为空'
            }), 400

        result = analyze_news(title, content)
        return jsonify(result)

    except Exception as e:
        error_logger.error(f"API /api/flow/analyze-news 异常: {e}")
        return jsonify({
            'success': False,
            'message': f'分析失败: {str(e)[:100]}'
        }), 500
