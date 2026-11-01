# -*- coding: utf-8 -*-
"""指尖时光日程数据: 解析用户手动记录的每日大事(xls, 2023-2026) → 知识库/日常记录.json
为人生时间线/记忆分析提供聊天记录之外的第二数据源(本人主动记录, 置信度高)。"""
import os, re, glob
from agent_core import config
STOP = {'休息', '取快递', '交报告', '无', '上班', '下班', '睡觉', '起床'}  # 低信息量标题(聚合时计数合并)


def _xls_paths():
    return sorted(glob.glob(os.path.join(config.DATA, '指尖时光日程数据*.xls')))


def parse_all():
    """解析全部 xls → [{'日期','标题','优先级','备注'}], 失败返回 []"""
    try:
        import xlrd
    except ImportError:
        return []
    out = []
    for p in _xls_paths():
        try:
            book = xlrd.open_workbook(p)
        except Exception:
            continue
        for sh in book.sheets():
            if sh.nrows < 3:
                continue
            for r in range(2, sh.nrows):
                title = str(sh.cell_value(r, 0)).strip()
                date = str(sh.cell_value(r, 1)).strip()
                if not title or not re.match(r'^\d{4}-\d{2}-\d{2}', date):
                    continue
                prio = str(sh.cell_value(r, 6)).strip() if sh.ncols > 6 else ''
                memo = str(sh.cell_value(r, 12)).strip() if sh.ncols > 12 else ''
                out.append({'日期': date[:10], '标题': title[:60],
                            '优先级': prio if prio and prio != '无' else '', '备注': memo[:80]})
    out.sort(key=lambda x: x['日期'])
    return out


def _load():
    cached = config.jload(os.path.join(config.KB, '日常记录.json'), {})
    paths = _xls_paths()
    if cached.get('记录') and cached.get('源文件数') == len(paths):
        return cached
    recs = parse_all()
    if not recs:
        return cached if cached.get('记录') else {'记录': [], '源文件数': len(paths)}
    cached = {'源文件数': len(paths), '总数': len(recs), '记录': recs}
    try:
        config.atomic_write_json(os.path.join(config.KB, '日常记录.json'), cached)
    except Exception:
        pass
    return cached


def digest(max_lines=220):
    """聚合文本: 按年→月列出日程大事(重复事项计数合并, 低信息量合并为一行)。
    供时间线生成/预测类分析作第二数据源。"""
    recs = _load().get('记录') or []
    if not recs:
        return ''
    by_ym = {}
    for r in recs:
        ym = r['日期'][:7]
        t = r['标题'].strip()
        if not t:
            continue
        if t in STOP:
            by_ym.setdefault(ym, []).append(('__stop__', t))
        else:
            by_ym.setdefault(ym, []).append(('item', t))
    lines = []
    for ym in sorted(by_ym):
        items, stops = [], {}
        for kind, t in by_ym[ym]:
            if kind == 'item':
                if t not in items:
                    items.append(t)
            else:
                stops[t] = stops.get(t, 0) + 1
        seg = [f'{ym[5:]}月: ']
        main = items[:6]
        seg.append('；'.join(main))
        if len(items) > 6:
            seg.append(f'等{len(items)}项')
        if stops:
            seg.append(' (另:' + '、'.join(f'{k}×{v}' for k, v in sorted(stops.items(), key=lambda x: -x[1])[:4]) + ')')
        lines.append(f"[{ym}] " + ''.join(seg))
        if len(lines) >= max_lines:
            lines.append(f'…(共 {len(recs)} 条日程, 已截断)')
            break
    return '\n'.join(lines)


def records_text_for(message, limit=40):
    """按问题中出现的年份/月份过滤日程, 供分析引擎引用。没提时间返回最近 40 条。"""
    recs = _load().get('记录') or []
    if not recs:
        return ''
    years = re.findall(r'20\d{2}', message or '')
    picked = [r for r in recs if any(y in r['日期'] for y in years)] if years else recs[-limit:]
    picked = picked[-limit:]
    return '\n'.join(f"[{r['日期']}] {r['标题']}" + (f" ({r['备注']})" if r.get('备注') else '') for r in picked)
