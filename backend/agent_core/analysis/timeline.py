# -*- coding: utf-8 -*-
"""人生时间线: 按年系统取样万凯真实发言 → AI 提取事件(必须带依据ID) → 后端回查校验
校验失败的事件直接剔除, 事件月份自动校正为证据消息的月份。"""
import os, re, difflib
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json, LLMError
from agent_core.memory import indexer
from agent_core import cache_store
PROMPT_VER = 'v2'
_norm_re = re.compile(r'[\s，。！？,.!?~…、“”‘’"\'（）()【】\[\]]')


def _norm(s):
    return _norm_re.sub('', s or '')


def generate_timeline():
    idx = indexer.mem_index()
    by_year = {}
    for it in idx:
        if it['s'] != '我' or it['ty'] != 'text':
            continue
        c = it['c'].strip()
        if len(c) < 4 or c.startswith(('[', '【')):
            continue
        by_year.setdefault(it['t'][:4], []).append(it)
    if not by_year:
        raise LLMError('无可用消息样本')

    parts, pool = [], {}   # pool: 依据ID -> item
    for y, lst in sorted(by_year.items()):
        lst2 = [x for x in lst if len(x['c']) >= 6] or lst
        n = min(30, len(lst2))
        step = max(1, len(lst2) // n)
        picks = sorted(lst2[::step][:n], key=lambda x: x['t'])   # 系统取样, 结果可复现
        rows = []
        for k, x in enumerate(picks):
            eid = f'{y}_{k:02d}'
            pool[eid] = x
            rows.append(f'[{eid}|{x["t"][:16]}] {x["c"][:80]}')
        parts.append(f'【{y} 年我说的消息样本({len(lst)}条中取{len(picks)}, 引用请带ID)】\n' + '\n'.join(rows))

    ov = config.jload(os.path.join(config.KB, '总览统计.json'), {})
    trend = ov.get('月度总趋势', {})
    by_month = {}
    for mth, n in trend.items():
        by_month.setdefault(mth[:4], {})[mth] = n
    trend_text = '\n'.join(f"{y}: " + ', '.join(f"{m[5:]}月{n}" for m, n in sorted(d.items()))
                           for y, d in sorted(by_month.items()))

    sys = """你是人物传记分析师。根据一个人历年微信发言样本和月度活跃数据, 梳理他的人生时间线。
只输出 JSON(不要 markdown 代码块):
{"总述":"100字内概括这几年的人生轨迹",
 "年份":[{"年":"2022","主题":"这年的关键词","事件":[{"月份":"03","标题":"8字内","描述":"30-60字, 具体不空话","依据ID":"样本里的消息ID","依据":"该ID对应原话的摘录(≤30字)","置信":"高或中"}]}]}
硬性规则:
1. 每个事件必须有「依据ID」(取自样本行首 [ID|时间] 里的 ID) 和「依据」(该条原话的摘录); 找不到依据的猜测事件不要写
2. 覆盖尽量多年份(有样本的年份都要有), 每年 2-5 个事件
3. 绝不编造样本之外的具体事实(人名/公司名/具体数字); 不确定的置信写"中"
4. 事件类型: 工作/学习/生活/兴趣/情绪状态/关系变化, 多样一些
5. 全部中文"""
    user = '\n\n'.join(parts) + f"\n\n【历年月度消息量(反映活跃度)】\n{trend_text}"
    out = extract_json(llm_chat([{'role': 'system', 'content': sys},
                                 {'role': 'user', 'content': user}], temperature=0.4, timeout=300))

    # ── 证据回查校验: 依据必须能在对应样本原文中找到 ──
    kept_total = dropped = 0
    for yev in out.get('年份', []):
        good = []
        for ev in yev.get('事件', []):
            src = pool.get(str(ev.get('依据ID', '')).strip())
            ok = False
            if src is not None:
                q, o = _norm(ev.get('依据', '')), _norm(src['c'])
                if q and o:
                    if q in o or o in q:
                        ok = True
                    elif len(q) >= 6 and difflib.SequenceMatcher(None, q, o).ratio() >= 0.5:
                        ok = True
                if ok:
                    mm = src['t'][5:7].lstrip('0') or '1'
                    if str(ev.get('月份', '')).lstrip('0') != mm:
                        ev['月份'] = mm   # 事件月份校正为证据消息的真实月份
            if ok:
                good.append(ev)
            else:
                dropped += 1
        kept_total += len(good)
        yev['事件'] = good
    out['年份'] = [y for y in out.get('年份', []) if y.get('事件')]
    out['校验'] = {'通过事件': kept_total, '剔除事件': dropped}

    # 校验通过的事件另存为事件记忆(供第三人称分析引擎引用)
    events = []
    for yev in out.get('年份', []):
        for ev in yev['事件']:
            events.append({'年': yev.get('年', ''), '月': ev.get('月份', ''),
                           '标题': ev.get('标题', ''), '描述': ev.get('描述', ''),
                           '依据': ev.get('依据', ''), '置信': ev.get('置信', '')})
    config.atomic_write_json(os.path.join(config.CACHE, 'events.json'), events)

    cache_store.save(os.path.join(config.CACHE, 'timeline.json'), out,
                     cache_store.fingerprint(PROMPT_VER, str(len(idx))))
    return out
