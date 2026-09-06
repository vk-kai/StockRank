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
  GET  /api/mp-admin/echo            弹幕墙留言列表(分页,wall_id/days过滤,hugs=实时抱抱数)
  POST /api/mp-admin/echo/create     补录留言(管理员内容,本地敏感词/注入检测照拦)
  POST /api/mp-admin/echo/seed       导入20条冷启动种子留言(is_seed=1,全局仅一次)
  POST /api/mp-admin/echo/delete     删留言(连带清掉对应 echohug_ 计数)
  POST /api/mp-admin/echo/ban        封禁留言用户(按 openid,永久或 N 天)
  POST /api/mp-admin/echo/unban      解封留言用户(幂等)
  GET  /api/mp-admin/echo/bans       封禁列表(分页,含状态)
  POST /api/mp-admin/cleanup-dev-data  清理开发联调脏数据(可重复执行)

鉴权注意:url_prefix 必须是 /api/mp-admin 而不能挂 /api/mp/ 下——
后者被 install_auth_guard 的 PUBLIC_PATH_PREFIXES 整段放行(小程序接口无登录态)。
本组接口走站点登录:每个 handler 先 _require_admin()(vk session)。
写操作不二次验动态密码(2026-09 按需求移除:后台仅 vk 一人可见,登录态即唯一门槛,
删除类操作由前端二次确认框兜底)。复用 mp_game_routes 的 _db()(同一 SQLite,
WAL)与缓存,改完主动清缓存。
"""
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_file

from core.daily_password import BEIJING_TZ
from core.logger import get_logger
from routes.auth_routes import is_authenticated
from routes.mp_game_routes import (
    _db, _rank_cache, _overall_cache, _overall_board_cached, _stat_cache,
    STAT_KEY_RE, STAT_KEY_NAMES, DEFAULT_NICKNAME, WALL_ID_RE, ECHO_TEXT_MAX,
    ECHO_CATEGORIES, ECHO_CATEGORY_DEFAULT, OPENID_RE, _field_safe, _safe_nick,
)
from routes.mp_sec_routes import local_text_blocked

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


def _quiz_display_name(names, quiz_id):
    """quiz_id → 中文名。

    scores 表的 quiz_id 是客户端原样上报(如 pastlifeWho / friend,不带 test_ 前缀、
    可能驼峰),而名称映射(stat_names/内置)的 key 统一小写且带 test_/tool_ 前缀
    (如 test_pastlifewho),直接 names.get(quiz_id) 匹配不上 → 全英文。
    这里按 小写原样/去前缀/补前缀 多形态匹配,都失败才回退 quiz_id。
    """
    if not quiz_id:
        return quiz_id
    low = quiz_id.lower()
    cands = [low]
    for prefix in ('test_', 'tool_'):
        if low.startswith(prefix):
            cands.append(low[len(prefix):])
        else:
            cands.append(prefix + low)
    for c in cands:
        if c in names:
            name = names[c]
            # 回显兜底(防存量脏数据):映射名来自小程序上报,注入检测不过则弃用
            return name if _field_safe(name) else quiz_id if _field_safe(quiz_id) else '未知'
    return quiz_id if _field_safe(quiz_id) else '未知'


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
                # 文章阅读:article_* 与测试/工具同一计数接口,口径=每阅读一次+1
                'articles': (conn.execute(
                    "SELECT COALESCE(SUM(count),0) AS c FROM stats WHERE key GLOB 'article_*'")
                    .fetchone()['c']),
                'article_count': (conn.execute(
                    'SELECT COUNT(*) AS c FROM stats WHERE key GLOB \'article_*\'')
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
            article_counts = [{'key': r['key'], 'name': names.get(r['key'], r['key']),
                               'count': r['count']}
                              for r in stat_rows if r['key'].startswith('article_')][:20]
            # 每日测试/工具人次:stat_log 按前缀 + 北京日 聚合
            tests_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'test_*' "
                "AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d", (day_from,))}
            tools_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'tool_*' "
                "AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d", (day_from,))}
            articles_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'article_*' "
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
                'quiz_id': r['quiz_id'], 'name': _quiz_display_name(names, r['quiz_id']),
                'players': r['players'], 'avg_score': round(r['avg_pct'], 1),
            } for r in conn.execute('''SELECT quiz_id, COUNT(*) AS players,
                    AVG(CAST(score AS REAL) / full_score * 100) AS avg_pct
                FROM scores GROUP BY quiz_id ORDER BY players DESC, avg_pct DESC LIMIT 20''')]
            # 今日按小时分布(北京时区,00~23):当天各时间点的实时使用情况
            today = days[-1]
            hours = [f'{h:02d}' for h in range(24)]
            tests_by_hour = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'test_*' "
                "AND date(ts, 'unixepoch', '+8 hours') = ? GROUP BY h", (today,))}
            tools_by_hour = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'tool_*' "
                "AND date(ts, 'unixepoch', '+8 hours') = ? GROUP BY h", (today,))}
            articles_by_hour = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'article_*' "
                "AND date(ts, 'unixepoch', '+8 hours') = ? GROUP BY h", (today,))}
            scores_by_hour = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', created_at, '+8 hours') AS h, COUNT(*) AS c FROM scores "
                "WHERE date(created_at, '+8 hours') = ? GROUP BY h", (today,))}
            rooms_by_hour = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', created_at, '+8 hours') AS h, COUNT(*) AS c FROM rooms "
                "WHERE date(created_at, '+8 hours') = ? GROUP BY h", (today,))}
            # 今日热力:top15 计数key × 24小时(「12点哪个工具最热」),按今天总量排序
            # article_* 是文章阅读计数(量大、口径与使用不同),不进测试/工具热力图,去数据管理列表看;
            # echohug_* 是弹幕墙「抱抱」技术计数(每条留言一个key),同理不进
            key_hour = {}
            for r in conn.execute(
                "SELECT key, strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE date(ts, 'unixepoch', '+8 hours') = ? "
                "AND key NOT GLOB 'article_*' AND key NOT GLOB 'echohug_*' GROUP BY key, h",
                (today,)):
                key_hour.setdefault(r['key'], {})[r['h']] = r['c']
            top_key_rows = sorted(key_hour.items(),
                                  key=lambda kv: (-sum(kv[1].values()), kv[0]))[:15]
            hourly_top_items = [{'key': k, 'name': names.get(k, k),
                                 'hours': [hh.get(h, 0) for h in hours]}
                                for k, hh in top_key_rows]
            hourly_top_max = max((c for _, hh in top_key_rows for c in hh.values()), default=0)
            # 近30天热力:top15 计数key × 30天(「哪天哪个测试/工具最热」),按30天总量排序
            # 同上:article_* 阅读计数与 echohug_* 技术计数不进此图
            key_day = {}
            for r in conn.execute(
                "SELECT key, date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE date(ts, 'unixepoch', '+8 hours') >= ? "
                "AND key NOT GLOB 'article_*' AND key NOT GLOB 'echohug_*' GROUP BY key, d",
                (day_from,)):
                key_day.setdefault(r['key'], {})[r['d']] = r['c']
            top_key_day_rows = sorted(key_day.items(),
                                      key=lambda kv: (-sum(kv[1].values()), kv[0]))[:15]
            daily_top_items = [{'key': k, 'name': names.get(k, k),
                                'days': [dd.get(d, 0) for d in days]}
                               for k, dd in top_key_day_rows]
            daily_top_max = max((c for _, dd in top_key_day_rows for c in dd.values()), default=0)

        # 综合排名榜:与小程序 /rank/overall 同口径(60秒缓存,成绩写操作时失效)
        board = _overall_board_cached()
        overall = {'total': board['total'], 'top': board['top']}

        return jsonify({'success': True, 'data': {
            'totals': totals,
            'test_counts': test_counts,
            'tool_counts': tool_counts,
            'article_counts': article_counts,
            'quiz_top': quiz_top,
            # 综合排名榜(与小程序 /rank/overall 同口径,走同一份60秒缓存)
            'overall': {'total': overall['total'], 'top': overall['top']},
            'daily': {
                'days': days,
                'tests': [tests_by_day.get(d, 0) for d in days],
                'tools': [tools_by_day.get(d, 0) for d in days],
                'articles': [articles_by_day.get(d, 0) for d in days],
                'scores': [players_by_day.get(d, 0) for d in days],
                'rooms': [rooms_by_day.get(d, 0) for d in days],
            },
            'hourly': {
                'hours': hours,
                'tests': [tests_by_hour.get(h, 0) for h in hours],
                'tools': [tools_by_hour.get(h, 0) for h in hours],
                'articles': [articles_by_hour.get(h, 0) for h in hours],
                'scores': [scores_by_hour.get(h, 0) for h in hours],
                'rooms': [rooms_by_hour.get(h, 0) for h in hours],
            },
            # 今日热力图数据:items 按今天总量降序取前15,自带上限 max(前端色阶用)
            'hourly_top': {'items': hourly_top_items, 'max': hourly_top_max},
            # 近30天热力图数据:items 按30天总量降序取前15,列=日期(一天总结一次)
            'daily_top': {'items': daily_top_items, 'max': daily_top_max},
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
            names = _key_names(conn)
            total = conn.execute(f'SELECT COUNT(*) AS c FROM scores WHERE {where}',
                                 params).fetchone()['c']
            items = [{
                'quiz_id': r['quiz_id'],
                'name': _quiz_display_name(names, r['quiz_id']),
                'openid': r['openid'],
                'nickname': _safe_nick(r['nickname']),
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
        _overall_cache['ts'] = 0.0
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
        _overall_cache['ts'] = 0.0
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
        _overall_cache['ts'] = 0.0
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
            names = _key_names(conn)
            total = conn.execute('SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ?',
                                 (quiz_id,)).fetchone()['c']
            items = [{
                'nickname': _safe_nick(r['nickname']),
                'score': r['score'], 'full_score': r['full_score'],
                'duration_ms': r['duration_ms'], 'created_at': r['created_at'],
            } for r in conn.execute('''SELECT nickname, score, full_score, duration_ms, created_at
                FROM scores WHERE quiz_id = ?
                ORDER BY score DESC, duration_ms ASC, created_at ASC
                LIMIT ? OFFSET ?''',
                (quiz_id, page_size, (page - 1) * page_size))]
            name = _quiz_display_name(names, quiz_id)
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
    """参与计数列表。?type=test|tool|article 按前缀过滤(测试/工具/文章),缺省全部。

    echohug_* 是弹幕墙「抱抱」技术计数(每条留言一个key,量大且非业务内容),不列。
    """
    resp = _require_admin()
    if resp:
        return resp
    try:
        stat_type = (request.args.get('type') or '').strip().lower()
        prefix = {'test': 'test_', 'tool': 'tool_', 'article': 'article_'}.get(stat_type)
        with _db() as conn:
            names = _key_names(conn)
            items = [{
                'key': r['key'], 'name': names.get(r['key'], r['key']),
                'count': r['count'], 'updated_at': r['updated_at'],
            } for r in conn.execute('SELECT key, count, updated_at FROM stats '
                                    'ORDER BY count DESC, key')
            if (not prefix or r['key'].startswith(prefix))
            and not r['key'].startswith('echohug_')]
        return jsonify({'success': True, 'data': {
            'items': items, 'total': len(items),
            'sum': sum(i['count'] for i in items),
        }})
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
            names = _key_names(conn)
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
                    'name': _quiz_display_name(names, r['quiz_id']),
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
# 六、弹幕墙留言管理（echo wall）
# --------------------------------------------------------------------------
@mp_admin_bp.route('/echo', methods=['GET'])
def mp_admin_echo():
    """弹幕墙留言列表。?wall_id= 过滤,?days= 时间窗(默认7,0=全部),分页;
    hugs=种子预设数 + 实时抱抱数(echohug_<留言id> 回填,与小程序 GET /echo 同口径);
    is_seed=冷启动种子数据标记(前端带「种子」角标,与真实用户数据区分)。"""
    resp = _require_admin()
    if resp:
        return resp
    try:
        wall_id = (request.args.get('wall_id') or '').strip()
        page, page_size = _parse_page_args()
        try:
            days = int(request.args.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        where, params = [], []
        if wall_id:
            where.append('wall_id = ?')
            params.append(wall_id)
        if days > 0:
            where.append('ts >= ?')
            params.append(int(time.time()) - days * 86400)
        cond = ('WHERE ' + ' AND '.join(where)) if where else ''
        with _db() as conn:
            total = conn.execute(f'SELECT COUNT(*) AS c FROM echo_wall {cond}',
                                 params).fetchone()['c']
            rows = conn.execute(
                f'''SELECT id, wall_id, openid, nickname, text, category, hugs, is_seed, ts
                    FROM echo_wall {cond}
                    ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?''',
                params + [page_size, (page - 1) * page_size]).fetchall()
            # 实时抱抱数:echohug_<留言id> 批量回填
            hug = {}
            if rows:
                keys = [f'echohug_{r["id"]}' for r in rows]
                marks = ','.join('?' * len(keys))
                hug = {r['key']: r['count'] for r in conn.execute(
                    f'SELECT key, count FROM stats WHERE key IN ({marks})', keys)}
            # 封禁状态:每行带 banned,前端按钮「封禁/解封」随状态切换(过期=未封)
            now = int(time.time())
            banned = {r['openid'] for r in conn.execute(
                'SELECT openid FROM echo_bans WHERE expires_at IS NULL OR expires_at > ?',
                (now,)).fetchall()}
        items = [{'id': r['id'], 'wall_id': r['wall_id'], 'openid': r['openid'],
                  'nickname': _safe_nick(r['nickname']), 'text': r['text'],
                  'category': r['category'] or ECHO_CATEGORY_DEFAULT,
                  'banned': r['openid'] in banned,
                  # 种子留言:预设 hugs 列 + 真实抱抱计数;普通留言 hugs 列恒 0
                  'hugs': r['hugs'] + hug.get(f'echohug_{r["id"]}', 0),
                  'is_seed': bool(r['is_seed']), 'ts': r['ts']} for r in rows]
        return jsonify({'success': True, 'data': {
            'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }})
    except Exception as e:
        error_logger.error(f'mp-admin echo 列表异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/echo/create', methods=['POST'])
def mp_admin_echo_create():
    """补录留言(造氛围/补内容)。管理员内容不走微信送检(与补录成绩同口径),
    但本地敏感词与注入检测照拦——墙上内容是公开回显的。

    body: {wall_id, text, nickname?, category?};分类缺省/不在枚举内落「其他」
    (与玩家发布接口同口径,不报错)。
    """
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        wall_id = str(data.get('wall_id') or '').strip()
        text = str(data.get('text') or '').strip()
        nickname = str(data.get('nickname') or '').strip()
        category = str(data.get('category') or '').strip()
        if not wall_id or not text:
            return jsonify({'success': False, 'message': '缺少 wall_id 或 text'}), 400
        if not WALL_ID_RE.match(wall_id):
            return jsonify({'success': False, 'message': 'wall_id 格式不合法'}), 400
        if len(text) > ECHO_TEXT_MAX:
            return jsonify({'success': False, 'message': f'留言最多{ECHO_TEXT_MAX}字'}), 400
        if not _field_safe(text) or local_text_blocked(text):
            return jsonify({'success': False, 'message': '内容含违规信息'}), 400
        if nickname and (not _field_safe(nickname) or local_text_blocked(nickname)):
            nickname = ''
        if category not in ECHO_CATEGORIES:
            category = ECHO_CATEGORY_DEFAULT
        with _db() as conn:
            cur = conn.execute(
                '''INSERT INTO echo_wall(wall_id, openid, nickname, text, category, hugs, ts)
                VALUES (?, ?, ?, ?, ?, 0, ?)''',
                (wall_id, 'admin', nickname or DEFAULT_NICKNAME, text, category,
                 int(time.time())))
            new_id = cur.lastrowid
        logger.info(f'[mp-admin] 补录留言: wall={wall_id} id={new_id} cat={category}')
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        error_logger.error(f'mp-admin echo create 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# 弹幕墙冷启动种子数据(vk 2026-09-06 提供,共20条):昵称/留言/预设抱抱数/分类。
# is_seed=1 标记,后台列表带「种子」角标,与真实用户数据区分;预设抱抱数写进
# echo_wall.hugs 列(真实用户留言恒0;真实抱抱仍走 echohug_<id> 计数,展示时相加)。
# 分类按留言内容人工归入 ECHO_CATEGORIES 枚举(情感/压力/成长/校园/生活/职场/树洞/其他)
ECHO_SEEDS = (
    ('悄悄碎了又拼好', '白天嘻嘻哈哈，晚上一个人对着天花板，突然就哭了。没发生什么，就是撑太久了。', 88, '压力'),
    ('十一点半的地铁', '加班到十一点，地铁上全是有家可回的人，只有我在故意走得很慢。', 23, '职场'),
    ('昨天很开心', '朋友圈编辑了又删，最后只发了个“哈哈哈”。其实我今天不太好。', 67, '树洞'),
    ('想妈妈的第四天', '搬家那天一个人扛了七个箱子，晚上坐在地板上吃泡面，突然特别想我妈。', 41, '情感'),
    ('情绪收容所所长', '说不难过是假的，只是说了也没用，就省了。', 92, '树洞'),
    ('熬夜的小月亮', '凌晨三点还醒着的人，我们看的是同一个月亮吧。', 34, '树洞'),
    ('半糖去冰', '工资到账那天最有底气，还完花呗，又归于平静。', 19, '生活'),
    ('等雨停的猫', '和最好的朋友已经三年没见了，聊天记录停在“改天聚”。', 27, '情感'),
    ('今天也想被夸', '别人问我最近怎么样，我说挺好的。反正说了详情，也没人能替我过。', 76, '压力'),
    ('一盏没关的灯', '洗完澡坐在床边擦头发，突然觉得这一天里只有这五分钟是自己的。', 38, '生活'),
    ('不哭挑战失败', '不是不想谈恋爱，是怕再遇到一个让我半夜等消息的人。', 45, '情感'),
    ('今晚也晚安', '周末睡到下午两点，房间里安安静静，手机也没有新消息。', 52, '生活'),
    ('甜甜圈中间的洞', '减肥第五天，深夜点了外卖，一边吃一边骂自己没出息。', 16, '生活'),
    ('打工的小水豚', '我不怕一个人吃饭，我怕的是第二杯半价。', 83, '生活'),
    ('月亮邮递员', '生日快乐是自己说的，蛋糕也是自己买的，插了一根蜡烛，认真许了愿。', 29, '情感'),
    ('不想长大的小孩', '长大以后连崩溃都要挑时间，最好是不用上班的周末。', 71, '成长'),
    ('藏眼泪的云朵', '今天又被夸“你真独立”，可我只是没有人可以麻烦。', 33, '情感'),
    ('抱抱补给站', '那天在地铁上看见一个女孩偷偷哭，好想抱抱她，也想有人抱抱我。', 58, '情感'),
    ('慢半拍的考拉', '存款一点点变多，快乐好像没跟着涨，但至少安全感有了。', 22, '生活'),
    ('凌晨三点的风', '上周三在洗澡的时候哭了一场，出来像什么都没发生过。', 12, '树洞'),
)


@mp_admin_bp.route('/echo/seed', methods=['POST'])
def mp_admin_echo_seed():
    """一键导入20条冷启动种子留言。仅 vk 登录态(无二次密码);全局只允许导入一次。

    body: {wall_id?}(缺省=北京今天 YYYYMMDD)。种子 openid='seed'、is_seed=1,
    预设抱抱数写 hugs 列、分类写 category 列(ECHO_SEEDS 内人工归类);
    ts 自导入时刻逐条向前错开约16分钟,列表顺序自然。
    """
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        wall_id = str(data.get('wall_id') or '').strip() or \
            datetime.now(BEIJING_TZ).strftime('%Y%m%d')
        if not WALL_ID_RE.match(wall_id):
            return jsonify({'success': False, 'message': 'wall_id 格式不合法'}), 400
        with _db() as conn:
            # 幂等:种子数据全局只此一批,重复调用不再写入(换 wall_id 也不行)
            if conn.execute('SELECT 1 FROM echo_wall WHERE is_seed = 1 LIMIT 1').fetchone():
                cnt = conn.execute(
                    'SELECT COUNT(*) AS c FROM echo_wall WHERE is_seed = 1').fetchone()['c']
                return jsonify({'success': False,
                                'message': f'种子数据已导入过({cnt}条)，不会重复写入'}), 409
            now = int(time.time())
            for i, (nick, text, hugs, cat) in enumerate(ECHO_SEEDS):
                conn.execute('''INSERT INTO echo_wall
                    (wall_id, openid, nickname, text, category, hugs, is_seed, ts)
                    VALUES (?, 'seed', ?, ?, ?, ?, 1, ?)''',
                    (wall_id, nick, text, cat, hugs, now - i * 977))
        logger.info(f'[mp-admin] 导入种子留言: wall={wall_id} {len(ECHO_SEEDS)}条')
        return jsonify({'success': True, 'message': '已导入',
                        'count': len(ECHO_SEEDS), 'wall_id': wall_id})
    except Exception as e:
        error_logger.error(f'mp-admin echo seed 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/echo/delete', methods=['POST'])
def mp_admin_echo_delete():
    """删留言(按 id)。连带清掉对应 echohug_<id> 计数与 echo_hugs 去重记录,不留孤儿条目。"""
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        try:
            msg_id = int(data.get('id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '缺少 id'}), 400
        hug_key = f'echohug_{msg_id}'
        with _db() as conn:
            cur = conn.execute('DELETE FROM echo_wall WHERE id = ?', (msg_id,))
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': '留言不存在'}), 404
            conn.execute('DELETE FROM stats WHERE key = ?', (hug_key,))
            # 抱抱去重记录一并删:否则留言 id 若被复用,老用户会被误判「已抱过」
            conn.execute('DELETE FROM echo_hugs WHERE hug_key = ?', (hug_key,))
        _stat_cache.pop(hug_key, None)
        logger.info(f'[mp-admin] 删除留言: id={msg_id}')
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        error_logger.error(f'mp-admin echo delete 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 弹幕墙用户封禁:按 openid 封禁/解封/列表。只挡发布留言(mp_game_routes
# echo_post 里 _echo_banned 检查),不影响抱抱/成绩等其他功能。
# 永久封禁 expires_at=NULL;临时封禁到期懒失效,过期行保留作历史可解封清除。
# --------------------------------------------------------------------------
@mp_admin_bp.route('/echo/ban', methods=['POST'])
def mp_admin_echo_ban():
    """封禁留言用户。body: {openid, days?, reason?}。

    days 缺省/0=永久;1~3650=临时封禁天数。重复封禁同一人:覆盖时长与原因。
    """
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        if not openid:
            return jsonify({'success': False, 'message': '缺少 openid'}), 400
        if not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': 'openid 格式不合法'}), 400
        days = data.get('days')
        if days in (None, '', 0):
            days = None
        else:
            try:
                days = int(days)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': '封禁时长不合法'}), 400
            if not 1 <= days <= 3650:
                return jsonify({'success': False, 'message': '封禁时长需为 1~3650 天（留空=永久）'}), 400
        # 原因选填,仅后台列表展示;截100字防滥用
        reason = str(data.get('reason') or '').strip()[:100] or None
        now = int(time.time())
        expires = now + days * 86400 if days else None
        with _db() as conn:
            conn.execute('''INSERT INTO echo_bans(openid, reason, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(openid) DO UPDATE SET
                    reason = excluded.reason,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at''', (openid, reason, expires, now))
        logger.info(f'[mp-admin] 封禁留言用户: {openid[:6]}… '
                    f'{"永久" if days is None else f"{days}天"} reason={reason or "-"}')
        return jsonify({'success': True, 'message': '已封禁', 'expires_at': expires})
    except Exception as e:
        error_logger.error(f'mp-admin echo ban 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/echo/unban', methods=['POST'])
def mp_admin_echo_unban():
    """解封留言用户。body: {openid};幂等:未封禁也返回成功(便于前端直接点)。"""
    resp = _require_admin()
    if resp:
        return resp
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        if not openid:
            return jsonify({'success': False, 'message': '缺少 openid'}), 400
        if not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': 'openid 格式不合法'}), 400
        with _db() as conn:
            cur = conn.execute('DELETE FROM echo_bans WHERE openid = ?', (openid,))
        removed = cur.rowcount > 0
        if removed:
            logger.info(f'[mp-admin] 解封留言用户: {openid[:6]}…')
        return jsonify({'success': True,
                        'message': '已解封' if removed else '该用户未在封禁列表'})
    except Exception as e:
        error_logger.error(f'mp-admin echo unban 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_admin_bp.route('/echo/bans', methods=['GET'])
def mp_admin_echo_bans():
    """封禁列表(分页,created_at 倒序)。status: permanent永久/active生效中/expired已过期。"""
    resp = _require_admin()
    if resp:
        return resp
    try:
        page, page_size = _parse_page_args()
        now = int(time.time())
        with _db() as conn:
            total = conn.execute('SELECT COUNT(*) AS c FROM echo_bans').fetchone()['c']
            rows = conn.execute('''SELECT openid, reason, expires_at, created_at
                FROM echo_bans ORDER BY created_at DESC, openid ASC LIMIT ? OFFSET ?''',
                [page_size, (page - 1) * page_size]).fetchall()
        items = [{'openid': r['openid'], 'reason': r['reason'],
                  'created_at': r['created_at'], 'expires_at': r['expires_at'],
                  'status': ('permanent' if r['expires_at'] is None
                             else 'active' if r['expires_at'] > now else 'expired')}
                 for r in rows]
        return jsonify({'success': True, 'data': {
            'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }})
    except Exception as e:
        error_logger.error(f'mp-admin echo bans 查询异常: {e}')
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
            _overall_cache['ts'] = 0.0   # 删过成绩,综合榜一并失效
        _stat_cache.clear()
        logger.info(f'[mp-admin] 清理联调数据: {result}')
        return jsonify({'success': True, 'message': '清理完成', 'result': result})
    except Exception as e:
        error_logger.error(f'mp-admin cleanup 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# --------------------------------------------------------------------------
# 五、Excel 报表导出(一个文件装全核心数据,面向"发给 AI 分析受欢迎程度"的场景)
# --------------------------------------------------------------------------
@mp_admin_bp.route('/export', methods=['GET'])
def mp_admin_export():
    resp = _require_admin()
    if resp:
        return resp
    # openpyxl 延迟导入:未安装时只影响本接口,不拖垮整个后台
    try:
        from io import BytesIO
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        error_logger.error('mp-admin export 失败: 服务器未安装 openpyxl')
        return jsonify({'success': False,
                        'message': '服务器未安装 openpyxl,pip install openpyxl 后重启即可'}), 500
    try:
        now_bj = datetime.now(BEIJING_TZ)
        days = _bj_days(TREND_DAYS)
        day_from, last7 = days[0], set(days[-7:])
        with _db() as conn:
            names = _key_names(conn)
            stat_counts = {r['key']: r['count']
                           for r in conn.execute('SELECT key, count FROM stats')}
            # 近30天 key×日 流水(近7天/沉睡判定都从这份出)
            key_day = {}
            for r in conn.execute(
                "SELECT key, date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c "
                "FROM stat_log WHERE date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY key, d",
                (day_from,)):
                key_day.setdefault(r['key'], {})[r['d']] = r['c']
            key_last = {r['key']: r['last'] for r in conn.execute(
                "SELECT key, MAX(date(ts, 'unixepoch', '+8 hours')) AS last "
                "FROM stat_log GROUP BY key")}
            # 测试维:成绩表(去重参与/得分率/用时) + 计数表(真实人次)
            quiz_rows = {r['quiz_id']: r for r in conn.execute('''SELECT quiz_id,
                    COUNT(*) AS players,
                    AVG(CAST(score AS REAL) / full_score * 100) AS avg_pct,
                    AVG(duration_ms) AS avg_ms,
                    MAX(created_at) AS last_at
                FROM scores GROUP BY quiz_id''')}
            tests_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c FROM stat_log "
                "WHERE key GLOB 'test_*' AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d",
                (day_from,))}
            tools_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(ts, 'unixepoch', '+8 hours') AS d, COUNT(*) AS c FROM stat_log "
                "WHERE key GLOB 'tool_*' AND date(ts, 'unixepoch', '+8 hours') >= ? GROUP BY d",
                (day_from,))}
            scores_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM scores "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            rooms_by_day = {r['d']: r['c'] for r in conn.execute(
                "SELECT date(created_at, '+8 hours') AS d, COUNT(*) AS c FROM rooms "
                "WHERE date(created_at, '+8 hours') >= ? GROUP BY d", (day_from,))}
            today = days[-1]
            hours = [f'{h:02d}' for h in range(24)]
            t_by_h = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'test_*' "
                "AND date(ts, 'unixepoch', '+8 hours') = ? GROUP BY h", (today,))}
            g_by_h = {r['h']: r['c'] for r in conn.execute(
                "SELECT strftime('%H', ts, 'unixepoch', '+8 hours') AS h, COUNT(*) AS c "
                "FROM stat_log WHERE key GLOB 'tool_*' "
                "AND date(ts, 'unixepoch', '+8 hours') = ? GROUP BY h", (today,))}
            rooms_all = list(conn.execute('SELECT * FROM rooms ORDER BY created_at DESC'))
            totals = {
                'players': conn.execute(
                    'SELECT COUNT(DISTINCT openid) AS c FROM scores').fetchone()['c'],
                'scores': conn.execute('SELECT COUNT(*) AS c FROM scores').fetchone()['c'],
                'quizzes': conn.execute(
                    'SELECT COUNT(DISTINCT quiz_id) AS c FROM scores').fetchone()['c'],
                'tests': sum(v for k, v in stat_counts.items() if k.startswith('test_')),
                'tools': sum(v for k, v in stat_counts.items() if k.startswith('tool_')),
                'articles': sum(v for k, v in stat_counts.items()
                                if k.startswith('article_')),
                # echohug_*(弹幕墙抱抱技术计数)不算业务条目,否则「测试+工具+文章」口径失真
                'key_total': sum(1 for k in stat_counts
                                 if not k.startswith('echohug_')),
                'active30': sum(1 for k in stat_counts
                                if not k.startswith('echohug_')
                                and sum(key_day.get(k, {}).values()) > 0),
            }
        # 综合排名与看板同源(60秒缓存)
        board = _overall_board_cached()
        rooms_finished = sum(1 for r in rooms_all if r['state'] == 'finished')

        def d30(k):
            return sum(key_day.get(k, {}).values())

        def d7(k):
            return sum(c for d, c in key_day.get(k, {}).items() if d in last7)

        def stat_key_for(quiz_id):
            # scores 的 quiz_id 与计数 key 可能差一个 test_ 前缀,两个都试
            if f'test_{quiz_id}' in stat_counts and quiz_id not in stat_counts:
                return f'test_{quiz_id}'
            return quiz_id

        wb = Workbook()
        h_fill = PatternFill('solid', fgColor='1F3864')
        h_font = Font(bold=True, color='FFFFFF')

        def sheet(ws, header, rows):
            ws.append(header)
            for c in ws[1]:
                c.fill, c.font = h_fill, h_font
                c.alignment = Alignment(horizontal='center', vertical='center')
            for r in rows:
                ws.append(r)
            # 简易列宽:按内容长度估,中文按约2倍宽算
            for i in range(1, len(header) + 1):
                vals = [len(str(header[i - 1]))] + \
                       [len(str(r[i - 1])) * 2 for r in rows if r[i - 1] is not None]
                ws.column_dimensions[get_column_letter(i)].width = \
                    min(max(max(vals) + 2, 10), 44)

        # 1) 概览
        ws = wb.active
        ws.title = '概览'
        sheet(ws, ['指标', '数值', '说明'], [
            ['报表生成时间', now_bj.strftime('%Y-%m-%d %H:%M'), '北京时间'],
            ['数据口径', '按日流水自后台上线起记录(约2026-08-21)',
             '更早历史无按日流水,只有全史累计次数'],
            ['参与人数(玩过测试,去重)', totals['players'], ''],
            ['测试完成总次数', totals['tests'], '每完成一次+1,重复计入'],
            ['工具使用总次数', totals['tools'], '每使用一次+1'],
            ['文章阅读总次数', totals['articles'], 'article_* 计数,每阅读一次+1'],
            ['提交成绩总数', totals['scores'], '同人同测试只记最好一次'],
            ['人均玩过测试数',
             round(totals['scores'] / totals['players'], 1) if totals['players'] else 0, ''],
            ['有成绩的测试数', totals['quizzes'], ''],
            ['计数条目总数(测试+工具+文章)', totals['key_total'], ''],
            ['近30天有使用的条目数', totals['active30'], ''],
            ['近30天零使用(沉睡)条目数', totals['key_total'] - totals['active30'], ''],
            ['PK房间总数', len(rooms_all), ''],
            ['PK完成局数', rooms_finished, ''],
            ['PK完成率',
             f"{rooms_finished * 100 // len(rooms_all) if rooms_all else 0}%", ''],
            ['综合排名达标人数(参与≥3个测试)', board['total'], ''],
        ])

        # 2) 测试明细(计数表 test_* ∪ 成绩表 quiz_id,两侧数据都别漏)
        test_keys = sorted({k for k in stat_counts if k.startswith('test_')} | set(quiz_rows))
        rows = []
        for k in test_keys:
            sk = stat_key_for(k)
            q = quiz_rows.get(k)
            n30 = d30(sk)
            all_cnt = stat_counts.get(sk, 0)
            status = '活跃' if n30 > 0 else (
                '沉睡(近30天零使用)' if all_cnt > 0 else '无计数(仅成绩)')
            rows.append([
                k, _quiz_display_name(names, k), all_cnt, n30, d7(sk),
                q['players'] if q else None,
                round(q['avg_pct'], 1) if q else None,
                round(q['avg_ms'] / 1000, 1) if q else None,
                (datetime.strptime(q['last_at'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=8))
                    .strftime('%Y-%m-%d %H:%M') if q else None,
                status,
            ])
        sheet(wb.create_sheet('测试明细'),
              ['quiz_id', '名称', '全史完成次数', '近30天次数', '近7天次数',
               '去重参与人数', '平均得分率(%)', '平均用时(秒)', '最近参与(北京)', '状态'], rows)

        # 3) 工具明细
        tool_keys = sorted({k for k in stat_counts if k.startswith('tool_')} |
                           {k for k in key_day if k.startswith('tool_')})
        rows = []
        for k in tool_keys:
            n30 = d30(k)
            rows.append([
                k, names.get(k, k), stat_counts.get(k, 0), n30, d7(k),
                key_last.get(k, '') or '',
                '活跃' if n30 > 0 else '沉睡(近30天零使用)',
            ])
        sheet(wb.create_sheet('工具明细'),
              ['key', '名称', '全史使用次数', '近30天次数', '近7天次数',
               '最近使用(北京)', '状态'], rows)

        # 4) 文章明细(article_* 阅读计数,小程序上报 key=article_<id> name=标题)
        art_keys = sorted({k for k in stat_counts if k.startswith('article_')} |
                          {k for k in key_day if k.startswith('article_')})
        rows = []
        for k in art_keys:
            n30 = d30(k)
            rows.append([
                k, names.get(k, k), stat_counts.get(k, 0), n30, d7(k),
                key_last.get(k, '') or '',
                '活跃' if n30 > 0 else '沉睡(近30天零阅读)',
            ])
        sheet(wb.create_sheet('文章明细'),
              ['key', '标题', '全史阅读次数', '近30天次数', '近7天次数',
               '最近阅读(北京)', '状态'], rows)

        # 5) 每日趋势(近30天,带星期,方便AI看周期性)
        wd_cn = '一二三四五六日'
        rows = []
        for d in days:
            w = '周' + wd_cn[datetime.strptime(d, '%Y-%m-%d').weekday()]
            rows.append([d, w, tests_by_day.get(d, 0), tools_by_day.get(d, 0),
                         scores_by_day.get(d, 0), rooms_by_day.get(d, 0)])
        sheet(wb.create_sheet('每日趋势'),
              ['日期', '星期', '测试次数', '工具次数', '新增成绩', '新建房间'], rows)

        # 6) 今日按小时(当天各时间点的实时分布)
        sheet(wb.create_sheet('今日按小时'), ['小时(北京)', '测试次数', '工具次数'],
              [[f'{h}:00', t_by_h.get(h, 0), g_by_h.get(h, 0)] for h in hours])

        # 7) 综合排名Top10(与小程序 /rank/overall 同口径)
        sheet(wb.create_sheet('综合排名'),
              ['排名', '昵称', '平均击败率(%)', '参与测试数'],
              [[p['rank'], p['nickname'], p['avg_beat'], p['quizzes']]
               for p in board['top']])

        # 8) PK房间明细(漏斗分析素材:多少房死在"等B加入")
        now_utc = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        rows = []
        for r in rooms_all:
            state = 'expired' if r['expires_at'] <= now_utc else r['state']
            created_bj = (datetime.strptime(r['created_at'], '%Y-%m-%d %H:%M:%S')
                          + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
            rows.append([
                r['room_code'], _quiz_display_name(names, r['quiz_id']), state,
                1 + (1 if r['openid_b'] else 0),
                '是' if r['answers_a'] else '否', '是' if r['answers_b'] else '否',
                r['match_percent'] if r['state'] == 'finished' else None, created_bj,
            ])
        sheet(wb.create_sheet('PK房间'),
              ['房间码', '测试', '状态', '玩家数', 'A已提交', 'B已提交',
               '默契度(%)', '建房时间(北京)'], rows)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = f"mp_report_{now_bj.strftime('%Y%m%d_%H%M')}.xlsx"
        logger.info(f'[mp-admin] 导出Excel报表: {fname}')
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=fname)
    except Exception as e:
        error_logger.error(f'mp-admin export 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500
