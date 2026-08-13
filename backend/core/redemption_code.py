"""兑换码（体验访问）服务 —— 一次性 + 固定池 + 自动补足 + 历史留存。

设计语义（与产品决策一致）：
1. **一次性**：一张码被成功兑换后即作废，移入历史（used），不可重复兑换。
2. **固定池**：永远维持 pool_size(默认 10) 张"未使用"的可用码（active）。
3. **自动补足**：每兑换一张，立即补一张**同款**（同 page/label/duration）新码进 active，
   保证池子始终满。生成新码时校验 `len(active)+count ≤ pool_size`，超额拒绝（不能多生成）。
4. **限时**：duration ∈ {10min, 30min, 1day, permanent}，兑换成功那一刻起算 expire_at。
5. **全站访问**：兑换码会话与 vk 登录态并列，凭码可看整个网站（码仅作标签 + 落地页）。

数据持久化：config/redemption_codes.json，仿 otp_config.json 的 load/save 模式。
线程安全：一个模块级 Lock 保护所有读改写（同 proxy_pool 的 _lock 模式），网络 I/O 无（纯本地 JSON）。
"""
import json
import os
import secrets
import threading
import time

from core.config import CONFIG_DIR, REDEMPTION_CODES_FILE
from core.daily_password import BEIJING_TZ

DEFAULT_POOL_SIZE = 10

# 时长档位 → 秒数。permanent 用约 10 年，等同"永久"（一次性码下即首个兑换者终身访问）。
_DURATION_SECONDS = {
    '10min': 600,
    '30min': 1800,
    '1day': 86400,
    'permanent': 10 * 365 * 86400,
}

# 生成码的字母表：剔除易混字符 0/O/1/I/L，降低口头/截图转写错误率。
_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

_lock = threading.Lock()


# ────────────────── 持久化 ──────────────────

def _default_config():
    return {'pool_size': DEFAULT_POOL_SIZE, 'active': [], 'used': []}


def load_codes():
    """读取兑换码池配置。文件缺失/损坏返回空池默认值，永不抛异常。"""
    cfg = _default_config()
    try:
        if os.path.exists(REDEMPTION_CODES_FILE):
            with open(REDEMPTION_CODES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            if isinstance(data, dict):
                cfg['pool_size'] = int(data.get('pool_size') or DEFAULT_POOL_SIZE)
                cfg['active'] = [c for c in (data.get('active') or []) if isinstance(c, dict) and c.get('code')]
                cfg['used'] = [c for c in (data.get('used') or []) if isinstance(c, dict) and c.get('code')]
    except Exception:
        pass
    return cfg


def _save_codes(cfg):
    """写盘。调用方持锁。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(REDEMPTION_CODES_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ────────────────── 内部工具 ──────────────────

def _gen_code(existing=None):
    """生成 XXXX-XXXX-XXXX 格式码（12 位，剔除易混字符）。existing 用于避免重复。"""
    existing = existing or set()
    for _ in range(50):  # 概率上不会重复，给个上限防极端
        code = '-'.join(
            ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
            for _ in range(3)
        )
        if code not in existing:
            return code
    # 兜底：拼时间戳，保证唯一
    return _gen_code(existing | {secrets.token_hex(4).upper()})


def _now_str():
    """当前北京时间字符串，用于 created_at / redeemed_at 展示。"""
    try:
        from datetime import datetime
        return datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


def _duration_to_seconds(dur):
    """时长档位转秒数；未知档位按 10min 兜底（最短，安全）。"""
    return _DURATION_SECONDS.get(dur, _DURATION_SECONDS['10min'])


def _existing_codes(cfg):
    """池中所有已存在码（active + used），用于去重。"""
    s = {c['code'] for c in cfg['active']}
    s.update(c['code'] for c in cfg['used'])
    return s


# ────────────────── 公开 API ──────────────────

def get_pool_status():
    """返回池状态（供前端列表/历史展示）：
    {pool_size, active:[...], can_generate, used:[...]}
    顺带惰性把 used 里已过期的 status 从 active→expired。
    """
    with _lock:
        cfg = load_codes()
        _lazily_expire(cfg)
        return {
            'pool_size': cfg['pool_size'],
            'active': cfg['active'],
            'can_generate': max(0, cfg['pool_size'] - len(cfg['active'])),
            'used': cfg['used'],
        }


def create_codes(label, page, duration, count, created_by='vk'):
    """生成 count 张同款码进 active。超额返回 {'success':False,'error':'overflow',...}。

    成功返回 {'success':True,'codes':[...], 'can_generate': 剩余可生成}。
    """
    label = (label or '').strip() or '体验'
    page = (page or '/').strip() or '/'
    duration = duration if duration in _DURATION_SECONDS else '10min'
    try:
        count = int(count)
    except Exception:
        count = 1
    if count < 1:
        count = 1

    with _lock:
        cfg = load_codes()
        can = cfg['pool_size'] - len(cfg['active'])
        if count > can:
            return {
                'success': False,
                'error': 'overflow',
                'message': f'超出池容量：当前还可生成 {can} 个',
                'can_generate': can,
            }

        existing = _existing_codes(cfg)
        now_str = _now_str()
        new_codes = []
        for _ in range(count):
            code = _gen_code(existing)
            existing.add(code)
            entry = {
                'code': code,
                'label': label,
                'page': page,
                'duration': duration,
                'created_at': now_str,
                'created_by': created_by,
            }
            cfg['active'].append(entry)
            new_codes.append(code)
        _save_codes(cfg)
        return {
            'success': True,
            'codes': new_codes,
            'can_generate': cfg['pool_size'] - len(cfg['active']),
        }


def redeem(code, client_ip=''):
    """核销一张码（一次性）。成功建会话用，返回含 expire_at/page/label/duration。

    - 码不在 active（不存在或已用过/已撤销）→ {'success':False,'error':'invalid'}
      （统一模糊错误，不区分 used/invalid，降低枚举探测信息泄露）
    - 成功：active 移除 → 插 used 顶部(status=active) → 立即补一张同款新码维持池满。
    """
    code = (code or '').strip().upper()

    with _lock:
        cfg = load_codes()

        # 找到该码
        target = None
        for c in cfg['active']:
            if c['code'] == code:
                target = c
                break
        if target is None:
            return {'success': False, 'error': 'invalid', 'message': '兑换码无效或已被使用'}

        # 移出 active
        cfg['active'] = [c for c in cfg['active'] if c['code'] != code]

        # 计算过期时间（兑换时刻起算）
        expire_at = time.time() + _duration_to_seconds(target.get('duration', '10min'))
        now_str = _now_str()

        # 插 used 顶部（历史，按时间倒序，最新在前）
        used_entry = dict(target)
        used_entry.update({
            'redeemed_at': now_str,
            'expire_at': int(expire_at),
            'status': 'active',
            'redeemed_by_ip': client_ip or '',
        })
        cfg['used'].insert(0, used_entry)

        # 立即补一张同款新码，维持池满（保证永远有 pool_size 个可用）
        existing = _existing_codes(cfg)
        new_code = _gen_code(existing)
        cfg['active'].append({
            'code': new_code,
            'label': target.get('label', '体验'),
            'page': target.get('page', '/'),
            'duration': target.get('duration', '10min'),
            'created_at': now_str,
            'created_by': target.get('created_by', 'vk'),
        })

        _save_codes(cfg)
        return {
            'success': True,
            'expire_at': int(expire_at),
            'page': used_entry['page'],
            'label': used_entry['label'],
            'duration': used_entry['duration'],
        }


def is_code_expired(code):
    """该码是否已过期/失效（供守卫与轮询判定会话有效性）。

    - 码不在 used → True（无效码，视为失效）
    - status != 'active'（已过期/已撤销）→ True
    - status == 'active' 但 expire_at 已过 → 惰性置为 expired 并返回 True
    - permanent 的 expire_at 极远，正常永不过期。
    """
    code = (code or '').strip().upper()
    if not code:
        return True
    with _lock:
        cfg = load_codes()
        target = None
        for c in cfg['used']:
            if c['code'] == code:
                target = c
                break
        if target is None:
            return True
        if target.get('status') != 'active':
            return True
        if time.time() > target.get('expire_at', 0):
            target['status'] = 'expired'
            _save_codes(cfg)
            return True
        return False


def _lazily_expire(cfg):
    """把 used 里 status=active 但已过期的，惰性标记为 expired。持锁调用。"""
    changed = False
    now = time.time()
    for c in cfg['used']:
        if c.get('status') == 'active' and now > c.get('expire_at', 0):
            c['status'] = 'expired'
            changed = True
    if changed:
        _save_codes(cfg)


def revoke(code):
    """vk 手动撤销一张码：active 里的直接删除；used 里的 status→revoked（立即踢出在线会话）。"""
    code = (code or '').strip().upper()
    with _lock:
        cfg = load_codes()
        changed = False
        before = len(cfg['active'])
        cfg['active'] = [c for c in cfg['active'] if c['code'] != code]
        if len(cfg['active']) != before:
            changed = True
        for c in cfg['used']:
            if c['code'] == code and c.get('status') == 'active':
                c['status'] = 'revoked'
                changed = True
        if changed:
            _save_codes(cfg)
            return {'success': True, 'message': '已撤销'}
        return {'success': False, 'error': 'not_found', 'message': '未找到该兑换码'}


def delete_code(code):
    """彻底删除一张码（从 active 和 used 中移除）。用于清理历史。"""
    code = (code or '').strip().upper()
    with _lock:
        cfg = load_codes()
        before_a = len(cfg['active'])
        before_u = len(cfg['used'])
        cfg['active'] = [c for c in cfg['active'] if c['code'] != code]
        cfg['used'] = [c for c in cfg['used'] if c['code'] != code]
        if len(cfg['active']) != before_a or len(cfg['used']) != before_u:
            _save_codes(cfg)
            return {'success': True, 'message': '已删除'}
        return {'success': False, 'error': 'not_found', 'message': '未找到该兑换码'}


def find_in_used(code):
    """查 used 里的码（供 auth_routes 取 redeem_label 展示），找不到返回 None。"""
    code = (code or '').strip().upper()
    with _lock:
        cfg = load_codes()
        for c in cfg['used']:
            if c['code'] == code:
                return c
    return None
