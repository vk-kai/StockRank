# -*- coding: utf-8 -*-
"""经济周期 API:仪表盘/序列/阶段带/回测/手动采集。挂 /api/econ/*。

- 展示类接口公开(游客只读,与全站只读策略一致)
- 采集与回放触发仅管理员
"""
import logging

from flask import Blueprint, jsonify, request

from routes.auth_routes import is_authenticated
from econ_cycle import collectors, db, engine, signals, backtest
from econ_cycle import playbook as econ_playbook

logger = logging.getLogger('econ_cycle')

bp = Blueprint('econ_cycle', __name__)


@bp.route('/api/econ/overview')
def api_overview():
    as_of = request.args.get('as_of') or None
    data = signals.overview(as_of=as_of)
    return jsonify(dict(success=True, data=data))


@bp.route('/api/econ/playbook')
def api_playbook():
    """周期知识库:指标解读/阶段路径/传导链/时间预判。"""
    as_of = request.args.get('as_of') or None
    return jsonify(dict(success=True, data=econ_playbook.playbook(as_of=as_of)))


@bp.route('/api/econ/series/<code>')
def api_series(code):
    value_type = request.args.get('type', 'level')
    rows = db.get_series(code, value_type=value_type)
    ind = next((i for i in db.get_indicators() if i['code'] == code), None)
    return jsonify(dict(success=True, code=code,
                        indicator=ind, points=rows))


@bp.route('/api/econ/phases/<scope>')
def api_phases(scope):
    if scope not in ('national', 'xian'):
        return jsonify(dict(success=False, error='scope 仅支持 national/xian')), 400
    bands = backtest.phase_bands(scope)
    return jsonify(dict(success=True, scope=scope, bands=bands,
                        phase_labels=engine.PHASE_LABELS))


@bp.route('/api/econ/backtest/<scope>')
def api_backtest(scope):
    if scope not in ('national', 'xian'):
        return jsonify(dict(success=False, error='scope 仅支持 national/xian')), 400
    return jsonify(dict(success=True, data=backtest.full_report(scope)))


@bp.route('/api/econ/collect', methods=['POST'])
def api_collect():
    if not is_authenticated():
        return jsonify(dict(success=False, error='未登录')), 401
    result = collectors.run_all()
    return jsonify(dict(success=True, data=result))


@bp.route('/api/econ/replay', methods=['POST'])
def api_replay():
    if not is_authenticated():
        return jsonify(dict(success=False, error='未登录')), 401
    scope = request.json.get('scope', 'national') if request.is_json else 'national'
    months = request.json.get('months') if request.is_json else None
    bands = backtest.phase_bands(scope, months=months)
    return jsonify(dict(success=True, scope=scope, count=len(bands),
                        bands=bands))
