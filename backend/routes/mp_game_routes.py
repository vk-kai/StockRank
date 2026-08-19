# -*- coding: utf-8 -*-
"""微信小程序游戏化接口:全国排行榜 + 双人异地默契PK。

挂在现有 Flask 进程里,SQLite(data/mp_game.db, WAL)存储,零新增服务/线程:
  POST /api/mp/game/score          上报成绩(客户端判分+服务端合理性校验)
  GET  /api/mp/game/rank           我的排名(击败比例)+ TOP10
  POST /api/mp/game/room           创建PK房间(4位房间码)
  POST /api/mp/game/room/join      加入房间
  POST /api/mp/game/room/answer    提交本人答案(双方交齐时服务端算合拍度)
  GET  /api/mp/game/room/status    轮询房间状态(小程序每3秒一次)
  GET  /api/mp/game/room/detail    逐题对照(双方交卷后)
  POST /api/mp/game/stat/inc       测试参与计数+1(「xx人在测」,不去重)
  GET  /api/mp/game/stat           批量查询计数(缺省0,最多20个key)

鉴权复用 mp_sec_routes 的 X-Auth-Key;业务失败统一 HTTP 200 + success:false + 中文 message。
限频:score 6次/分、room创建 10次/时、其余 30次/分(按 openid)。
房间过期清理:懒删除(房间操作时顺带 DELETE,5分钟节流),不开新线程。
"""
import os
import json
import re
import time
import random
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from core.config import DATA_DIR
from core.logger import get_logger
from routes.mp_sec_routes import _check_auth_key, _call_wx_api

mp_game_bp = Blueprint('mp_game', __name__, url_prefix='/api/mp/game')
logger = get_logger('system')
error_logger = get_logger('error')

DB_FILE = os.path.join(DATA_DIR, 'mp_game.db')
DEFAULT_NICKNAME = '匿名测试者'
ROOM_TTL_HOURS = 24
MAX_ANSWERS = 64
ANSWER_CHARS = set('ABCDEF')
RANK_CACHE_TTL = 60          # 榜单缓存秒数
ROOM_PURGE_INTERVAL = 300    # 过期房间懒清理节流

_rl_lock = threading.Lock()
_rl_store = {}               # {(action, openid): [时间戳...]} 滑动窗口限频
_rank_cache = {}             # {quiz_id: {'ts', 'total', 'top'}}
_nick_ok_cache = {}          # 昂贵的 msgSecCheck 结果缓存:昵称->通过
_purge_lock = threading.Lock()
_last_purge = 0.0

STAT_KEY_RE = re.compile(r'^[a-z0-9_]{1,64}$')
STAT_DEDUP_SECONDS = 10      # 同 openid+key 防脚本窗口(不是去重,产品要求重复测试照常+1)
STAT_CACHE_TTL = 60
_stat_lock = threading.Lock()
_stat_dedup = {}             # {(openid, key): 上次计入时间戳} 内存级,重启丢失无所谓
_stat_cache = {}             # {key: {'ts', 'count'}} 查询缓存,inc 主动失效


# --------------------------------------------------------------------------
# SQLite 基础设施
# --------------------------------------------------------------------------
@contextmanager
def _db():
    conn = sqlite3.connect(DB_FILE, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('''CREATE TABLE IF NOT EXISTS scores (
            quiz_id     TEXT NOT NULL,
            openid      TEXT NOT NULL,
            nickname    TEXT,
            score       INTEGER NOT NULL,
            full_score  INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            answers     TEXT,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (quiz_id, openid)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_scores_rank ON scores(quiz_id, score DESC)')
        conn.execute('''CREATE TABLE IF NOT EXISTS rooms (
            room_code      TEXT PRIMARY KEY,
            quiz_id        TEXT NOT NULL,
            openid_a       TEXT NOT NULL,
            answers_a      TEXT,
            submitted_a_at TEXT,
            openid_b       TEXT,
            answers_b      TEXT,
            submitted_b_at TEXT,
            state          TEXT NOT NULL DEFAULT 'waiting',
            answer_count   INTEGER,
            match_percent  INTEGER,
            match_detail   TEXT,
            expires_at     TEXT NOT NULL,
            created_at     TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS stats (
            key       TEXT PRIMARY KEY,
            count     INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rooms_expire ON rooms(expires_at)')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


# --------------------------------------------------------------------------
# 限频 / 缓存 / 懒清理
# --------------------------------------------------------------------------
def _rate_limited(action, openid, limit, window_s):
    """滑动窗口限频。超限返回 True。"""
    now = time.time()
    with _rl_lock:
        key = (action, openid)
        hits = [t for t in _rl_store.get(key, []) if now - t < window_s]
        if len(hits) >= limit:
            _rl_store[key] = hits
            return True
        hits.append(now)
        _rl_store[key] = hits
        if len(_rl_store) > 10000:  # 防膨胀:原地重建,丢弃已过期窗口
            stale = {k: v for k, v in _rl_store.items() if v and now - v[-1] < 3600}
            _rl_store.clear()
            _rl_store.update(stale)
        return False


def _purge_expired_rooms(force=False):
    """删除过期房间(懒清理,节流5分钟,不开线程)。"""
    global _last_purge
    now = time.time()
    if not force and now - _last_purge < ROOM_PURGE_INTERVAL:
        return
    with _purge_lock:
        if not force and now - _last_purge < ROOM_PURGE_INTERVAL:
            return
        try:
            with _db() as conn:
                cur = conn.execute('DELETE FROM rooms WHERE expires_at <= ?', (_utcnow(),))
                if cur.rowcount:
                    logger.info(f'已清理过期PK房间 {cur.rowcount} 个')
        except Exception as e:
            error_logger.error(f'清理过期房间失败: {e}')
        _last_purge = now


def _check_nickname(nickname, openid):
    """昵称过 msgSecCheck;任何失败/不合规一律回退默认昵称,绝不让成绩丢失。"""
    nickname = (nickname or '').strip()
    if not nickname or len(nickname) > 12:
        return DEFAULT_NICKNAME
    if nickname in _nick_ok_cache:
        return nickname
    try:
        resp = _call_wx_api('/wxa/msg_sec_check', {
            'version': 2, 'openid': openid, 'scene': 1, 'content': nickname})
        ok = resp.get('errcode') == 0 and (resp.get('result') or {}).get('suggest') == 'pass'
    except Exception as e:
        error_logger.warning(f'昵称安全校验异常(按默认昵称处理): {e}')
        ok = False
    if not ok:
        return DEFAULT_NICKNAME
    _nick_ok_cache[nickname] = True
    if len(_nick_ok_cache) > 1000:
        _nick_ok_cache.clear()
    return nickname


def _fetch_room(conn, room_code):
    """取未过期房间;过期则顺手删掉返回 None。"""
    row = conn.execute('SELECT * FROM rooms WHERE room_code = ?', (room_code,)).fetchone()
    if not row:
        return None
    if row['expires_at'] <= _utcnow():
        conn.execute('DELETE FROM rooms WHERE room_code = ?', (room_code,))
        return None
    return row


def _compute_match(answers_a, answers_b):
    """合拍度:一致题数/总题数*100 取整 + 逐题明细(a/b 中性视角)。"""
    pairs = list(zip(answers_a, answers_b))
    same = sum(1 for x, y in pairs if x == y)
    percent = int(round(same / len(pairs) * 100)) if pairs else 0
    detail = [{'q': i + 1, 'same': x == y, 'a': x, 'b': y} for i, (x, y) in enumerate(pairs)]
    return percent, detail


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 一、排行榜
# --------------------------------------------------------------------------
@mp_game_bp.route('/score', methods=['POST'])
def submit_score():
    """上报成绩。同人同测试只记最佳(分数更高,同分用时更短才覆盖)。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        quiz_id = str(data.get('quiz_id') or '').strip()
        if not openid or not quiz_id:
            return jsonify({'success': False, 'message': '缺少 openid 或 quiz_id'})
        if _rate_limited('score', openid, 6, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        score = _parse_int(data.get('score'))
        full_score = _parse_int(data.get('full_score'))
        duration_ms = _parse_int(data.get('duration_ms'))
        answer_count = _parse_int(data.get('answer_count') or 0)
        if None in (score, full_score, duration_ms):
            return jsonify({'success': False, 'message': '成绩参数格式错误'})
        if not (0 < full_score <= 1000) or not (0 <= score <= full_score):
            return jsonify({'success': False, 'message': '成绩参数不合法'})
        if not (0 < answer_count <= MAX_ANSWERS):
            return jsonify({'success': False, 'message': '题目数量不合法'})
        if duration_ms < answer_count * 800 or not (0 < duration_ms <= 86400000):
            return jsonify({'success': False, 'message': '答题时长异常'})

        # answers 可选:长度/字符不符则忽略该字段,成绩照收(为将来服务端判分预留)
        answers = str(data.get('answers') or '').strip().upper()
        if not answers or len(answers) != answer_count or not set(answers) <= ANSWER_CHARS:
            answers = None

        nickname = _check_nickname(str(data.get('nickname') or ''), openid)

        with _db() as conn:
            conn.execute('''INSERT INTO scores
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(quiz_id, openid) DO UPDATE SET
                    nickname = excluded.nickname,
                    score = excluded.score,
                    full_score = excluded.full_score,
                    duration_ms = excluded.duration_ms,
                    answers = excluded.answers,
                    created_at = excluded.created_at
                WHERE excluded.score > scores.score
                   OR (excluded.score = scores.score AND excluded.duration_ms < scores.duration_ms)''',
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, _utcnow()))
        _rank_cache.pop(quiz_id, None)
        return jsonify({'success': True, 'message': '已记录'})
    except Exception as e:
        error_logger.error(f'score 上报异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/rank', methods=['GET'])
def query_rank():
    """我的排名 + TOP10。total/top 缓存60秒,mine 实时算。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        quiz_id = (request.args.get('quiz_id') or '').strip()
        openid = (request.args.get('openid') or '').strip()
        if not quiz_id or not openid:
            return jsonify({'success': False, 'message': '缺少 quiz_id 或 openid'})
        if _rate_limited('rank', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        now = time.time()
        cached = _rank_cache.get(quiz_id)
        if not cached or now - cached['ts'] > RANK_CACHE_TTL:
            with _db() as conn:
                total = conn.execute('SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ?',
                                     (quiz_id,)).fetchone()['c']
                top = [{'nickname': r['nickname'] or DEFAULT_NICKNAME,
                        'score': r['score'], 'duration_ms': r['duration_ms']}
                       for r in conn.execute('''SELECT nickname, score, duration_ms FROM scores
                           WHERE quiz_id = ? ORDER BY score DESC, duration_ms ASC LIMIT 10''',
                           (quiz_id,))]
            cached = {'ts': now, 'total': total, 'top': top}
            _rank_cache[quiz_id] = cached

        mine = {'found': False}
        with _db() as conn:
            row = conn.execute('SELECT score, duration_ms FROM scores WHERE quiz_id = ? AND openid = ?',
                               (quiz_id, openid)).fetchone()
        if row:
            with _db() as conn:
                better = conn.execute('''SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ?
                    AND (score > ? OR (score = ? AND duration_ms < ?))''',
                    (quiz_id, row['score'], row['score'], row['duration_ms'])).fetchone()['c']
                strictly_less = conn.execute('SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ? AND score < ?',
                                             (quiz_id, row['score'])).fetchone()['c']
            total = cached['total']
            mine = {
                'found': True,
                'score': row['score'],
                'rank': better + 1,
                'beat_percent': round(strictly_less / total * 100, 1) if total else 0.0,
            }
        return jsonify({'success': True, 'total': cached['total'], 'mine': mine, 'top': cached['top']})
    except Exception as e:
        error_logger.error(f'rank 查询异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


# --------------------------------------------------------------------------
# 二、双人 PK
# --------------------------------------------------------------------------
@mp_game_bp.route('/room', methods=['POST'])
def create_room():
    """创建PK房间,返回4位数字房间码。可带 answer_count 存题数供答案校验。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        quiz_id = str(data.get('quiz_id') or '').strip()
        if not openid or not quiz_id:
            return jsonify({'success': False, 'message': '缺少 openid 或 quiz_id'})
        if _rate_limited('room_create', openid, 10, 3600):
            return jsonify({'success': False, 'message': '创建太频繁，请稍后再试'})
        answer_count = _parse_int(data.get('answer_count')) if data.get('answer_count') else None
        if answer_count is not None and not (0 < answer_count <= MAX_ANSWERS):
            return jsonify({'success': False, 'message': '题目数量不合法'})

        _purge_expired_rooms()
        now_str = _utcnow()
        expires = (datetime.now(timezone.utc) + timedelta(hours=ROOM_TTL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
        room_code = None
        for _ in range(20):  # 4位码9000个,冲突重试
            code = str(random.randint(1000, 9999))
            try:
                with _db() as conn:
                    conn.execute('''INSERT INTO rooms
                        (room_code, quiz_id, openid_a, state, answer_count, expires_at, created_at)
                        VALUES (?, ?, ?, 'waiting', ?, ?, ?)''',
                        (code, quiz_id, openid, answer_count or None, expires, now_str))
                room_code = code
                break
            except sqlite3.IntegrityError:
                continue
        if not room_code:
            return jsonify({'success': False, 'message': '房间码分配失败，请重试'})
        logger.info(f'PK房间已创建: {room_code} quiz={quiz_id}')
        return jsonify({'success': True, 'room_code': room_code, 'expires_in': ROOM_TTL_HOURS * 3600})
    except Exception as e:
        error_logger.error(f'创建房间异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/room/join', methods=['POST'])
def join_room():
    """B 加入房间。同人重复加入幂等;房间满/自PK给对应中文提示。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        room_code = str(data.get('room_code') or '').strip()
        openid = str(data.get('openid') or '').strip()
        if not room_code or not openid:
            return jsonify({'success': False, 'message': '缺少 room_code 或 openid'})
        if _rate_limited('join', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        with _db() as conn:
            room = _fetch_room(conn, room_code)
            if not room:
                return jsonify({'success': False, 'message': '房间不存在或已过期'})
            if openid == room['openid_a']:
                return jsonify({'success': False, 'message': '不能和自己 PK 哦'})
            if room['openid_b']:
                if openid == room['openid_b']:
                    # 幂等:重复加入直接返回当前状态
                    return jsonify({'success': True, 'state': room['state'], 'quiz_id': room['quiz_id']})
                return jsonify({'success': False, 'message': '房间已满'})
            conn.execute("UPDATE rooms SET openid_b = ?, state = 'ready' WHERE room_code = ?",
                         (openid, room_code))
            state = 'ready'
        return jsonify({'success': True, 'state': state, 'quiz_id': room['quiz_id']})
    except Exception as e:
        error_logger.error(f'加入房间异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/room/answer', methods=['POST'])
def submit_answer():
    """提交本人答案(按 openid 判 a/b 侧,幂等覆盖);双方交齐置 finished 并算合拍度。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        room_code = str(data.get('room_code') or '').strip()
        openid = str(data.get('openid') or '').strip()
        answers = str(data.get('answers') or '').strip().upper()
        if not room_code or not openid or not answers:
            return jsonify({'success': False, 'message': '缺少 room_code、openid 或 answers'})
        if _rate_limited('answer', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})
        if len(answers) > MAX_ANSWERS or not set(answers) <= ANSWER_CHARS:
            return jsonify({'success': False, 'message': '答案格式不合法'})

        with _db() as conn:
            room = _fetch_room(conn, room_code)
            if not room:
                return jsonify({'success': False, 'message': '房间不存在或已过期'})
            if openid == room['openid_a']:
                side = 'a'
            elif openid == room['openid_b']:
                side = 'b'
            else:
                return jsonify({'success': False, 'message': '你不在该房间中'})

            # 题数校验:优先用创建时存的 answer_count,否则和对方已交答案比对
            other_answers = room['answers_b'] if side == 'a' else room['answers_a']
            if room['answer_count']:
                if len(answers) != room['answer_count']:
                    return jsonify({'success': False, 'message': '答案数量与题目数不符'})
            elif other_answers and len(answers) != len(other_answers):
                return jsonify({'success': False, 'message': '双方题数不一致'})

            now_str = _utcnow()
            if side == 'a':
                conn.execute('UPDATE rooms SET answers_a = ?, submitted_a_at = ? WHERE room_code = ?',
                             (answers, now_str, room_code))
            else:
                conn.execute('UPDATE rooms SET answers_b = ?, submitted_b_at = ? WHERE room_code = ?',
                             (answers, now_str, room_code))

            row = conn.execute('SELECT * FROM rooms WHERE room_code = ?', (room_code,)).fetchone()
            both_done = bool(row['answers_a'] and row['answers_b'])
            if both_done:
                percent, detail = _compute_match(row['answers_a'], row['answers_b'])
                conn.execute('''UPDATE rooms SET state = 'finished', match_percent = ?, match_detail = ?
                                WHERE room_code = ?''',
                             (percent, json.dumps(detail, ensure_ascii=False), room_code))
                state = 'finished'
            else:
                state = row['state']
        return jsonify({'success': True, 'state': state, 'both_done': both_done})
    except Exception as e:
        error_logger.error(f'提交答案异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/room/status', methods=['GET'])
def room_status():
    """轮询房间状态(小程序每3秒一次)。match_percent 双方交卷前为 null。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        room_code = (request.args.get('room_code') or '').strip()
        openid = (request.args.get('openid') or '').strip()
        if not room_code or not openid:
            return jsonify({'success': False, 'message': '缺少 room_code 或 openid'})
        if _rate_limited('status', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        with _db() as conn:
            room = _fetch_room(conn, room_code)
            if not room:
                return jsonify({'success': False, 'message': '房间不存在或已过期'})
            players = 1 + (1 if room['openid_b'] else 0)
            i_submitted = (openid == room['openid_a'] and bool(room['answers_a'])) or \
                          (openid == room['openid_b'] and bool(room['answers_b']))
            match_percent = room['match_percent'] if room['state'] == 'finished' else None
        return jsonify({'success': True, 'state': room['state'], 'players': players,
                        'i_submitted': i_submitted, 'match_percent': match_percent})
    except Exception as e:
        error_logger.error(f'房间状态查询异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/room/detail', methods=['GET'])
def room_detail():
    """逐题对照(双方交卷后)。mine/theirs 按请求 openid 视角返回。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        room_code = (request.args.get('room_code') or '').strip()
        openid = (request.args.get('openid') or '').strip()
        if not room_code or not openid:
            return jsonify({'success': False, 'message': '缺少 room_code 或 openid'})
        if _rate_limited('detail', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        with _db() as conn:
            room = _fetch_room(conn, room_code)
            if not room:
                return jsonify({'success': False, 'message': '房间不存在或已过期'})
            if room['state'] != 'finished' or not room['match_detail']:
                return jsonify({'success': False, 'message': '对方还没交卷'})
            i_am_a = openid == room['openid_a']
            detail = [{'q': d['q'], 'same': d['same'],
                       'mine': d['a'] if i_am_a else d['b'],
                       'theirs': d['b'] if i_am_a else d['a']}
                      for d in json.loads(room['match_detail'])]
        return jsonify({'success': True, 'match_percent': room['match_percent'], 'detail': detail})
    except Exception as e:
        error_logger.error(f'逐题对照查询异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


# --------------------------------------------------------------------------
# 三、测试参与计数（「xx人在测」真实数据）
#    每测完一次+1,不去重;同 openid+key 10秒窗口只防脚本连发,不是业务去重。
#    错误响应字段用 error(与本组规范一致)。
# --------------------------------------------------------------------------
@mp_game_bp.route('/stat/inc', methods=['POST'])
def stat_inc():
    """计数+1,返回自增后的最新值。key 如 test_caiyun/test_sbti。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        key = str(data.get('key') or '').strip()
        openid = str(data.get('openid') or '').strip()
        if not key or not openid:
            return jsonify({'success': False, 'error': '参数不完整'})
        if not STAT_KEY_RE.match(key):
            return jsonify({'success': False, 'error': 'key 格式不合法'})
        if _rate_limited('stat_inc', openid, 30, 60):
            return jsonify({'success': False, 'error': '操作太频繁，请稍后再试'})

        now = time.time()
        with _stat_lock:
            allowed = now - _stat_dedup.get((openid, key), 0) >= STAT_DEDUP_SECONDS
        if not allowed:
            # 10秒内连发:吞掉不计,回当前值(正常重测至少几十秒,不受影响)
            with _db() as conn:
                row = conn.execute('SELECT count FROM stats WHERE key = ?', (key,)).fetchone()
            return jsonify({'success': True, 'count': row['count'] if row else 0})

        with _db() as conn:
            row = conn.execute('''INSERT INTO stats(key, count) VALUES (?, 1)
                ON CONFLICT(key) DO UPDATE SET count = count + 1,
                    updated_at = CAST(strftime('%s','now') AS INTEGER)
                RETURNING count''', (key,)).fetchone()
            count = row['count']
        # 写库成功后才登记防刷窗口,失败可立即重试
        with _stat_lock:
            _stat_dedup[(openid, key)] = now
            if len(_stat_dedup) > 10000:  # 防膨胀:丢弃早已过期的窗口
                stale = {k: v for k, v in _stat_dedup.items() if now - v < 60}
                _stat_dedup.clear()
                _stat_dedup.update(stale)
        _stat_cache.pop(key, None)
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        error_logger.error(f'stat inc 异常: {e}')
        return jsonify({'success': False, 'error': f'服务异常: {e}'})


@mp_game_bp.route('/stat', methods=['GET'])
def stat_query():
    """批量查询计数:GET /stat?keys=test_a,test_b。无记录的 key 返回 0。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        keys_raw = (request.args.get('keys') or '').strip()
        if not keys_raw:
            return jsonify({'success': False, 'error': '参数不完整'})
        keys = [k.strip() for k in keys_raw.split(',') if k.strip()]
        keys = [k for k in keys if STAT_KEY_RE.match(k)][:20]  # 最多20个,超出截断

        now = time.time()
        found = {}
        missing = []
        for k in keys:
            c = _stat_cache.get(k)
            if c and now - c['ts'] <= STAT_CACHE_TTL:
                found[k] = c['count']
            else:
                missing.append(k)
        if missing:
            with _db() as conn:
                for k in missing:
                    row = conn.execute('SELECT count FROM stats WHERE key = ?', (k,)).fetchone()
                    v = row['count'] if row else 0
                    _stat_cache[k] = {'ts': now, 'count': v}
                    found[k] = v
        return jsonify({'success': True, 'counts': {k: found.get(k, 0) for k in keys}})
    except Exception as e:
        error_logger.error(f'stat 查询异常: {e}')
        return jsonify({'success': False, 'error': f'服务异常: {e}'})
