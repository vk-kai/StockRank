# -*- coding: utf-8 -*-
"""微信小程序游戏化接口:全国排行榜 + 双人异地默契PK。

挂在现有 Flask 进程里,SQLite(data/mp_game.db, WAL)存储,零新增服务/线程:
  POST /api/mp/game/score          上报成绩(客户端判分+服务端合理性校验)
  GET  /api/mp/game/rank           我的排名(击败比例)+ TOP10
  GET  /api/mp/game/rank/overall   综合排名(≥3个测试上榜,avg_beat=各测试击败率均值)
  POST /api/mp/game/room           创建PK房间(4位房间码)
  POST /api/mp/game/room/join      加入房间
  POST /api/mp/game/room/answer    提交本人答案(双方交齐时服务端算合拍度)
  GET  /api/mp/game/room/status    轮询房间状态(小程序每3秒一次)
  GET  /api/mp/game/room/detail    逐题对照(双方交卷后)
  POST /api/mp/game/stat/inc       测试参与计数+1(「xx人在测」,不去重;echohug_*抱抱例外,永久去重)
  GET  /api/mp/game/stat           批量查询计数(缺省0,最多20个key)
  POST /api/mp/game/echo          弹幕墙发布留言(服务端强制再过一次msgSecCheck,不信客户端)
  GET  /api/mp/game/echo          弹幕墙留言列表(按wall_id,最近7天,ts倒序,默认50条)
  POST /api/mp/game/echo/sub      抱抱推送订阅额度记账(授权一次+1,同一对上限20)

鉴权复用 mp_sec_routes 的 X-Auth-Key;业务失败统一 HTTP 200 + success:false + 中文 message。
限频:score 6次/分、room创建 10次/时、echo留言 10次/分、其余 30次/分(按 openid)。
房间过期清理:懒删除(房间操作时顺带 DELETE,5分钟节流),不开新线程。
"""
import os
import json
import re
import time
import random
import sqlite3
import threading
from bisect import bisect_left
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from core.config import DATA_DIR
from core.logger import get_logger
from routes.mp_sec_routes import (
    _check_auth_key, _call_wx_api, _do_msg_sec_check, local_text_blocked,
)

mp_game_bp = Blueprint('mp_game', __name__, url_prefix='/api/mp/game')
logger = get_logger('system')
error_logger = get_logger('error')

DB_FILE = os.path.join(DATA_DIR, 'mp_game.db')
DEFAULT_NICKNAME = '匿名测试者'
ROOM_TTL_HOURS = 24
ROOM_KEEP_DAYS = 7           # 过期房间再保留7天供后台查看,之后懒清理删除
MAX_ANSWERS = 64
ANSWER_CHARS = set('ABCDEF')
RANK_CACHE_TTL = 60          # 榜单缓存秒数
ROOM_PURGE_INTERVAL = 300    # 过期房间懒清理节流

_rl_lock = threading.Lock()
_rl_store = {}               # {(action, openid): [时间戳...]} 滑动窗口限频
_rank_cache = {}             # {quiz_id: {'ts', 'total', 'top'}}
# 综合榜(全站跨测试聚合)整体缓存:60秒兜底,上报成绩/后台改成绩时主动失效
OVERALL_MIN_QUIZZES = 3      # 上榜门槛:参与≥3个不同测试(不足则 found=false 带 quizzes)
_overall_cache = {'ts': 0.0, 'board': None}
_nick_ok_cache = {}          # 昂贵的 msgSecCheck 结果缓存:昵称->通过
_purge_lock = threading.Lock()
_last_purge = 0.0
_seed_cat_migrated = False   # 种子留言分类回填:每进程只跑一次(幂等,只补 NULL)

# key 统一先转小写再校验/入库:test_careerFit 与 test_careerfit 是同一个计数器
STAT_KEY_RE = re.compile(r'^[a-z0-9_]{1,64}$')
# quiz_id 白名单:客户端上报的测试/工具标识(成绩表、PK房间),英文标识符形态
QUIZ_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
# openid 白名单:微信 openid 形态(字母数字-_);openid 会入库并回显后台,提交时拦截
OPENID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
# 房间码:服务端生成的4位数字,join/answer/status/detail 由客户端回传
ROOM_CODE_RE = re.compile(r'^\d{4}$')
STAT_DEDUP_SECONDS = 10      # 同 openid+key 防脚本窗口(不是去重,产品要求重复测试照常+1)
# 弹幕墙(「抱抱树洞」共鸣墙):wall_id 形如日期 20260906;留言≤50字,列表只回最近7天
WALL_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
ECHO_TEXT_MAX = 50
ECHO_KEEP_DAYS = 7
# 种子补位阈值:当天真实用户留言(is_seed=0)不足该条数时,种子数据跨天补位充数;
# 达到该条数后种子全部隐藏(纯真实列表)。种子主要给冷启动/低峰期撑场面
ECHO_SEED_FILL_REAL_MIN = 10
# 留言分类:白名单枚举,缺省/非法一律落「其他」(前端另有白名单兜底展示)
ECHO_CATEGORIES = ('情感', '压力', '成长', '校园', '生活', '职场', '树洞', '其他')
ECHO_CATEGORY_DEFAULT = '其他'
# 抱抱→订阅消息推送(一次性订阅「点赞提醒」):额度复用 stats KV 计数,
# key=subs_<openid>_<template_id>;前端授权成功调 /echo/sub 记额度+1(同一对
# 上限20防刷),抱抱推送发送成功扣1;无额度/发送失败静默跳过,不影响计数主流程。
ECHO_HUG_KEY_PREFIX = 'echohug_'             # 抱抱计数 key 前缀(/stat/inc)
ECHO_HUG_TEMPLATE_ID = 'MFBBu8GqBoC7_VF41dhJu2ZEVr6jVeDy_eNnjWIKYJs'
ECHO_HUG_PUSH_PAGE = 'pages/echoWall/echoWall'
ECHO_HUG_PUSH_STATE = 'trial'                # miniprogram_state:联调期体验版,上线前切 'formal'
SUBS_KEY_PREFIX = 'subs_'                    # 订阅额度 KV key 前缀(stats 表)
SUBS_QUOTA_MAX = 20                          # 单个 (openid, template_id) 额度上限
TEMPLATE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# 注入防护:复用 Jarvis 攻击模式库(XSS/SQL注入等)对回显字段做入库前检测。
# 全局中间件已在请求层拦截(命中即400+记IP),这里是第二道纵深防线——
# 中间件模式有盲区(编码变形/不完整标签),脏数据一旦入库会回显到管理后台。
try:
    from Jarvis import SecurityChecker as _JarvisChecker
    _sec_checker = _JarvisChecker()
except Exception:            # Jarvis 不可用时降级为仅白名单校验,不阻断业务
    _sec_checker = None


def _field_safe(value):
    """回显字段检测:命中 Jarvis 攻击模式(XSS/SQL注入等)返回 False。"""
    if not _sec_checker or not isinstance(value, str) or not value:
        return True
    return _sec_checker.check(value) is None


def _safe_nick(nickname):
    """昵称回显兜底(玩家排行榜/后台列表共用):空/含攻击特征一律显示默认昵称。"""
    if not nickname or not _field_safe(nickname):
        return DEFAULT_NICKNAME
    return nickname


STAT_CACHE_TTL = 60
# key→中文名 内置兜底映射(小程序端 /stat/inc 现已自带 name 字段优先入库;
# 这里只兜底:早期没传过 name 的 key、以及还没触发过计数的新 key)。
# 映射的 key 统一小写:入库的 stat key 一律小写归一,驼峰写法查不到
STAT_KEY_NAMES = {k.lower(): v for k, v in {
    'test_careerFit': '职业适配测试', 'test_childCreativity': '创造力测试',
    'test_childEmotion': '情绪管理测试', 'test_childFocus': '专注力测试',
    'test_childIntelligence': '智力测试', 'test_childLogic': '逻辑测试',
    'test_childSocial': '社交测试', 'test_company': '职场测试',
    'test_decisionStyle': '决策风格测试', 'test_fortune': '财运测试',
    'test_friend': '好友印象测试', 'test_health': '健康测试',
    'test_lifestyle': '生活测试', 'test_love': '真爱定位测试',
    'test_loveAttraction': '恋爱吸引力测试', 'test_loveCommunication': '恋爱沟通力测试',
    'test_loveDifficulty': '恋爱难追测试', 'test_loveReunionChance': '复合可能性测试',
    'test_loveTiming': '脱单时间测试', 'test_mbti': 'MBTI人格测试',
    'test_pastlifeWho': '前世测试', 'test_personality': '性格测试',
    'test_qixiLove': '七夕鹊桥缘', 'test_richChance': '暴富测试',
    'test_sbti': 'SBTI人格测试', 'test_stress': '心理测试',
    'test_wealthTalent': '赚钱天赋测试', 'test_wealthTime': '发财时间测试',
    'tool_danmaku': '手持弹幕', 'tool_beadArt': '拼豆图纸生成器',
    'tool_beadString': '串珠排珠计算器', 'tool_sketch': '照片转素描',
    'tool_gridCut': '九宫格切图', 'tool_avatar': '头像挂件',
    'tool_signature': '艺术签名设计', 'tool_coupleTest': '情侣契合度',
    'tool_friendPK': '好友PK', 'tool_giftMoney': '随礼金额计算器',
    'tool_pkRoom': '双人默契大作战', 'tool_fortune': '每日运势签',
    'tool_horoscope': '今日星座运势', 'tool_zodiacMatch': '十二星座配对',
    'tool_foodWheel': '吃什么转盘', 'tool_countdown': '倒数日',
    'tool_echowall': '抱抱树洞',
}.items()}
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
        # 每次真实 +1 记一条流水（不含被10秒窗口吞掉的），供后台「每日测试人次」趋势图
        # openid 用于事后按人清理联调脏数据(回滚其贡献的计数)
        conn.execute('''CREATE TABLE IF NOT EXISTS stat_log (
            id  INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            ts  INTEGER NOT NULL,
            openid TEXT
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_stat_log_ts ON stat_log(ts)')
        # 旧库迁移:stat_log 早期无 openid 列,补上(新库 CREATE 已带,ALTER 报重复列则忽略)
        try:
            conn.execute('ALTER TABLE stat_log ADD COLUMN openid TEXT')
        except sqlite3.OperationalError:
            pass
        # key→中文名 KV(小程序 /stat/inc 自带 name,后写覆盖先写)
        conn.execute('''CREATE TABLE IF NOT EXISTS stat_names (
            key  TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )''')
        # 弹幕墙留言(「抱抱树洞」):每面墙按 wall_id(如日期 20260906)隔离,
        # 列表只回最近7天;openid 仅存档用于限频/清理,绝不随列表下发。
        # hugs 列=种子留言的预设抱抱数(真实用户留言恒0,真实抱抱走 echohug_ 计数);
        # is_seed=冷启动种子数据标记,后台列表带角标区分
        conn.execute('''CREATE TABLE IF NOT EXISTS echo_wall (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            wall_id  TEXT NOT NULL,
            openid   TEXT NOT NULL,
            nickname TEXT,
            text     TEXT NOT NULL,
            category TEXT,
            hugs     INTEGER NOT NULL DEFAULT 0,
            is_seed  INTEGER NOT NULL DEFAULT 0,
            ts       INTEGER NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_echo_wall ON echo_wall(wall_id, ts)')
        # 旧库迁移:echo_wall 早期无 is_seed 列(种子数据标记),补上
        try:
            conn.execute('ALTER TABLE echo_wall ADD COLUMN is_seed INTEGER NOT NULL DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        # 旧库迁移:echo_wall 无 category 列(留言分类),补上;历史 NULL 值查询时按「其他」返回
        try:
            conn.execute('ALTER TABLE echo_wall ADD COLUMN category TEXT')
        except sqlite3.OperationalError:
            pass
        # 抱抱永久去重:同一 openid 对同一条留言(echohug_<留言id>)终身只计一次,
        # 重复点 /stat/inc 直接返回当前值;admin 删留言时连带清掉
        conn.execute('''CREATE TABLE IF NOT EXISTS echo_hugs (
            hug_key TEXT NOT NULL,
            openid  TEXT NOT NULL,
            ts      INTEGER NOT NULL,
            PRIMARY KEY (hug_key, openid)
        )''')
        # 留言用户封禁:后台按 openid 手动封禁(永久或 N 天),只挡发布留言,
        # 不影响抱抱/成绩等其他功能;到期懒失效(查询时比对),过期行保留作历史。
        conn.execute('''CREATE TABLE IF NOT EXISTS echo_bans (
            openid     TEXT PRIMARY KEY,
            reason     TEXT,
            expires_at INTEGER,
            created_at INTEGER NOT NULL
        )''')
        # 旧数据自愈:category 功能上线前导入的种子留言分类为 NULL(导入是全局幂等的,
        # 重导被拒,老数据不会自己长出分类)——按昵称给 is_seed=1 且 category IS NULL
        # 的行回填 ECHO_SEEDS 内置分类。每进程只跑一次;提交成功才标记完成,
        # 中途回滚则下次连接重试。
        global _seed_cat_migrated
        migrate_pending = False
        if not _seed_cat_migrated:
            try:
                from routes.mp_admin_routes import ECHO_SEEDS  # 延迟导入避免循环依赖
                for _nick, _text, _hugs, _cat in ECHO_SEEDS:
                    conn.execute('''UPDATE echo_wall SET category = ?
                        WHERE is_seed = 1 AND nickname = ? AND category IS NULL''',
                        (_cat, _nick))
                migrate_pending = True
            except Exception as e:
                error_logger.warning(f'种子留言分类回填失败(下次连接重试): {e}')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rooms_expire ON rooms(expires_at)')
        yield conn
        conn.commit()
        if migrate_pending:
            _seed_cat_migrated = True
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
    """删除过期超过 ROOM_KEEP_DAYS 天的房间(懒清理,节流5分钟,不开线程)。
    刚过期的房间保留在库里:玩家侧当不存在,后台还能看7天漏斗。"""
    global _last_purge
    now = time.time()
    if not force and now - _last_purge < ROOM_PURGE_INTERVAL:
        return
    with _purge_lock:
        if not force and now - _last_purge < ROOM_PURGE_INTERVAL:
            return
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ROOM_KEEP_DAYS)) \
                .strftime('%Y-%m-%d %H:%M:%S')
            with _db() as conn:
                cur = conn.execute('DELETE FROM rooms WHERE expires_at <= ?', (cutoff,))
                if cur.rowcount:
                    logger.info(f'已清理过期超{ROOM_KEEP_DAYS}天的PK房间 {cur.rowcount} 个')
        except Exception as e:
            error_logger.error(f'清理过期房间失败: {e}')
        _last_purge = now


def _check_nickname(nickname, openid):
    """昵称过 msgSecCheck;任何失败/不合规一律回退默认昵称,绝不让成绩丢失。

    失败原因打详细日志(errcode/errmsg),常见:
      87009  openid 用户近2小时未访问小程序(客户端需重新 wx.login 换 code 走 /sec/login)
      45009  接口调用额度耗尽
      40001/42001 access_token 失效(已自动强刷重试一次,仍失败多为 appsecret 配置错)
    """
    nickname = (nickname or '').strip()
    if not nickname or len(nickname) > 12:
        return DEFAULT_NICKNAME
    # 注入防护(复用Jarvis攻击模式库):昵称会回显到管理后台,先于msgSecCheck拦截,
    # 命中XSS/SQL注入等模式直接回退默认昵称——顺带省一次检测额度
    if not _field_safe(nickname):
        logger.warning(f"昵称含攻击特征(回退默认): openid={openid[:6]}…")
        return DEFAULT_NICKNAME
    # 本地敏感词硬底线(轻度辱骂微信可能判 pass),先拦且不耗检测额度
    if local_text_blocked(nickname):
        logger.warning(f"昵称命中本地敏感词(回退默认): openid={openid[:6]}…")
        return DEFAULT_NICKNAME
    if nickname in _nick_ok_cache:
        return nickname
    try:
        resp = _call_wx_api('/wxa/msg_sec_check', {
            'version': 2, 'openid': openid, 'scene': 1, 'content': nickname})
        errcode = resp.get('errcode')
        ok = errcode == 0 and (resp.get('result') or {}).get('suggest') == 'pass'
        if not ok:
            if errcode == 0:
                # 检测服务正常、内容被拦:正常业务,记 info
                logger.info(f"昵称未过审(回退默认): openid={openid[:6]}… "
                            f"suggest={(resp.get('result') or {}).get('suggest')}")
            else:
                # 检测服务故障:warning 带错误码,便于服务端定位
                error_logger.warning(
                    f"昵称安全检测接口失败(回退默认昵称): errcode={errcode} "
                    f"errmsg={resp.get('errmsg')} openid={openid[:6]}…")
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
    """取未过期房间;过期的对玩家侧视为不存在(不立即删,留7天给后台看漏斗)。"""
    row = conn.execute('SELECT * FROM rooms WHERE room_code = ?', (room_code,)).fetchone()
    if not row:
        return None
    if row['expires_at'] <= _utcnow():
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
        # openid 会入库并回显后台(玩家列),quiz_id 回显到成绩列表/排行榜/趋势页:白名单防注入
        if not OPENID_RE.match(openid) or not QUIZ_ID_RE.match(quiz_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
        # 时长合理性:每题至少0.5秒且整体至少1秒(拦脚本连发),快速真实作答可过;
        # 上限1天。曾用每题0.8秒,实测会误杀点得快的真实玩家(10题5秒被拒)。
        if duration_ms < max(1000, answer_count * 500) or not (0 < duration_ms <= 86400000):
            return jsonify({'success': False, 'message': '答题时长异常'})

        # answers 可选:长度/字符不符则忽略该字段,成绩照收(为将来服务端判分预留)
        answers = str(data.get('answers') or '').strip().upper()
        if not answers or len(answers) != answer_count or not set(answers) <= ANSWER_CHARS:
            answers = None

        nickname = _check_nickname(str(data.get('nickname') or ''), openid)

        with _db() as conn:
            # 昵称检测失败回退默认昵称时,保留库中已有昵称:
            # 避免检测服务故障期间重交成绩,把玩家已通过检测的昵称冲掉
            if nickname == DEFAULT_NICKNAME:
                row = conn.execute('SELECT nickname FROM scores WHERE quiz_id = ? AND openid = ?',
                                   (quiz_id, openid)).fetchone()
                if row and row['nickname']:
                    nickname = row['nickname']
            # 改名需求:昵称无条件更新(低分重交也能改);
            # 成绩相关字段仍只记最佳(分数更高,或同分用时更短)
            better = ('excluded.score > scores.score '
                      'OR (excluded.score = scores.score AND excluded.duration_ms < scores.duration_ms)')
            conn.execute(f'''INSERT INTO scores
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(quiz_id, openid) DO UPDATE SET
                    nickname = excluded.nickname,
                    score = CASE WHEN {better} THEN excluded.score ELSE scores.score END,
                    full_score = CASE WHEN {better} THEN excluded.full_score ELSE scores.full_score END,
                    duration_ms = CASE WHEN {better} THEN excluded.duration_ms ELSE scores.duration_ms END,
                    answers = CASE WHEN {better} THEN excluded.answers ELSE scores.answers END,
                    created_at = CASE WHEN {better} THEN excluded.created_at ELSE scores.created_at END''',
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, _utcnow()))
        _rank_cache.pop(quiz_id, None)
        _overall_cache['ts'] = 0.0   # 综合榜聚合依赖全部成绩,一并失效
        # 返回最终入库昵称,客户端可感知被安全检测替换的情况
        return jsonify({'success': True, 'message': '已记录', 'nickname': nickname})
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
        if not OPENID_RE.match(openid) or not QUIZ_ID_RE.match(quiz_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
        if _rate_limited('rank', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        now = time.time()
        cached = _rank_cache.get(quiz_id)
        if not cached or now - cached['ts'] > RANK_CACHE_TTL:
            with _db() as conn:
                total = conn.execute('SELECT COUNT(*) AS c FROM scores WHERE quiz_id = ?',
                                     (quiz_id,)).fetchone()['c']
                top = [{'nickname': _safe_nick(r['nickname']),
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


def _compute_overall_board():
    """全站综合榜:每人综合分 = 各测试 beat_percent 的平均(击败率跨测试可比)。

    单测试 beat_percent = 击败人数/该榜总人数(与 /rank 同口径,按当前最佳成绩行);
    榜内名次同分按时长 tie-break,也与 /rank 一致。上榜需参与 ≥ OVERALL_MIN_QUIZZES
    个测试。排序:avg_beat 降序 → 参与测试多者优先 → openid 保证稳定。
    best 取击败率最高的测试(并列取榜内名次靠前,再按 quiz_id)。
    """
    with _db() as conn:
        rows = conn.execute('''SELECT quiz_id, openid, nickname, score, duration_ms, created_at
            FROM scores''').fetchall()
    # 每个测试榜预排序:bisect 算「严格更低的分数个数」(击败数)和「严格更好的个数」(名次-1)
    quizzes = {}   # quiz_id -> {'scores': 升序[], 'keys': (-score,duration) 升序[], 'rows': {openid: row}}
    for r in rows:
        q = quizzes.setdefault(r['quiz_id'], {'scores': [], 'keys': [], 'rows': {}})
        q['scores'].append(r['score'])
        q['keys'].append((-r['score'], r['duration_ms']))
        q['rows'][r['openid']] = r
    for q in quizzes.values():
        q['scores'].sort()
        q['keys'].sort()

    players = {}   # openid -> 聚合(未达门槛的用户也保留,供 mine.quizzes 展示)
    for quiz_id, q in quizzes.items():
        total = len(q['scores'])
        for openid, r in q['rows'].items():
            beat = bisect_left(q['scores'], r['score']) / total * 100 if total else 0.0
            rank = bisect_left(q['keys'], (-r['score'], r['duration_ms'])) + 1
            p = players.setdefault(openid, {'beats': [], 'best': None,
                                            'nickname': '', 'latest': ''})
            p['beats'].append(beat)
            cand = {'quiz_id': quiz_id, 'rank': rank, 'score': r['score'], 'beat': beat}
            b = p['best']
            if b is None or (beat, -rank) > (b['beat'], -b['rank']) or \
                    ((beat, -rank) == (b['beat'], -b['rank']) and quiz_id < b['quiz_id']):
                p['best'] = cand
            if r['created_at'] >= p['latest']:   # 昵称取最近一条成绩的,只用于 top 展示
                p['latest'] = r['created_at']
                p['nickname'] = r['nickname']

    ranked = sorted(
        ((openid, p, sum(p['beats']) / len(p['beats']))
         for openid, p in players.items() if len(p['beats']) >= OVERALL_MIN_QUIZZES),
        key=lambda t: (-t[2], -len(t[1]['beats']), t[0]))
    return {
        'total': len(ranked),
        'top': [{'rank': i + 1, 'nickname': _safe_nick(p['nickname']),
                 'avg_beat': round(avg, 1), 'quizzes': len(p['beats'])}
                for i, (_, p, avg) in enumerate(ranked[:10])],
        'players': {openid: {'rank': i + 1, 'quizzes': len(p['beats']),
                             'avg_beat': round(avg, 1),
                             'best': {'quiz_id': p['best']['quiz_id'],
                                      'rank': p['best']['rank'],
                                      'score': p['best']['score']}}
                    for i, (openid, p, avg) in enumerate(ranked)},
        'quiz_counts': {openid: len(p['beats']) for openid, p in players.items()},
    }


def _overall_board_cached():
    """综合榜(带60秒缓存):小程序端点与后台看板共用,写操作主动失效。"""
    now = time.time()
    if not _overall_cache['board'] or now - _overall_cache['ts'] > RANK_CACHE_TTL:
        _overall_cache['board'] = _compute_overall_board()
        _overall_cache['ts'] = now
    return _overall_cache['board']


@mp_game_bp.route('/rank/overall', methods=['GET'])
def query_rank_overall():
    """综合排名。参与<3个测试:mine.found=false 且带 quizzes(前端「再测N个解锁」)。

    total/top/各玩家名次整体缓存60秒;上报成绩或后台改数据时主动失效。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        openid = (request.args.get('openid') or '').strip()
        if not openid:
            return jsonify({'success': False, 'message': '缺少 openid'})
        if not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': '参数格式不合法'})
        if _rate_limited('rank', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})

        board = _overall_board_cached()

        info = board['players'].get(openid)
        mine = ({'found': True, **info} if info
                else {'found': False, 'quizzes': board['quiz_counts'].get(openid, 0)})
        return jsonify({'success': True, 'total': board['total'],
                        'mine': mine, 'top': board['top']})
    except Exception as e:
        error_logger.error(f'overall rank 查询异常: {e}')
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
        # openid/quiz_id 均入库并回显后台PK房间列表,白名单防注入
        if not OPENID_RE.match(openid) or not QUIZ_ID_RE.match(quiz_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
        if not ROOM_CODE_RE.match(room_code) or not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
        if not ROOM_CODE_RE.match(room_code) or not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
        if not ROOM_CODE_RE.match(room_code) or not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
        if not ROOM_CODE_RE.match(room_code) or not OPENID_RE.match(openid):
            return jsonify({'success': False, 'message': '参数格式不合法'})
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
#    (例外:echohug_* 抱抱计数是「同一人对同一条留言」语义,永久去重,见 stat_inc。)
#    key 统一小写归一(兼容 test_careerFit 这类驼峰写法),查询响应按原始写法返回。
#    错误响应字段用 error(与本组规范一致)。
# --------------------------------------------------------------------------
@mp_game_bp.route('/stat/inc', methods=['POST'])
def stat_inc():
    """计数+1,返回自增后的最新值。key 如 test_caiyun/test_sbti,驼峰自动按小写归一。

    echohug_<留言id>(弹幕墙抱抱)例外:同一 openid 对同一条留言永久只计一次,
    重复点返回当前值——去重记录在 echo_hugs 表,重过期/清缓存也不会重复计数。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        key = str(data.get('key') or '').strip().lower()
        openid = str(data.get('openid') or '').strip()
        if not key or not openid:
            return jsonify({'success': False, 'error': '参数不完整'})
        if not STAT_KEY_RE.match(key):
            return jsonify({'success': False, 'error': 'key 格式不合法'})
        if not OPENID_RE.match(openid):
            return jsonify({'success': False, 'error': 'openid 格式不合法'})
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
            # 抱抱永久去重:首点 INSERT 去重表成功才 +1;重复点(哪怕隔了几个月、
            # 或10秒防刷窗口已过)直接返回当前值,不再涨。普通计数不受影响。
            if key.startswith('echohug_'):
                cur = conn.execute('''INSERT INTO echo_hugs(hug_key, openid, ts)
                    VALUES (?, ?, ?) ON CONFLICT(hug_key, openid) DO NOTHING''',
                    (key, openid, int(now)))
                if cur.rowcount == 0:
                    row = conn.execute('SELECT count FROM stats WHERE key = ?',
                                       (key,)).fetchone()
                    return jsonify({'success': True,
                                    'count': row['count'] if row else 0})
            row = conn.execute('''INSERT INTO stats(key, count) VALUES (?, 1)
                ON CONFLICT(key) DO UPDATE SET count = count + 1,
                    updated_at = CAST(strftime('%s','now') AS INTEGER)
                RETURNING count''', (key,)).fetchone()
            count = row['count']
            # 同事务记流水:后台趋势图按天聚合 + 事后按人清理联调数据
            conn.execute('INSERT INTO stat_log(key, ts, openid) VALUES (?, ?, ?)',
                         (key, int(now), openid))
            # 可选中文名:后写覆盖先写,后台展示用(不传不影响计数)
            # name 会回显到后台且能覆盖内置映射,注入检测不过则丢弃(计数照常+1)
            # ≤64:文章标题(article_*)常超30字,与微信标题上限对齐
            name = str(data.get('name') or '').strip()
            if name and len(name) <= 64 and _field_safe(name):
                conn.execute('''INSERT INTO stat_names(key, name) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET name = excluded.name''', (key, name))
            # 抱抱推送挂钩(方案A:第一个抱抱就推,每个新抱抱者都触发一次;
            # 同一抱抱者对同一留言已被上面 echo_hugs 永久去重,不会重复推):
            # 事务内只取作者+心声文本,微信发送放到事务提交后(网络调用不占连接)。
            # 种子留言无真实作者(is_seed=1),查询直接排除
            push_msg = None
            if key.startswith(ECHO_HUG_KEY_PREFIX):
                msg_id = key[len(ECHO_HUG_KEY_PREFIX):]
                if msg_id.isdigit():
                    push_msg = conn.execute(
                        'SELECT openid, text FROM echo_wall WHERE id = ? AND is_seed = 0',
                        (int(msg_id),)).fetchone()
        # 写库成功后才登记防刷窗口,失败可立即重试
        with _stat_lock:
            _stat_dedup[(openid, key)] = now
            if len(_stat_dedup) > 10000:  # 防膨胀:丢弃早已过期的窗口
                stale = {k: v for k, v in _stat_dedup.items() if now - v < 60}
                _stat_dedup.clear()
                _stat_dedup.update(stale)
        _stat_cache.pop(key, None)
        # 抱抱→订阅推送:计数已落库,推送静默失败,绝不影响计数主流程
        if push_msg is not None:
            _send_echo_hug_push(push_msg['openid'], push_msg['text'], openid)
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        error_logger.error(f'stat inc 异常: {e}')
        return jsonify({'success': False, 'error': f'服务异常: {e}'})


@mp_game_bp.route('/stat', methods=['GET'])
def stat_query():
    """批量查询计数:GET /stat?keys=test_a,test_b。无记录的 key 返回 0,响应按原始写法回 key 名。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        keys_raw = (request.args.get('keys') or '').strip()
        if not keys_raw:
            return jsonify({'success': False, 'error': '参数不完整'})
        # 归一key(小写)查库,响应按客户端原始写法返回;最多20个,超出截断
        pairs = []    # [(原始写法, 归一key)]
        seen = set()  # 已收录的归一key(同key不同大小写只查一次)
        for raw in keys_raw.split(','):
            raw = raw.strip()
            norm = raw.lower()
            if raw and norm not in seen and STAT_KEY_RE.match(norm):
                seen.add(norm)
                pairs.append((raw, norm))
                if len(pairs) >= 20:
                    break

        now = time.time()
        found = {}
        missing = []
        for _, norm in pairs:
            c = _stat_cache.get(norm)
            if c and now - c['ts'] <= STAT_CACHE_TTL:
                found[norm] = c['count']
            else:
                missing.append(norm)
        if missing:
            with _db() as conn:
                for k in missing:
                    row = conn.execute('SELECT count FROM stats WHERE key = ?', (k,)).fetchone()
                    v = row['count'] if row else 0
                    _stat_cache[k] = {'ts': now, 'count': v}
                    found[k] = v
        return jsonify({'success': True,
                        'counts': {raw: found.get(norm, 0) for raw, norm in pairs}})
    except Exception as e:
        error_logger.error(f'stat 查询异常: {e}')
        return jsonify({'success': False, 'error': f'服务异常: {e}'})


# --------------------------------------------------------------------------
# 四、弹幕墙（「抱抱树洞」共鸣墙,原名「不止我一个」）
#    发布留言服务端强制再过一次 msgSecCheck(不信任客户端「已检测」的说法,
#    否则绕过客户端直接打接口就能把未检内容塞进墙里);昵称复用成绩那套检测。
#    「抱抱/xx人也这样」计数不新开接口:小程序走 /stat/inc,key 形如 echohug_<留言id>
#    (同一 openid 对同一条留言永久只计一次,去重记录在 echo_hugs 表)。
# --------------------------------------------------------------------------
def _echo_banned(conn, openid):
    """留言封禁检查:存在且未到期(永久封禁 expires_at=NULL)返回 True。

    后台 /mp-admin/echo/ban 维护;到期懒失效不删行,保留作封禁历史。
    """
    row = conn.execute(
        'SELECT 1 FROM echo_bans WHERE openid = ? AND (expires_at IS NULL OR expires_at > ?)',
        (openid, int(time.time()))).fetchone()
    return bool(row)


def _subs_key(openid, template_id):
    """订阅额度 KV 键(复用 stats 计数表):授权一次 count+1,推送成功 count-1。"""
    return f'{SUBS_KEY_PREFIX}{openid}_{template_id}'


def _send_echo_hug_push(author_openid, msg_text, hugger_openid):
    """抱抱→给留言作者发订阅消息(一次性订阅「点赞提醒」)。

    作者有剩余额度才发,发送成功扣1条额度;自己抱自己/无额度/发送失败一律
    静默跳过(抱抱计数主流程不受影响)。thing 关键词上限20字,超长截断。
    """
    try:
        if not author_openid or author_openid == hugger_openid:
            return                    # 自己抱自己不推(计数照常)
        sub_key = _subs_key(author_openid, ECHO_HUG_TEMPLATE_ID)
        with _db() as conn:
            row = conn.execute('SELECT count FROM stats WHERE key = ?', (sub_key,)).fetchone()
        if not row or row['count'] <= 0:
            return                    # 未授权/额度用尽:静默跳过
        bj_now = datetime.now(timezone(timedelta(hours=8)))
        resp = _call_wx_api('/cgi-bin/message/subscribe/send', {
            'touser': author_openid,
            'template_id': ECHO_HUG_TEMPLATE_ID,
            'page': ECHO_HUG_PUSH_PAGE,
            'miniprogram_state': ECHO_HUG_PUSH_STATE,   # 联调期体验版,上线切 'formal'
            'lang': 'zh_CN',
            'data': {
                'thing3': {'value': '一位温暖的路人'},  # 匿名树洞氛围,不暴露抱抱者
                'thing1': {'value': msg_text[:20]},     # 心声前20字摘要
                'time2': {'value': bj_now.strftime('%Y-%m-%d %H:%M')},
            },
        })
        if resp.get('errcode') == 0:
            with _db() as conn:
                conn.execute('''UPDATE stats SET count = count - 1,
                    updated_at = CAST(strftime('%s','now') AS INTEGER)
                    WHERE key = ? AND count > 0''', (sub_key,))
            logger.info(f'抱抱推送成功: to={author_openid[:6]}…')
        else:
            # 43101=用户未订阅/授权耗尽等:微信侧未消耗授权,本地额度不扣
            logger.info(f'抱抱推送未发出(errcode={resp.get("errcode")}),静默跳过')
    except Exception as e:
        error_logger.warning(f'抱抱推送异常(静默跳过,不影响计数): {e}')


@mp_game_bp.route('/echo', methods=['POST'])
def echo_post():
    """发布弹幕墙留言。body: {openid, wall_id, text, nickname?}。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        wall_id = str(data.get('wall_id') or '').strip()
        text = str(data.get('text') or '').strip()
        if not openid or not wall_id or not text:
            return jsonify({'success': False, 'message': '参数不完整'})
        # openid 入库存档;wall_id/text 会回显给所有访问者,白名单+长度先拦
        if not OPENID_RE.match(openid) or not WALL_ID_RE.match(wall_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
        if len(text) > ECHO_TEXT_MAX:
            return jsonify({'success': False, 'message': f'留言最多{ECHO_TEXT_MAX}字'})
        if _rate_limited('echo', openid, 10, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})
        # 封禁检查:被封用户直接拒(放内容送检之前,不烧微信检测额度)
        with _db() as conn:
            if _echo_banned(conn, openid):
                return jsonify({'success': False, 'message': '你已被封禁，暂时无法留言'})
        # 注入防护先拦一道(XSS/SQL注入模式),省一次微信检测额度
        if not _field_safe(text):
            return jsonify({'success': False, 'message': '内容含违规信息'})
        # 本地敏感词硬底线:轻度辱骂微信 msgSecCheck 可能判 pass(实测),
        # 不依赖微信可用性与判定,先拦——裸词/加空格/全角变体都拦
        if local_text_blocked(text):
            logger.info(f'echo 留言命中本地敏感词(拒绝): wall={wall_id} openid={openid[:6]}…')
            return jsonify({'success': False, 'message': '内容含违规信息'})
        # 内容安全:服务端自己送检(scene=2 评论),检测结果不信任客户端
        try:
            resp = _do_msg_sec_check(openid, text, 2)
            checked = resp.get('errcode') == 0
            safe = checked and (resp.get('result') or {}).get('suggest') == 'pass'
        except Exception as e:
            error_logger.warning(f'echo 留言送检异常(拒绝入库): {e}')
            checked, safe = False, False
        if not checked:
            # 检测服务故障:宁可拒发也不放未检内容上墙(内容审核风险 > 体验)
            return jsonify({'success': False, 'message': '内容检测暂不可用，请稍后再试'})
        if not safe:
            return jsonify({'success': False, 'message': '内容含违规信息'})

        nickname = _check_nickname(str(data.get('nickname') or ''), openid)
        # 分类:不在白名单/缺省一律落「其他」,不做严格校验(前端另有兜底展示)
        category = str(data.get('category') or '').strip()
        if category not in ECHO_CATEGORIES:
            category = ECHO_CATEGORY_DEFAULT
        with _db() as conn:
            cur = conn.execute('''INSERT INTO echo_wall(wall_id, openid, nickname, text, category, hugs, ts)
                VALUES (?, ?, ?, ?, ?, 0, ?)''',
                (wall_id, openid, nickname, text, category, int(time.time())))
            new_id = cur.lastrowid
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        error_logger.error(f'echo 发布异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/echo', methods=['GET'])
def echo_list():
    """弹幕墙留言列表。GET /echo?wall_id=20260906&limit=50(1~100,默认50)。

    只回最近 ECHO_KEEP_DAYS 天,ts 倒序;openid 不出库(列表只有展示字段)。
    种子补位:当天真实用户留言不足 ECHO_SEED_FILL_REAL_MIN 条时,种子数据
    跨天补位(不限 wall_id/天数);够了则种子全部隐藏,纯真实列表。
    hugs = 种子留言预设数(hugs 列) + 真实抱抱数(echohug_<留言id> 计数,永久去重),
    前端不必再拉一次 /stat 合并。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        wall_id = (request.args.get('wall_id') or '').strip()
        if not wall_id:
            return jsonify({'success': False, 'message': '缺少 wall_id'})
        if not WALL_ID_RE.match(wall_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
        limit = _parse_int(request.args.get('limit')) or 50
        limit = max(1, min(limit, 100))
        cutoff = int(time.time()) - ECHO_KEEP_DAYS * 86400
        with _db() as conn:
            # 真实用户留言(is_seed=0):优先返回,窗口/排序/上限与原逻辑一致
            rows = conn.execute('''SELECT id, text, nickname, category, hugs, ts FROM echo_wall
                WHERE wall_id = ? AND is_seed = 0 AND ts >= ?
                ORDER BY ts DESC, id DESC LIMIT ?''',
                (wall_id, cutoff, limit)).fetchall()
            # 种子补位:展示条数不足阈值时按当天真实总数(不受 limit 截断影响)复核,
            # 确实不足 → 种子跨天补位凑到 limit;真实够了 → 种子全隐藏
            if len(rows) < ECHO_SEED_FILL_REAL_MIN:
                real_count = conn.execute(
                    'SELECT COUNT(*) AS c FROM echo_wall WHERE wall_id = ? AND is_seed = 0',
                    (wall_id,)).fetchone()['c']
                if real_count < ECHO_SEED_FILL_REAL_MIN:
                    seeds = conn.execute('''SELECT id, text, nickname, category, hugs, ts
                        FROM echo_wall WHERE is_seed = 1 ORDER BY ts DESC, id DESC LIMIT ?''',
                        (limit - len(rows),)).fetchall()
                    rows = sorted(list(rows) + list(seeds),
                                  key=lambda r: (r['ts'], r['id']), reverse=True)
            # 实时抱抱数:echohug_<留言id> 批量查一把(≤100个key,PK索引)
            hug = {}
            if rows:
                keys = [f'echohug_{r["id"]}' for r in rows]
                marks = ','.join('?' * len(keys))
                hug = {r['key']: r['count'] for r in conn.execute(
                    f'SELECT key, count FROM stats WHERE key IN ({marks})', keys)}
        # category:历史数据 NULL 统一按「其他」返回,前端按 it.category 白名单兜底展示
        return jsonify({'success': True,
                        'list': [{'id': r['id'], 'text': r['text'],
                                  'nickname': _safe_nick(r['nickname']),
                                  'category': r['category'] or ECHO_CATEGORY_DEFAULT,
                                  'hugs': r['hugs'] + hug.get(f'echohug_{r["id"]}', 0),
                                  'ts': r['ts']} for r in rows]})
    except Exception as e:
        error_logger.error(f'echo 查询异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})


@mp_game_bp.route('/echo/sub', methods=['POST'])
def echo_sub():
    """订阅授权记账:前端订阅授权成功后调用,为 (openid, template_id) 记额度+1。

    一次性订阅语义:授权一次=可推1条;额度复用 stats KV(key=subs_<openid>_
    <template_id>),同一对上限 SUBS_QUOTA_MAX 防刷,到顶后继续调用只返回上限值。
    返回 {success, total: 当前剩余额度}。错误响应字段与 echo 组一致用 message。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = str(data.get('openid') or '').strip()
        template_id = str(data.get('template_id') or '').strip()
        if not openid or not template_id:
            return jsonify({'success': False, 'message': '参数不完整'})
        if not OPENID_RE.match(openid) or not TEMPLATE_ID_RE.match(template_id):
            return jsonify({'success': False, 'message': '参数格式不合法'})
        if _rate_limited('echo_sub', openid, 30, 60):
            return jsonify({'success': False, 'message': '操作太频繁，请稍后再试'})
        with _db() as conn:
            key = _subs_key(openid, template_id)
            prev = conn.execute('SELECT count FROM stats WHERE key = ?', (key,)).fetchone()
            # CASE 守护上限:到顶后不再自增,RETURNING 仍回当前值(前端好提示)
            row = conn.execute('''INSERT INTO stats(key, count) VALUES (?, 1)
                ON CONFLICT(key) DO UPDATE SET
                    count = CASE WHEN count < ? THEN count + 1 ELSE count END,
                    updated_at = CAST(strftime('%s','now') AS INTEGER)
                RETURNING count''', (key, SUBS_QUOTA_MAX)).fetchone()
            # 真正涨了额度才记流水:后台「订阅额度」页签靠它展示首次/最近订阅时间
            # (推送扣减不写流水,不污染订阅时间;后台热力图查询已排除 subs_*)
            if row['count'] > (prev['count'] if prev else 0):
                conn.execute('INSERT INTO stat_log(key, ts, openid) VALUES (?, ?, ?)',
                             (key, int(time.time()), openid))
        return jsonify({'success': True, 'total': row['count']})
    except Exception as e:
        error_logger.error(f'echo 订阅记账异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'})
