# -*- coding: utf-8 -*-
"""经济周期通知(第四步):阶段切换推送 + 月度一页纸报告。

复用现有基础设施,不造新轮子:
- 推送: pushers/notification_pusher.send_news_message(飞书/企微)
- 前端实时: ws.push_event('econ_phase', record)
- 存储: data/realtime/econ_alerts.json (与 anomaly_alerts.json 同模式,200 条上限)
- 调度: econ_cycle_loop 守护线程,app.py 启动时挂载;经济数据月度发布,
  每 6 小时检查一次足够,月报每月只推一次。

推送文案遵循通知偏好:标题带关键结论(哪个区域、从什么阶段→什么阶段),
内容带温度计分数与依据,可立即行动。
"""
import json
import logging
import os
import threading
import time
from datetime import datetime

from . import db, engine
from .signals import overview

logger = logging.getLogger('econ_cycle')

ALERTS_FILE = os.path.join('data', 'realtime', 'econ_alerts.json')
_alerts_lock = threading.Lock()

CHECK_INTERVAL_SECONDS = 6 * 3600  # 每 6 小时检查一次(月度数据,无需更频繁)


def _load_alerts():
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_alerts(alerts):
    os.makedirs(os.path.dirname(ALERTS_FILE), exist_ok=True)
    tmp = ALERTS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(alerts, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ALERTS_FILE)


def _append_alert(record):
    with _alerts_lock:
        alerts = _load_alerts()
        alerts.append(record)
        _save_alerts(alerts[-200:])


# ---------------- 月度一页纸报告 ----------------

_LIGHT_CN = {'green': '绿灯', 'yellow': '黄灯', 'red': '红灯'}
_PHASE_CN = engine.PHASE_NAMES
_STATE_CN = {'rising': '↑', 'falling': '↓', 'flat': '→'}


def _fmt_region(name, item):
    if not item:
        return '%s：数据不足' % name
    inds = item.get('indicators') or []
    ind_lines = '\n'.join('  · %s %.1f %s' % (
        i.get('name', i.get('code', '?')), i.get('value') or 0,
        _STATE_CN.get(i.get('state'), '')) for i in inds[:5])
    return ('%s：【%s】温度计 %s 分\n%s' % (
        name, item.get('phase_cn', '?'), item.get('score', '?'), ind_lines))


def monthly_report(as_of=None):
    """月度一页纸:全国/西安阶段 + 两盏灯 + 核心依据。纯文本,直接可推送。"""
    o = overview(as_of=as_of)
    job, startup = o.get('job_switch') or {}, o.get('startup') or {}
    lines = [
        '【经济周期月报 · %s】' % (o.get('month') or datetime.now().strftime('%Y-%m')),
        '',
        _fmt_region('🇨🇳 全国', o.get('national')),
        '',
        _fmt_region('🏛 西安', o.get('xian')),
        '',
        '💼 换工作窗口：%s（%s 分）' % (_LIGHT_CN.get(job.get('light'), '?'), job.get('score', 0)),
    ]
    lines += ['  · %s' % r for r in (job.get('reasons') or [])[:3]]
    lines += [
        '🚀 创业窗口：%s（%s 分）' % (_LIGHT_CN.get(startup.get('light'), '?'), startup.get('score', 0)),
    ]
    lines += ['  · %s' % r for r in (startup.get('reasons') or [])[:3]]
    lines += ['', '注：单月值由累计差分近似,信号为概率参考而非确定结论。']
    return '\n'.join(lines)


# ---------------- 阶段切换检测 ----------------

def phase_switch_check(push=True):
    """判定当月阶段并与上一落库月对比;跨月阶段变化时推送。

    push=False 用于首次启动建立基线(只落库,不推送)。
    返回切换记录列表(无切换返回 [])。
    """
    switches = []
    for scope, name in (('national', '全国'), ('xian', '西安')):
        try:
            prev_rows = db.get_phases(scope)
            prev = prev_rows[-1] if prev_rows else None
            r = engine.judge(scope, persist=True)
            if not r:
                continue
            # 同月重跑不推送;跨月且阶段变化才算切换
            if (push and prev and prev['month'] != r['month']
                    and prev['phase'] != r['phase']):
                direction = '↑ 转暖' if engine.PHASES.index(r['phase']) > engine.PHASES.index(prev['phase']) else '↓ 转冷'
                record = dict(
                    kind='econ_phase', scope=scope, region=name,
                    date=datetime.now().strftime('%Y-%m-%d %H:%M'),
                    month=r['month'],
                    from_phase=prev['phase'], from_phase_cn=_PHASE_CN[prev['phase']],
                    to_phase=r['phase'], to_phase_cn=r['phase_cn'],
                    score=r['score'], direction=direction,
                    reason=r.get('reason', ''),
                )
                title = '🧭 经济周期切换:%s%s %s→%s(%.0f分)' % (
                    name, direction, _PHASE_CN[prev['phase']], r['phase_cn'], r['score'])
                content = '数据期间:%s\n依据:%s\n\n详情:https://0vk.top/econ-cycle' % (
                    r['month'], r.get('reason', '见页面'))
                pushed = False
                if push:
                    try:
                        from pushers.notification_pusher import send_news_message
                        pushed = bool(send_news_message(title, content))
                    except Exception as e:
                        logger.error('[econ] 阶段切换推送失败: %s', e)
                record['pushed'] = pushed
                _append_alert(record)
                try:
                    from ws import push_event
                    push_event('econ_phase', record)
                except Exception:
                    pass
                switches.append(record)
                logger.info('[econ] %s 阶段切换: %s→%s (%s)', name,
                            prev['phase'], r['phase'], r['month'])
        except Exception as e:
            logger.error('[econ] %s 阶段检查失败: %s', scope, e)
    return switches


def _maybe_monthly_report():
    """每月只在数据月份变化后推一次月报(以 JSON 里最后一条月报为准)。"""
    with _alerts_lock:
        alerts = _load_alerts()
    last = next((a for a in reversed(alerts) if a.get('kind') == 'econ_monthly'), None)
    o = overview()
    month = (o.get('national') or {}).get('month')
    if not month or (last and last.get('month') == month):
        return False
    report = monthly_report()
    pushed = False
    try:
        from pushers.notification_pusher import send_news_message
        pushed = bool(send_news_message('🧭 经济周期月报(%s)' % month, report))
    except Exception as e:
        logger.error('[econ] 月报推送失败: %s', e)
    _append_alert(dict(kind='econ_monthly', month=month,
                       date=datetime.now().strftime('%Y-%m-%d %H:%M'),
                       pushed=pushed))
    return True


def econ_cycle_loop():
    """后台守护线程:启动建基线 → 每 6 小时检查阶段切换 + 月报。"""
    logger.info('[econ] 经济周期检查线程启动')
    # 启动时先静默跑一次,建立当月基线(不推送,避免重启误报)
    try:
        phase_switch_check(push=False)
    except Exception as e:
        logger.error('[econ] 基线建立失败: %s', e)
    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        try:
            phase_switch_check(push=True)
            _maybe_monthly_report()
        except Exception as e:
            logger.error('[econ] 周期检查异常: %s', e)
