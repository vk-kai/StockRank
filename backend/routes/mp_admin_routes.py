# -*- coding: utf-8 -*-
"""小程序数据后台管理接口（仅 vk 登录态可用）。

给《每日热门趣味测试》小程序的数据做后台看板与增删改查:
  GET  /api/mp-admin/overview        趋势看板:总量/各测试参与人次/近30天每日趋势/热度排行
  GET  /api/mp-admin/scores          成绩列表(分页,可按 quiz_id 过滤)
  GET  /api/mp-admin/quiz-rank       某测试的排行榜(分页,按分数/用时排序,含测试时间)
  POST /api/mp-admin/scores/create  新增成绩(手动补录/造数据)
  POST /api/mp-admin/scores/update   改成绩(昵称/分数/用时)
  POST /api/mp-admin/scores/delete   删成绩
  GET  /api/mp-admin/stats           参与计数列表
  POST /api/mp-admin/stats/save      新建/改计数(key+count)
  POST /api/mp-admin/stats/delete    删计数
  GET  /api/mp-admin/rooms           PK房间列表(分页,默认近7天;过期房间统一展示为已过期)
  POST /api/mp-admin/rooms/delete    删房间
  POST /api/mp-admin/cleanup-dev-data  清理开发联调脏数据(可重复执行)

鉴权注意:url_prefix 必须是 /api/mp-admin 而不能挂 /api/mp/ 下——
后者被 install_auth_guard 的 PUBLIC_PATH_PREFIXES 整段放行(小程序接口无登录态)。
本组接口走站点登录:每个 handler 先 _require_admin()(vk session),
写操作再校验 body 里的今日动态密码(与兑换码/配置管理一致的双保险)。
复用 mp_game_routes 的 _db()(同一 SQLite,WAL)与缓存,改完主动清缓存。
"""
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from core.daily_password import BEIJING_TZ
from core.logger import get_logger
from routes.auth_routes import is_authenticated, verify_password
from routes.mp_game_routes import (
    _db, _rank_cache, _stat_cache, STAT_KEY_RE, STAT_KEY_NAMES, DEFAULT_NICKNAME,
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


def _key_names(conn):
    """key→展示名 解析表:stat_names(小程序上报) 覆盖内置映射,兜底原样 key。"""
    names = dict(STAT_KEY_NAMES)
    try:
        for r in conn.execute('SELECT key, name FROM stat_names'):
            if r['name']:
                names[r['key']] = r['name']
    except Exception:
        pass
    return names


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
            names = _key_names(conn)
            totals = {
                # 口径:计数接口求和,同人重测也+1(真实人次);成绩表那套是去重口径
                'tests': (conn.execute(
                    "SELECT COALESCE(SUM(count),0) AS c FROM stats WHERE key GLOB 'test_*'")
                    .fetchone()['c']),
                'tool_usage': (conn.execute(
                    "SELECT COALESCE(SUM(count),0) AS c FROM stats WHERE key GLOB 'tool_*'")
                    .fetchone()['c']),
                'players': (conn.execute('SELECT COUNT(DISTINCT openid) AS c FROM scores')
                            .fetchone()['c']),
                # 去重参与记录:成绩表主键(quiz_id, openid),同人同测试只记最佳
                'scores': (conn.execute('SELECT COUNT(*) AS c FROM scores').fetchone()['c']),
                # 有成绩记录的测试数(≠上线测试总数,不上报排行榜的不在内)
                'quizzes': (conn.execute('SELECT COUNT(DISTINCT quiz_id) AS c FROM scores')
                            .fetchone()['c']),
                'rooms': (conn.execute('SELECT COUNT(*) AS c FROM rooms').fetchone()['c']),
                'rooms_finished': (conn.execute(
                    "SELECT COUNT(*) AS c FROM rooms WHERE state = 'finished'")
                    .fetchone()['c']),
            }
            # 参与计数按前缀拆两榜(测试/工具),各取前20,带中文名
            stat_rows = list(conn.execute(
                'SELECT key, count FROM stats ORDER BY count DESC, key'))
            test_counts = [{'key': r['key'], 'name': names.get(r['key'], r['key']),
                            'count': r['count']}
                           for r in stat_rows if r['key'].startswith('test_')][:20]
            tool_counts = [{'key': r['key'], 'name': names.get(r['key'], r['key']),
                            'count': r['count']}
                           for r in stat_rows if r['key'].startswith('tool_')][:20]
            # 每日测试/工具人次:stat_log 按前缀 + 北京日 聚合
            tests_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'test_*' "
                "AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d", (day_from,))}
            tools_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'tool_*' "
                "AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d", (day_from,))}
            # 每日新增成绩/建房:scores/rooms 的 created_at 是 UTC 文本,+8h 转北京日
            players_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM scores "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            rooms_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM rooms "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            # 测试热度排行:每个 quiz 的参与人数/平均得分率(带中文名)
            quiz_top = [{
                'quiz_id': r['quiz_id'], 'name': names.get(r['quiz_id'], r['quiz_id']),
                'players': r['players'], 'avg_score': round(r['avg_pct'], 1),
            } for r in conn.execute('''SELECT quiz_id, COUNT(*) AS players,
                    AVG(CAST(score AS REAL) / full_score * 100) AS avg_pct
                FROM scores GROUP BY quiz_id ORDER BY players DESC, avg_pct DESC LIMIT 20''')]

        return jsonify({'success': True, 'data': {
            'totals': totals,
            'test_counts': test_counts,
            'tool_counts': tool_counts,
            'quiz_top': quiz_top,
            'daily': {
                'days': days,
                'tests': [tests_by_day.get(d, 0) for d in days],
                'tools': [tools_by_day.get(d, 0) for d in days],
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


@mp_admin_bp.route('/scores/create', methods=['POST'])
def mp_admin_score_create():
    """手动新增成绩(补录/运营造数据)。管理员录入,昵称不过 msgSecCheck(可信源)。
    同 quiz_id+openid 已存在则提示走编辑,不覆盖。"""
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
        nickname = str(data.get('nickname') or '').strip()
        if not quiz_id or not openid:
            return jsonify({'success': False, 'message': '缺少 quiz_id 或 openid'}), 400
        if not nickname or len(nickname) > 12:
            return jsonify({'success': False, 'message': '昵称不合法(1~12字)'}), 400
        try:
            score = int(data.get('score'))
            full_score = int(data.get('full_score'))
            duration_ms = int(data.get('duration_ms'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '分数/满分/用时格式错误'}), 400
        if not (0 < full_score <= 1000) or not (0 <= score <= full_score):
            return jsonify({'success': False, 'message': '分数不合法(0 ≤ 分数 ≤ 满分 ≤ 1000)'}), 400
        if not (0 <= duration_ms <= 86400000):
            return jsonify({'success': False, 'message': '用时不合法(0 ≤ 用时 ≤ 1天)'}), 400

        with _db() as conn:
            exists = conn.execute('SELECT 1 FROM scores WHERE quiz_id = ? AND openid = ?',
                                  (quiz_id, openid)).fetchone()
            if exists:
                return jsonify({'success': False,
                                'message': '该玩家在此测试已有成绩，请使用编辑功能'}), 409
            conn.execute('''INSERT INTO scores
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (quiz_id, openid, nickname, score, full_score, duration_ms, None,
                 datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))
        _rank_cache.pop(quiz_id, None)
        logger.info(f'[mp-admin] 新增成绩: {quiz_id}/{openid} score={score}')
        return jsonify({'success': True, 'message': '已新增'})
    except Exception as e:
        error_logger.error(f'mp-admin score create 异常: {e}')
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
# 三、测试排行榜（点开测试名查看）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/quiz-rank', methods=['GET'])
def mp_admin_quiz_rank():
    """某测试的排行榜:排序与小程序端一致(分数高优先,同分用时短优先)。
    返回 昵称/分数/满分/用时/测试时间(created_at,UTC文本,前端转北京时间)。"""
    resp = _require_admin()
    if resp:
        return resp
    try:
        quiz_id = (request.args.get('quiz_id') or '').strip()
        if not quiz_id:
            return jsonify({'success': False, 'message': '缺少 quiz_id'}), 400
        page, page_size = _parse_page_args()
        with _db() as conn:
            total = conn.execute('SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ?',
                                 (quiz_id,)).fetchone()['c']
            items = [{
                'nickname': r['nickname'] or DEFAULT_NICKNAME,
                'score': r['score'], 'full_score': r['full_score'],
                'duration_ms': r['duration_ms'], 'created_at': r['created_at'],
            } for r in conn.execute('''SELECT nickname, score, full_score, duration_ms, created_at
                FROM scores WHERE quiz_id = ?
                ORDER BY score DESC, duration_ms ASC, created_at ASC
                LIMIT ? OFFSET ?''',
                (quiz_id, page_size, (page - 1) * page_size))]
            name = _key_names(conn).get(quiz_id, quiz_id)
        return jsonify({'success': True, 'data': {
            'quiz_id': quiz_id, 'name': name,
            'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }})
    except Exception as e:
        error_logger.error(f'mp-admin quiz-rank 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 四、参与计数管理（stats）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/stats', methods=['GET'])
def mp_admin_stats():
    resp = _require_admin()
    if resp:
        return resp
    try:
        with _db() as conn:
            names = _key_names(conn)
            items = [{
                'key': r['key'], 'name': names.get(r['key'], r['key']),
                'count': r['count'], 'updated_at': r['updated_at'],
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
# 五、PK 房间管理（rooms）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/rooms', methods=['GET'])
def mp_admin_rooms():
    resp = _require_admin()
    if resp:
        return resp
    try:
        state = (request.args.get('state') or '').strip()
        page, page_size = _parse_page_args()
        # 默认只看近7天(过期房间保留7天);days=0 表示全部
        try:
            days = int(request.args.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        where, params = '1=1', []
        if days > 0:
            cutoff = (datetime.utcnow() - timedelta(days=days)) \
                .strftime('%Y-%m-%d %H:%M:%S')
            where = 'created_at >= ?'
            params.append(cutoff)
        if state:
            where += ' AND state = ?'
            params.append(state)
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with _db() as conn:
            total = conn.execute(f'SELECT COUNT(*) AS c FROM rooms WHERE {where}',
                                 params).fetchone()['c']
            items = []
            for r in conn.execute(
                    f'''SELECT * FROM rooms WHERE {where}
                        ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?''',
                    params + [page_size, (page - 1) * page_size]):
                # 已过 expires_at 的房间对玩家侧已不可用,后台统一展示为 expired
                display_state = 'expired' if r['expires_at'] <= now_str else r['state']
                items.append({
                    'room_code': r['room_code'], 'quiz_id': r['quiz_id'],
                    'state': display_state,
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


# --------------------------------------------------------------------------
# 六、清理开发联调脏数据
#    可重复执行:删遗留 quiz、删联调 openid 的成绩/房间、按流水回滚其计数、探针计数清零
# --------------------------------------------------------------------------
@mp_admin_bp.route('/cleanup-dev-data', methods=['POST'])
def mp_admin_cleanup_dev_data():
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        resp = _require_password(data)
        if resp:
            return resp

        dirty_quizzes = ('selftest_tmp', 'wealth')          # 遗留/废弃 quiz_id
        dev_glob = 'vkself*'                                 # 联调 openid 前缀(GLOB)
        dev_glob2 = 'otest*'
        result = {'scores': 0, 'rooms': 0, 'log_rows': 0, 'decremented': {}, 'probe_cleared': False}

        with _db() as conn:
            # 1) 遗留 quiz 的成绩
            cur = conn.execute('DELETE FROM scores WHERE quiz_id IN (?, ?)', dirty_quizzes)
            result['scores'] += cur.rowcount
            # 2) 联调 openid 的成绩/房间
            for glob in (dev_glob, dev_glob2):
                cur = conn.execute('DELETE FROM scores WHERE openid GLOB ?', (glob,))
                result['scores'] += cur.rowcount
                cur = conn.execute('DELETE FROM rooms WHERE openid_a GLOB ? OR openid_b GLOB ?',
                                   (glob, glob))
                result['rooms'] += cur.rowcount
            # 3) 按流水回滚联调 openid 贡献的计数(早期流水无 openid,回滚不了,
            #    残余偏高可用「参与计数-改数值」手工修正)
            for glob in (dev_glob, dev_glob2):
                rows = conn.execute('''SELECT key, COUNT(*) AS c FROM stat_log
                    WHERE openid GLOB ? GROUP BY key''', (glob,)).fetchall()
                for r in rows:
                    conn.execute('''UPDATE stats SET count = MAX(0, count - ?)
                        WHERE key = ?''', (r['c'], r['key']))
                    # 两个前缀循环可能命中同一 key,累加别覆盖
                    result['decremented'][r['key']] = \
                        result['decremented'].get(r['key'], 0) + r['c']
                cur = conn.execute('DELETE FROM stat_log WHERE openid GLOB ?', (glob,))
                result['log_rows'] += cur.rowcount
            # 4) 诊断探针 key 计数清零
            cur = conn.execute("UPDATE stats SET count = 0 WHERE key = 'tool_probe_diag'")
            result['probe_cleared'] = cur.rowcount > 0
            conn.execute("DELETE FROM stat_log WHERE key = 'tool_probe_diag'")
            # 5) 顺手清掉遗留 quiz 贡献的榜单缓存
            for q in dirty_quizzes:
                _rank_cache.pop(q, None)
        _stat_cache.clear()
        logger.info(f'[mp-admin] 清理联调数据: {result}')
        return jsonify({'success': True, 'message': '清理完成', 'result': result})
    except Exception as e:
        error_logger.error(f'mp-admin cleanup 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500
