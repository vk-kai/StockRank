# -*- coding: utf-8 -*-
"""小程序数据后台管理接口（仅 vk 登录态可用）。

给《每日热门趣味测试》小程序的数据做后台看板与增删改查:
  GET  /api/mp-admin/overview        趋势看板:总量/各测试参与人次/近30天每日趋势/热度排行
  GET  /api/mp-admin/scores          成绩列表(分页,可按 quiz_id 过滤)
  POST /api/mp-admin/scores/update   改成绩(昵称/分数/用时)
  POST /api/mp-admin/scores/delete   删成绩
  GET  /api/mp-admin/stats           参与计数列表
  POST /api/mp-admin/stats/save      新建/改计数(key+count)
  POST /api/mp-admin/stats/delete    删计数
  GET  /api/mp-admin/rooms           PK房间列表(分页)
  POST /api/mp-admin/rooms/delete    删房间

鉴权注意:url_prefix 必须是 /api/mp-admin 而不能挂 /api/mp/ 下——
后者被 install_auth_guard 的 PUBLIC_PATH_PREFIXES 整段放行(小程序接口无登录态)。
本组接口走站点登录:每个 handler 先 _require_admin()(vk session),
写操作再校验 body 里的今日动态密码(与兑换码/配置管理一致的双保险)。
复用 mp_game_routes 的 _db()(同一 SQLite,WAL)与缓存,改完主动清缓存。
"""
import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from core.daily_password import BEIJING_TZ
from core.logger import get_logger
from routes.auth_routes import is_authenticated, verify_password
from routes.mp_game_routes import (
    _db, _rank_cache, _stat_cache, STAT_KEY_RE, DEFAULT_NICKNAME,
)

mp_admin_bp = Blueprint('mp_admin', __name__, url_prefix='/api/mp-admin')
logger = get_logger('system')
error_logger = get_logger('error')

TREND_DAYS = 30
MAX_COUNT = 999999999


def _require_admin():
    """仅 vk 登录态可访问(体验码会话 authenticated 但非 admin,不放行)。"""
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'auth_required',
                        'message': '仅管理员可操作'}), 401
    return None


def _require_password(data):
    """写操作二次校验今日动态密码。返回 (response_or_None)。"""
    if not verify_password((data or {}).get('password', '')):
        return jsonify({'success': False, 'message': '密码错误'}), 401
    return None


def _parse_page_args():
    """分页参数:page 从1起,page_size 10~100 默认20。"""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(max(1, int(request.args.get('page_size', 20))), 100)
    except (TypeError, ValueError):
        page_size = 20
    return page, page_size


def _bj_days(n):
    """近 n 天的北京日期串列表(含今天,升序)。"""
    today = datetime.now(BEIJING_TZ).date()
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n - 1, -1, -1)]


# --------------------------------------------------------------------------
# 一、趋势看板
# --------------------------------------------------------------------------
@mp_admin_bp.route('/overview', methods=['GET'])
def mp_admin_overview():
    resp = _require_admin()
    if resp:
        return resp
    try:
        days = _bj_days(TREND_DAYS)
        day_from = days[0]
        with _db() as conn:
            totals = {
                'tests': (conn.execute('SELECT COALESCE(SUM(count),0) AS c FROM stats')
                          .fetchone()['c']),
                'players': (conn.execute('SELECT COUNT(DISTINCT openid) AS c FROM scores')
                            .fetchone()['c']),
                'quizzes': (conn.execute('SELECT COUNT(DISTINCT quiz_id) AS c FROM scores')
                            .fetchone()['c']),
                'scores': (conn.execute('SELECT COUNT(*) AS c FROM scores').fetchone()['c']),
                'rooms': (conn.execute('SELECT COUNT(*) AS c FROM rooms').fetchone()['c']),
                'rooms_finished': (conn.execute(
                    "SELECT COUNT(*) AS c FROM rooms WHERE state = 'finished'")
                    .fetchone()['c']),
            }
            # 各测试当前累计参与人次(柱状图,取前20)
            stat_counts = [{'key': r['key'], 'count': r['count']} for r in conn.execute(
                'SELECT key, count FROM stats ORDER BY count DESC LIMIT 20')]
            # 每日测试人次:stat_log 按 北京日 聚合
            tests_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                'FROM stat_log WHERE date(ts, \'unixepoch\', \'+8 hours\') >= ? GROUP BY d',
                (day_from,))}
            # 每日新增成绩/建房:scores/rooms 的 created_at 是 UTC 文本,+8h 转北京日
            players_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM scores "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            rooms_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM rooms "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            # 测试热度排行:每个 quiz 的参与人数/平均得分率
            quiz_top = [{
                'quiz_id': r['quiz_id'], 'players': r['players'],
                'avg_score': round(r['avg_pct'], 1),
            } for r in conn.execute('''SELECT quiz_id, COUNT(*) AS players,
                    AVG(CAST(score AS REAL) / full_score * 100) AS avg_pct
                FROM scores GROUP BY quiz_id ORDER BY players DESC, avg_pct DESC LIMIT 20''')]

        return jsonify({'success': True, 'data': {
            'totals': totals,
            'stat_counts': stat_counts,
            'quiz_top': quiz_top,
            'daily': {
                'days': days,
                'tests': [tests_by_day.get(d, 0) for d in days],
                'scores': [players_by_day.get(d, 0) for d in days],
                'rooms': [rooms_by_day.get(d, 0) for d in days],
            },
        }})
    except Exception as e:
        error_logger.error(f'mp-admin overview 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 二、成绩管理（scores）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/scores', methods=['GET'])
def mp_admin_scores():
    resp = _require_admin()
    if resp:
        return resp
    try:
        quiz_id = (request.args.get('quiz_id') or '').strip()
        page, page_size = _parse_page_args()
        where, params = '1=1', []
        if quiz_id:
            where = 'quiz_id = ?'
            params.append(quiz_id)
        with _db() as conn:
            total = conn.execute(f'SELECT COUNT(*) AS c FROM scores WHERE {where}',
                                 params).fetchone()['c']
            items = [{
                'quiz_id': r['quiz_id'], 'openid': r['openid'],
                'nickname': r['nickname'] or DEFAULT_NICKNAME,
                'score': r['score'], 'full_score': r['full_score'],
                'duration_ms': r['duration_ms'], 'created_at': r['created_at'],
            } for r in conn.execute(
                f'''SELECT * FROM scores WHERE {where}
                    ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?''',
                params + [page_size, (page - 1) * page_size])]
        return jsonify({'success': True, 'data': {
            'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }})
    except Exception as e:
        error_logger.error(f'mp-admin scores 列表异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/scores/update', methods=['POST'])
def mp_admin_score_update():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp
        quiz_id = str(data.get('quiz_id') or '').strip()
        openid = str(data.get('openid') or '').strip()
        if not quiz_id or not openid:
            return jsonify({'success': False, 'message': '缺少 quiz_id 或 openid'}), 400

        sets, params = [], []
        nickname = str(data.get('nickname') or '').strip()
        if 'nickname' in data:
            if not nickname or len(nickname) > 12:
                return jsonify({'success': False, 'message': '昵称不合法(1~12字)'}), 400
            sets.append('nickname = ?')
            params.append(nickname)
        for field, name in (('score', '分数'), ('duration_ms', '用时'),
                            ('full_score', '满分')):
            if field in data:
                try:
                    v = int(data[field])
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': f'{name}格式错误'}), 400
                if v < 0 or v > 100000000:
                    return jsonify({'success': False, 'message': f'{name}不合法'}), 400
                sets.append(f'{field} = ?')
                params.append(v)
        if not sets:
            return jsonify({'success': False, 'message': '没有可更新的字段'}), 400

        with _db() as conn:
            cur = conn.execute(f'''UPDATE scores SET {', '.join(sets)}
                WHERE quiz_id = ? AND openid = ?''', params + [quiz_id, openid])
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': '记录不存在'}), 404
        _rank_cache.pop(quiz_id, None)
        logger.info(f'[mp-admin] 修改成绩: {quiz_id}/{openid}')
        return jsonify({'success': True, 'message': '已更新'})
    except Exception as e:
        error_logger.error(f'mp-admin score update 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/scores/delete', methods=['POST'])
def mp_admin_score_delete():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp
        quiz_id = str(data.get('quiz_id') or '').strip()
        openid = str(data.get('openid') or '').strip()
        if not quiz_id or not openid:
            return jsonify({'success': False, 'message': '缺少 quiz_id 或 openid'}), 400
        with _db() as conn:
            cur = conn.execute('DELETE FROM scores WHERE quiz_id = ? AND openid = ?',
                               (quiz_id, openid))
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': '记录不存在'}), 404
        _rank_cache.pop(quiz_id, None)
        logger.info(f'[mp-admin] 删除成绩: {quiz_id}/{openid}')
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        error_logger.error(f'mp-admin score delete 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 三、参与计数管理（stats）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/stats', methods=['GET'])
def mp_admin_stats():
    resp = _require_admin()
    if resp:
        return resp
    try:
        with _db() as conn:
            items = [{
                'key': r['key'], 'count': r['count'], 'updated_at': r['updated_at'],
            } for r in conn.execute('SELECT key, count, updated_at FROM stats '
                                    'ORDER BY count DESC, key')]
        return jsonify({'success': True, 'data': {'items': items, 'total': len(items)}})
    except Exception as e:
        error_logger.error(f'mp-admin stats 列表异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/stats/save', methods=['POST'])
def mp_admin_stat_save():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp
        key = str(data.get('key') or '').strip().lower()
        try:
            count = int(data.get('count'))
        except (TypeError, ValueError):
            count = -1
        if not STAT_KEY_RE.match(key):
            return jsonify({'success': False, 'message': 'key 格式不合法'}), 400
        if not (0 <= count <= MAX_COUNT):
            return jsonify({'success': False, 'message': 'count 不合法'}), 400
        with _db() as conn:
            conn.execute('''INSERT INTO stats(key, count, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET count = excluded.count,
                    updated_at = excluded.updated_at''',
                (key, count, int(time.time())))
        _stat_cache.pop(key, None)
        logger.info(f'[mp-admin] 保存计数: {key}={count}')
        return jsonify({'success': True, 'message': '已保存'})
    except Exception as e:
        error_logger.error(f'mp-admin stat save 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/stats/delete', methods=['POST'])
def mp_admin_stat_delete():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp
        key = str(data.get('key') or '').strip().lower()
        if not key:
            return jsonify({'success': False, 'message': '缺少 key'}), 400
        with _db() as conn:
            cur = conn.execute('DELETE FROM stats WHERE key = ?', (key,))
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': '记录不存在'}), 404
        _stat_cache.pop(key, None)
        logger.info(f'[mp-admin] 删除计数: {key}')
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        error_logger.error(f'mp-admin stat delete 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 四、PK 房间管理（rooms）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/rooms', methods=['GET'])
def mp_admin_rooms():
    resp = _require_admin()
    if resp:
        return resp
    try:
        state = (request.args.get('state') or '').strip()
        page, page_size = _parse_page_args()
        where, params = '1=1', []
        if state:
            where = 'state = ?'
            params.append(state)
        with _db() as conn:
            total = conn.execute(f'SELECT COUNT(*) AS c FROM rooms WHERE {where}',
                                 params).fetchone()['c']
            items = []
            for r in conn.execute(
                    f'''SELECT * FROM rooms WHERE {where}
                        ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?''',
                    params + [page_size, (page - 1) * page_size]):
                items.append({
                    'room_code': r['room_code'], 'quiz_id': r['quiz_id'],
                    'state': r['state'],
                    'players': 1 + (1 if r['openid_b'] else 0),
                    'a_submitted': bool(r['answers_a']), 'b_submitted': bool(r['answers_b']),
                    'match_percent': r['match_percent'] if r['state'] == 'finished' else None,
                    'created_at': r['created_at'], 'expires_at': r['expires_at'],
                })
        return jsonify({'success': True, 'data': {
            'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }})
    except Exception as e:
        error_logger.error(f'mp-admin rooms 列表异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/rooms/delete', methods=['POST'])
def mp_admin_room_delete():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp
        room_code = str(data.get('room_code') or '').strip()
        if not room_code:
            return jsonify({'success': False, 'message': '缺少 room_code'}), 400
        with _db() as conn:
            cur = conn.execute('DELETE FROM rooms WHERE room_code = ?', (room_code,))
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': '记录不存在'}), 404
        logger.info(f'[mp-admin] 删除房间: {room_code}')
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        error_logger.error(f'mp-admin room delete 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500
