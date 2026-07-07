# -*- coding: utf-8 -*-
"""
资金异动检测模块（Anomaly Detector）
====================================

【数据现实（务必先读）】
- 每个时点只记录 TOP5 净流入 + TOP5 净流出 = 10 个板块（稀疏「上榜」数据）。
- net_flow 是「当日累计净流入」（亿元），随时间单调-ish，非平稳。
- 因此 z-score 不能基于「累计值」的长期分布做主力判定。

【判定策略】
主力维度（不依赖长期平稳分布，最稳健）：
  1. 价量背离 divergence   —— 涨跌方向与资金流向相反（拉高出货 / 低位吸筹）
  2. 突变 spike            —— 相邻时点净流入增量 Δnet_flow 急速变化
  3. 连续同向 streak       —— 当天连续 N 个时点 net_flow 同号（趋势形成）

辅助维度（依赖上榜历史，标注样本量）：
  4. 巨量 surge           —— 当前上榜量级 vs 该板块历史上榜分布的 z-score
                              样本不足时降级为绝对阈值。

信息标签（不单独推送，附加在其它维度上）：
  5. 榜首 rank_top        —— rank==1 且量级显著

【调用入口】
- 采集 hook（实时）：detect_and_push(today, minute_key, data)
- 历史/手动试跑：detect_for_snapshot(date_str, minute_key, push=False)
"""
import os
import json
import threading
import math
from datetime import datetime, timedelta

from config import REALTIME_DIR, CONFIG_DIR, DATA_DIR
from data_processor import load_realtime_data, error_logger
from logger import get_logger

logger = get_logger('anomaly')

# --------------------------------------------------------------------------
# 路径与默认配置
# --------------------------------------------------------------------------
ANOMALY_CONFIG_FILE = os.path.join(CONFIG_DIR, 'flow_anomaly_config.json')
BASELINE_FILE = os.path.join(DATA_DIR, 'anomaly_baseline.json')
ALERTS_FILE = os.path.join(REALTIME_DIR, 'anomaly_alerts.json')

DEFAULT_CONFIG = {
    'enabled': True,                 # 总开关（实时 hook 用）
    # 巨量 surge（z-score）
    'z_threshold': 2.0,              # z 超过此值视为罕见
    'min_samples': 8,                # 基线最小样本数，不足则降级
    'abs_threshold': 50.0,           # 样本不足时的绝对阈值（亿元）
    # 价量背离 divergence
    'divergence_change': 0.002,      # 5分钟价格变化门槛（小数，0.002=0.2%）
    'min_net_for_divergence': 2.0,   # 背离判定的5分钟最小反向 |Δnet_flow|（亿）
    # 突变 spike
    'spike_threshold': 20.0,         # 相邻时点 |Δnet_flow| 门槛（亿）
    # 连续 streak
    'streak_min': 4,                 # 连续同号最少时点数（4=约20分钟）
    'min_net_for_streak': 3.0,       # 参与连续判定的单点最小 |net_flow|（亿）
    # 通用
    'cooldown_minutes': 30,          # 同板块+同类型去重冷却
    'baseline_days': 20,             # 基线扫描天数
    'rank_top_net': 30.0,            # 「榜首」标签的 |net_flow| 门槛（亿）
}

_config_cache = None
_config_lock = threading.Lock()
_baseline_cache = None
_baseline_lock = threading.Lock()


# --------------------------------------------------------------------------
# 配置读写
# --------------------------------------------------------------------------
def load_config():
    """加载异动配置（带缓存）。"""
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache
        cfg = dict(DEFAULT_CONFIG)
        if os.path.exists(ANOMALY_CONFIG_FILE):
            try:
                with open(ANOMALY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg.update(json.load(f))
            except Exception as e:
                logger.warning(f"读取异动配置失败，使用默认值: {e}")
        _config_cache = cfg
        return cfg


def save_config(new_cfg):
    """持久化配置并刷新缓存。"""
    global _config_cache
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({k: v for k, v in new_cfg.items() if k in DEFAULT_CONFIG})
    with _config_lock:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(ANOMALY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _config_cache = cfg
    logger.info("异动配置已更新")
    return cfg


# --------------------------------------------------------------------------
# 基线（z-score 用）：扫描历史上榜 net_flow 分布
# --------------------------------------------------------------------------
def _is_date_file(name):
    import re
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}\.json$', name))


def build_baseline(days=None):
    """扫描最近 N 天 realtime，统计每个板块「上榜时 net_flow」的均值/标准差。

    注意：这是「上榜分布」而非「平时分布」，仅用于判断「这次上榜是否罕见」。
    """
    cfg = load_config()
    days = days or cfg.get('baseline_days', 20)
    stats = {}  # {sector: [abs_net_flow,...]}

    today = datetime.now().strftime('%Y-%m-%d')
    for i in range(1, days + 1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        rt = load_realtime_data(d)
        if not rt or rt.get('_invalid'):
            continue
        for minute_key, payload in rt.items():
            if not isinstance(payload, dict):
                continue
            for sec in payload.get('data', []):
                name = sec.get('name')
                nf = sec.get('net_flow')
                if name is None or nf is None:
                    continue
                try:
                    nf = float(nf)
                except (TypeError, ValueError):
                    continue
                stats.setdefault(name, []).append(abs(nf))

    baseline = {'built_at': datetime.now().isoformat(), 'baseline_days': days, 'sectors': {}}
    for name, vals in stats.items():
        n = len(vals)
        if n == 0:
            continue
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n if n > 1 else 0.0
        std = math.sqrt(var)
        baseline['sectors'][name] = {
            'count': n,
            'mean': round(mean, 2),
            'std': round(std, 2),
            'max': round(max(vals), 2),
        }

    with _baseline_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        global _baseline_cache
        _baseline_cache = baseline
    logger.info(f"基线构建完成：{len(baseline['sectors'])} 个板块")
    return baseline


def get_baseline(force_rebuild=False):
    """获取基线（懒加载：缺失或非今日构建则重建）。"""
    global _baseline_cache
    with _baseline_lock:
        if force_rebuild:
            return build_baseline()
        if _baseline_cache is not None:
            return _baseline_cache
        if os.path.exists(BASELINE_FILE):
            try:
                with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
                    _baseline_cache = json.load(f)
            except Exception:
                _baseline_cache = None
        # 基线跨天复用：板块资金分布不会一天突变，3 天内不重建（避免每天首次接口卡顿）
        built_at = (_baseline_cache or {}).get('built_at', '')
        need_rebuild = True
        if built_at:
            try:
                built_date = datetime.fromisoformat(built_at)
                if (datetime.now() - built_date).days < 3:
                    need_rebuild = False
            except Exception:
                pass
        if need_rebuild:
            _baseline_cache = build_baseline()
        return _baseline_cache


# --------------------------------------------------------------------------
# 工具：从当天 realtime 取某板块的有序 (time, net_flow) 序列
# --------------------------------------------------------------------------
def _sector_series(realtime_data, sector_name, up_to_key=None):
    """返回 [{time, net_flow, change}, ...] 按时间升序，可截止到 up_to_key（不含）。"""
    series = []
    if not realtime_data or realtime_data.get('_invalid'):
        return series
    keys = sorted([k for k in realtime_data.keys() if isinstance(k, str) and ':' in k])
    for k in keys:
        if up_to_key is not None and k >= up_to_key:
            break
        payload = realtime_data.get(k)
        if not isinstance(payload, dict):
            continue
        for sec in payload.get('data', []):
            if sec.get('name') == sector_name:
                try:
                    series.append({
                        'time': k,
                        'net_flow': float(sec.get('net_flow', 0) or 0),
                        'change': float(sec.get('change', 0) or 0),
                    })
                except (TypeError, ValueError):
                    pass
                break
    return series


def _load_realtime(date_str):
    rt = load_realtime_data(date_str)
    if rt.get('_invalid'):
        return {}
    return rt


# --------------------------------------------------------------------------
# 维度 1：价量背离
# --------------------------------------------------------------------------
def _check_divergence(sec, series, cfg):
    """价量背离：基于「5分钟增量」Δ价格 vs Δ净流入。

    用累计值（change、net_flow 都是当日累计）会让"全天吸筹但盘中回调"的板块
    每个时点都触发，造成刷屏。改为增量判：这5分钟价格上涨但资金流出=拉高出货；
    价格下跌但资金流入=低位吸筹。只在真正的短期价量反向时触发。
    """
    if not series:
        return None
    change = float(sec.get('change', 0) or 0)
    nf = float(sec.get('net_flow', 0) or 0)
    prev = series[-1]
    d_change = change - prev['change']       # 这5分钟价格变化（小数）
    d_nf = nf - prev['net_flow']              # 这5分钟资金增量
    if abs(d_change) < cfg['divergence_change'] or abs(d_nf) < cfg['min_net_for_divergence']:
        return None
    d_change_pct = round(d_change * 100, 2)
    if d_change > 0 and d_nf < 0:
        return {'type': 'divergence', 'sub': 'top_distribution',
                'label': '拉高出货', 'd_change_pct': d_change_pct, 'd_net_flow': round(d_nf, 2),
                'change_pct': round(change * 100, 2), 'net_flow': round(nf, 2)}
    if d_change < 0 and d_nf > 0:
        return {'type': 'divergence', 'sub': 'bottom_accumulation',
                'label': '回调吸筹', 'd_change_pct': d_change_pct, 'd_net_flow': round(d_nf, 2),
                'change_pct': round(change * 100, 2), 'net_flow': round(nf, 2)}
    return None


# --------------------------------------------------------------------------
# 维度 2：突变（相邻时点 Δnet_flow）
# --------------------------------------------------------------------------
def _check_spike(sec, series, cfg):
    if len(series) < 1:
        return None
    nf = float(sec.get('net_flow', 0) or 0)
    prev = series[-1]
    prev_time, prev_nf = prev['time'], prev['net_flow']
    delta = nf - prev_nf
    if abs(delta) < cfg['spike_threshold']:
        return None
    return {'type': 'spike', 'sub': 'spike_in' if delta > 0 else 'spike_out',
            'label': '加速流入' if delta > 0 else '加速流出',
            'delta': round(delta, 2), 'net_flow': round(nf, 2),
            'prev_time': prev_time, 'prev_net_flow': round(prev_nf, 2)}


# --------------------------------------------------------------------------
# 维度 3：连续同向（基于「增量 Δnet_flow」，非累计值）
# --------------------------------------------------------------------------
def _check_streak(sec, series, cfg):
    """连续同向：基于相邻时点的「增量 Δnet_flow」（每5分钟的实际资金行为）。

    注意：net_flow 是当日累计值，直接对累计值判同号会让"全天持续流入的板块"
    从早到晚每个时点都累计 streak（出现 30/40 这种离谱数字）——那是 bug。
    正确做法是对「增量」判连续同号：反映"短期资金持续进场/离场"。
    """
    nf = float(sec.get('net_flow', 0) or 0)
    if not series:
        return None  # 无历史，无法算增量
    # series = [(time, 累计nf), ...]（不含当前时点），末尾追加当前累计 → 构造增量序列
    nf_seq = [s['net_flow'] for s in series] + [nf]
    deltas = [nf_seq[i] - nf_seq[i - 1] for i in range(1, len(nf_seq))]
    if not deltas:
        return None
    cur_delta = deltas[-1]
    sign = 1 if cur_delta > 0 else -1
    streak = 0
    cum_delta = 0.0
    for d in reversed(deltas):
        d_sign = 1 if d > 0 else -1
        if d_sign == sign and abs(d) >= cfg['min_net_for_streak']:
            streak += 1
            cum_delta += d
        else:
            break
    if streak < cfg['streak_min']:
        return None
    minutes = streak * 5
    return {'type': 'streak', 'sub': 'streak_in' if sign > 0 else 'streak_out',
            'label': f'持续流入{streak}段(≈{minutes}分钟)' if sign > 0 else f'持续流出{streak}段(≈{minutes}分钟)',
            'streak': streak, 'minutes': minutes, 'cum_delta': round(cum_delta, 2),
            'net_flow': round(nf, 2)}


# --------------------------------------------------------------------------
# 维度 4：巨量 z-score（辅助，标注样本量）
# --------------------------------------------------------------------------
def _check_surge(sec, baseline, cfg):
    nf = float(sec.get('net_flow', 0) or 0)
    abs_nf = abs(nf)
    sec_stats = (baseline or {}).get('sectors', {}).get(sec.get('name'), {}) if baseline else {}
    count = sec_stats.get('count', 0)
    mean = sec_stats.get('mean', 0)
    std = sec_stats.get('std', 0) or 1e-9

    # 样本充足：用 z-score
    if count >= cfg['min_samples'] and std > 0:
        z = (abs_nf - mean) / std
        if z >= cfg['z_threshold']:
            return {'type': 'surge', 'sub': 'surge_in' if nf > 0 else 'surge_out',
                    'label': '巨量流入' if nf > 0 else '巨量流出',
                    'z': round(z, 2), 'net_flow': round(nf, 2),
                    'count': count, 'mean': mean, 'sample_sufficient': True}
        return None
    # 样本不足：降级绝对阈值，并标注
    if abs_nf >= cfg['abs_threshold']:
        return {'type': 'surge', 'sub': 'surge_in' if nf > 0 else 'surge_out',
                'label': '巨量流入' if nf > 0 else '巨量流出',
                'z': None, 'net_flow': round(nf, 2),
                'count': count, 'sample_sufficient': False}
    return None


# --------------------------------------------------------------------------
# 主检测：对一个时点的所有板块跑全维度
# --------------------------------------------------------------------------
def detect_for_snapshot(date_str, minute_key, push=False, realtime_data=None):
    """对指定 (日期, 时点) 跑异动检测，返回命中异动列表。

    push=True 时对「一档推送维度」走去重 + 推送（实时 hook 用）。
    """
    cfg = load_config()
    if realtime_data is None:
        realtime_data = _load_realtime(date_str)
    if not realtime_data:
        return []

    payload = realtime_data.get(minute_key)
    if not isinstance(payload, dict):
        return []
    current_sectors = payload.get('data', [])
    if not current_sectors:
        return []

    baseline = get_baseline()

    findings = []
    for sec in current_sectors:
        name = sec.get('name')
        if not name:
            continue
        series = _sector_series(realtime_data, name, up_to_key=minute_key)
        hits = []
        for checker in (_check_divergence, _check_spike, _check_streak):
            try:
                r = checker(sec, series, cfg)
            except Exception as e:
                logger.warning(f"维度检测异常 {name}: {e}")
                r = None
            if r:
                hits.append(r)
        # 巨量（辅助）
        try:
            r = _check_surge(sec, baseline, cfg)
            if r:
                hits.append(r)
        except Exception as e:
            logger.warning(f"巨量检测异常 {name}: {e}")
        # 榜首标签（附加，不单独成条）
        rank_top = None
        try:
            if sec.get('rank') == 1 and abs(float(sec.get('net_flow', 0) or 0)) >= cfg['rank_top_net']:
                rank_top = True
        except Exception:
            pass

        if hits:
            lead = sec.get('lead_stock') or {}
            findings.append({
                'sector': name,
                'rank': sec.get('rank'),
                'flow_group': sec.get('flow_group'),
                'net_flow': round(float(sec.get('net_flow', 0) or 0), 2),
                'change_pct': round(float(sec.get('change', 0) or 0) * 100, 2),
                'lead_stock': lead.get('name', ''),
                'lead_change': round(float(lead.get('change', 0) or 0) * 100, 2) if lead.get('change') is not None else None,
                'is_rank_top': rank_top,
                'time': minute_key,
                'date': date_str,
                'hits': hits,
            })

    if push and findings:
        _push_findings(findings, cfg)
    return findings


# --------------------------------------------------------------------------
# 去重 + 推送
# --------------------------------------------------------------------------
def _load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_alerts(alerts):
    os.makedirs(REALTIME_DIR, exist_ok=True)
    with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def _is_in_cooldown(alerts, sector, sub, cfg, now_ts):
    cooldown = cfg['cooldown_minutes'] * 60
    for a in reversed(alerts):
        if a.get('sector') == sector and sub in a.get('subs', []):
            try:
                t = datetime.fromisoformat(a['timestamp']).timestamp()
                if now_ts - t < cooldown:
                    return True
            except Exception:
                continue
    return False


def _push_findings(findings, cfg):
    """合并同板块异动 → 去重 → 推送 → 入库。"""
    try:
        from notification_pusher import send_news_message
    except Exception as e:
        logger.error(f"无法导入推送模块: {e}")
        return

    alerts = _load_alerts()
    now = datetime.now()
    now_ts = now.timestamp()
    new_records = []

    for f in findings:
        subs = [h['sub'] for h in f['hits']]
        # 同板块+任一类型在冷却期内 → 跳过推送（仍记录为 muted）
        if _is_in_cooldown(alerts, f['sector'], subs[0], cfg, now_ts):
            continue
        title, content = _format_message(f)
        pushed = False
        try:
            pushed = bool(send_news_message(title, content))
        except Exception as e:
            logger.error(f"异动推送失败 {f['sector']}: {e}")
        record = {
            'sector': f['sector'],
            'subs': subs,
            'labels': [h['label'] for h in f['hits']],
            'net_flow': f['net_flow'],
            'change_pct': f['change_pct'],
            'lead_stock': f['lead_stock'],
            'time': f['time'],
            'date': f['date'],
            'pushed': pushed,
            'timestamp': now.isoformat(),
        }
        alerts.append(record)
        new_records.append(record)

    if new_records:
        # 仅保留最近 500 条，防膨胀
        _save_alerts(alerts[-500:])
        logger.info(f"异动推送 {len(new_records)} 条")


def _format_message(f):
    """生成飞书/企微 markdown 消息。"""
    sector = f['sector']
    nf = f['net_flow']
    chg = f['change_pct']
    arrow = '🔴' if nf >= 0 else '🟢'  # 红涨绿跌（A股习惯：红=流入/涨）
    lines = [f"{arrow} **资金异动 · {sector}**"]
    meta = []
    meta.append(f"净流入 {nf:+.2f}亿")
    meta.append(f"涨跌 {chg:+.2f}%")
    if f.get('lead_stock'):
        lc = f.get('lead_change')
        lc_str = f" {lc:+.2f}%" if lc is not None else ""
        meta.append(f"龙头 {f['lead_stock']}{lc_str}")
    lines.append(" / ".join(meta))
    lines.append("")
    for h in f['hits']:
        detail = ""
        if h['type'] == 'surge':
            if h.get('sample_sufficient'):
                detail = f"（z={h['z']}，历史上榜 {h['count']} 次均值的 { (abs(nf)/h['mean']):.1f} 倍）"
            else:
                detail = f"（历史上榜样本 {h.get('count',0)} 次不足，按绝对量级判定）"
        elif h['type'] == 'spike':
            detail = f"（相比 {h['prev_time']} 变化 {h['delta']:+.2f}亿）"
        elif h['type'] == 'streak':
            detail = f"（连续 {h['streak']} 个时点≈{h['minutes']}分钟，累计 {h['cum_net_flow']:+.2f}亿）"
        elif h['type'] == 'divergence':
            detail = f"（价量方向背离）"
        lines.append(f"• {h['label']}{detail}")
    lines.append("")
    lines.append(f"⏰ {f['date']} {f['time']}")
    title = f"资金异动 · {sector}"
    return title, "\n".join(lines)


# --------------------------------------------------------------------------
# 实时采集 hook 入口
# --------------------------------------------------------------------------
def detect_and_push(today, minute_key, data):
    """采集落盘成功后调用：加载当天 realtime（含本次）→ 检测 → 推送。

    绝不抛异常影响采集主循环。
    """
    try:
        cfg = load_config()
        if not cfg.get('enabled', True):
            return
        # data 已落盘，重新 load 保证拿到含本次的完整 dict
        detect_for_snapshot(today, minute_key, push=True)
    except Exception as e:
        error_logger.error(f"异动检测异常（不影响采集）: {e}")


# --------------------------------------------------------------------------
# 查询接口用
# --------------------------------------------------------------------------
def list_alerts(date_str=None, limit=200):
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    alerts = sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)
    return alerts[:limit]


def detect_full_day(date_str, push=False):
    """对某天所有时点跑检测（复盘/试跑用）。返回所有命中，按时间序。"""
    rt = _load_realtime(date_str)
    if not rt:
        return []
    keys = sorted([k for k in rt.keys() if isinstance(k, str) and ':' in k])
    all_findings = []
    for k in keys:
        try:
            fs = detect_for_snapshot(date_str, k, push=push, realtime_data=rt)
            all_findings.extend(fs)
        except Exception as e:
            logger.warning(f"全天检测异常 {k}: {e}")
    return all_findings
