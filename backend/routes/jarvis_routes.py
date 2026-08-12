"""Jarvis 手机管家聚合端点。

为手机 app 提供「一次请求拿全」的股票早报数据，避免 app 发起多次往返（省电）。
挂载在 /api/jarvis 前缀下：
  - 安全中间件 SecurityMiddleware 的 exempt_routes 含 '/api/jarvis'（前缀匹配），
    因此本路径不被攻击检测/IP 封禁误伤，手机端不会被误封。
  - install_auth_guard 识别请求头 X-Jarvis-Token（is_jarvis_request）放行，无需登录。

每项数据用 _safe 独立 try/except：单源失败只置 _error 字段，不影响其余数据，
保证 app 拿到的总是结构完整的响应。
"""
from datetime import datetime

from flask import Blueprint, jsonify

from core.logger import get_logger

jarvis_app_bp = Blueprint('jarvis_app', __name__, url_prefix='/api/jarvis')

_logger = get_logger('system')


def _safe(fn, label):
    """best-effort 调用：失败返回 {'_error': str}，绝不抛出。"""
    try:
        return fn()
    except Exception as e:
        _logger.warning(f"[jarvis/digest] {label} 获取失败: {e}")
        return {'_error': str(e)}


@jarvis_app_bp.route('/ping', methods=['GET'])
def ping():
    """轻量探活：app 配置页用来验证「服务地址 + X-Jarvis-Token」是否正确。
    能到达此处（返回 200）即说明地址可达且鉴权放行通过。"""
    return jsonify({'success': True, 'message': 'pong'})


@jarvis_app_bp.route('/digest', methods=['GET'])
def digest():
    """Jarvis 手机管家聚合端点：一次返回管家做「股票早报」所需的汇总数据。

    需带 X-Jarvis-Token 头（install_auth_guard.is_jarvis_request 放行）。
    返回结构（任一子项失败会带 _error 字段而非整体失败）：
      trading         : { is_trading_day, is_trading_time }
      market_overview : 大盘总览
      market_summary  : 市场成交摘要缓存
      market_map      : 大盘云图三级树（申万一级→二级→个股）
      anomaly_alerts  : 资金异动告警
    """
    from data.data_processor import (
        get_market_overview, load_market_summary_cache, get_market_map_tree,
    )
    from analysis.anomaly_detector import list_alerts
    from data.data_collector import is_trading_day, is_trading_time

    now = datetime.now().astimezone()
    payload = {
        'success': True,
        'trading': {
            'is_trading_day': _safe(lambda: is_trading_day(now), 'is_trading_day'),
            'is_trading_time': _safe(lambda: is_trading_time(now), 'is_trading_time'),
        },
        'market_overview': _safe(get_market_overview, 'market_overview'),
        'market_summary': _safe(load_market_summary_cache, 'market_summary'),
        'market_map': _safe(lambda: get_market_map_tree(), 'market_map'),
        'anomaly_alerts': _safe(lambda: list_alerts(), 'anomaly_alerts'),
    }

    return jsonify(payload)
