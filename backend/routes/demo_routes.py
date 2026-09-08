# -*- coding: utf-8 -*-
"""演示模式免鉴权接口:未登录访客只读固定历史快照,永不返回实时数据。

给外人演示系统用;登录用户走正常实时接口,互不影响。
数据由 data/demo_snapshot.py 每个交易日收盘后固化到 data/demo/demo_snapshot.json。
"""
from flask import Blueprint, jsonify

from core.logger import get_logger
from data.demo_snapshot import load_demo_snapshot

logger = get_logger('demo')
error_logger = get_logger('error')

demo_bp = Blueprint('demo', __name__, url_prefix='/api/demo')


@demo_bp.route('/status', methods=['GET'])
def demo_status():
    snap = load_demo_snapshot()
    return jsonify({
        'success': True,
        'data': {
            'available': bool(snap.get('available')),
            'date': snap.get('date', ''),
            'captured_at': snap.get('captured_at', ''),
        },
    })


@demo_bp.route('/home', methods=['GET'])
def demo_home():
    """首页演示数据:分钟级板块资金(折线图+top榜单) + 新闻 + 大盘摘要。"""
    try:
        snap = load_demo_snapshot()
        return jsonify({
            'success': True,
            'data': {
                'available': bool(snap.get('available')),
                'date': snap.get('date', ''),
                'captured_at': snap.get('captured_at', ''),
                'minute': snap.get('minute') or {},
                'news': snap.get('news') or [],
                'market_summary': snap.get('market_summary'),
            },
        })
    except Exception as e:
        error_logger.error(f'API /api/demo/home 异常: {e}')
        return jsonify({'success': False, 'message': '演示数据暂不可用'}), 500


@demo_bp.route('/market-map', methods=['GET'])
def demo_market_map():
    """大盘云图演示数据:最后一个整点快照(自带当日真实涨跌幅,静态不再刷新)。"""
    try:
        snap = load_demo_snapshot()
        map_snap = snap.get('market_map') or {}
        return jsonify({
            'success': True,
            'data': {
                'available': bool(map_snap.get('data')),
                'date': map_snap.get('date', ''),
                'time': map_snap.get('time', ''),
                'data': map_snap.get('data') or {},
            },
        })
    except Exception as e:
        error_logger.error(f'API /api/demo/market-map 异常: {e}')
        return jsonify({'success': False, 'message': '演示数据暂不可用'}), 500
