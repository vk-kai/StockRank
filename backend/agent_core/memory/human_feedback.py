# -*- coding: utf-8 -*-
"""人工介入闭环: 分身拿不准 → 弹窗请本人拿主意 → 决定写入知识库 → 持续注入记忆

低确定性协议:
- dialog 模式(persona_agent): prompt 要求拿不准时首行输出 [[?]] 标记 + 2-3 个候选回复,
  parse_reply() 负责识别并剥离标记;
- ask 模式(analysis_agent): JSON 输出自带「不确定信息/置信/候选回答」字段, 程序化判定。
前端收到 unsure 事件后弹介入窗(人工直答 / 选候选 / 直接采用), 决定经 /api/interventions
落到 Agent知识库/人工纠正.jsonl; 之后 context_note() 会把相关纠正注入分身 prompt,
让「越纠正越像本人」的持续训练闭环成立。
"""
import os
import re
import json
import time
import threading

from agent_core import config
SURE_MARK = '[[?]]'
_FEEDBACK_P = os.path.join(config.KB, '人工纠正.jsonl')
_MAX_FEEDBACK = 1000   # 纠正记录上限: 超出丢最旧(防止无限增长拖慢注入打分)
_lock = threading.Lock()

_CAND_RE = re.compile(r'^候选\s*\d*\s*[:：]\s*(.+)$')


def parse_reply(text):
    """解析分身回复: 识别 [[?]] 低确定性标记 → {reply, unsure, candidates}"""
    t = str(text or '').strip()
    if SURE_MARK not in t:
        return {'reply': t, 'unsure': False, 'candidates': []}
    body = t.split(SURE_MARK, 1)[1].strip()
    keep, cands = [], []
    for line in body.split('\n'):
        line = line.strip()
        m = _CAND_RE.match(line)
        if m:
            cands.append(m.group(1).strip())
        elif line:
            keep.append(line)
    # 候选之外的行是 AI 草稿正文(dialog 是微信单行风格, 用空格连回一行)
    return {'reply': ' '.join(keep).strip(), 'unsure': True, 'candidates': cands[:3]}


def save_decision(question, ai_draft, contact, mode, choice,
                  human_answer='', candidates=None, candidate_index=None):
    """保存本人决定, 返回最终要发送的回答 (choice: human/candidate/adopt)"""
    candidates = [str(c or '').strip() for c in (candidates or []) if str(c or '').strip()]
    choice = str(choice or '')
    if choice == 'human':
        final = str(human_answer or '').strip()
        if not final:
            raise ValueError('本人回答不能为空')
        label = '人工直答'
    elif choice == 'candidate':
        idx = int(candidate_index if candidate_index is not None else -1)
        if not (0 <= idx < len(candidates)):
            raise ValueError('候选选项无效')
        final = candidates[idx]
        label = '选定候选'
    elif choice == 'adopt':
        final = str(ai_draft or '').strip()
        if not final:
            raise ValueError('AI 草稿为空, 无法采用')
        label = '直接采用'
    else:
        raise ValueError('未知的介入方式')
    rec = {'时间': time.strftime('%Y-%m-%dT%H:%M:%S'), '联系人': contact or '',
           '模式': mode or 'dialog', '问题': (question or '').strip()[:500],
           'AI草稿': (ai_draft or '').strip()[:500], '最终回答': final[:500],
           '决定': label, '候选': candidates[:3]}
    with _lock:
        os.makedirs(config.KB, exist_ok=True)
        items = []
        try:
            with open(_FEEDBACK_P, encoding='utf-8') as f:
                items = [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            pass
        except Exception:
            items = []
        # 去重: 同一联系人+同一问题+同一最终回答 已纠正过 → 不重复入库
        dup_q = ' '.join(rec['问题'].split())
        for ln in items:
            try:
                old = json.loads(ln)
            except Exception:
                continue
            if (old.get('联系人') == rec['联系人']
                    and ' '.join(str(old.get('问题', '')).split()) == dup_q
                    and old.get('最终回答') == rec['最终回答']):
                return final
        items.append(json.dumps(rec, ensure_ascii=False))
        if len(items) > _MAX_FEEDBACK:
            items = items[-_MAX_FEEDBACK:]
        tmp = _FEEDBACK_P + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(items) + '\n')
        os.replace(tmp, _FEEDBACK_P)
    return final


def load_recent(limit=6):
    """最近的纠正记录(新→旧) + 总条数, 供设置页展示"""
    items = []
    try:
        with open(_FEEDBACK_P, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except Exception:
                        continue
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {'count': len(items), 'items': list(reversed(items))[:max(1, int(limit or 6))]}


def context_note(question, contact='', limit=3):
    """把与当前问题相关的历史纠正注入 prompt (联系人命中 + 问题 2-gram 重合度打分)"""
    data = load_recent(limit=200)
    items = data.get('items') or []
    if not items:
        return ''
    # items 是新→旧, 倒回旧→新遍历, 同分时保留更近的(后写覆盖)
    q = str(question or '').strip()
    q_grams = {q[i:i + 2] for i in range(len(q) - 1)} if len(q) > 1 else ({q} if q else set())
    scored = []
    for it in reversed(items):
        s = 0.0
        if contact and it.get('联系人') == contact:
            s += 3.0
        iq = str(it.get('问题') or '')
        if iq and q_grams:
            g = {iq[i:i + 2] for i in range(len(iq) - 1)} if len(iq) > 1 else {iq}
            s += 2.0 * len(g & q_grams) / max(len(g), 1)
        if s >= 2.0:
            scored.append((s, it))
    if not scored:
        return ''
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for _, it in scored[:max(1, limit)]:
        lines.append(f"· 问「{it.get('问题', '')[:120]}」时, 本人事后确认的正确说法是: "
                     f"{it.get('最终回答', '')[:160]}（AI 当时猜的是「{it.get('AI草稿', '')[:80]}」, 已被纠正）")
    return '【本人纠正记忆(你以前答错过、本人亲自更正过的问答, 必须优先遵循, 不得再猜)】\n' + '\n'.join(lines)
