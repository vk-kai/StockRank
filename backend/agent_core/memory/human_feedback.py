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


def _worth_saving(question, ai_draft, contact, mode, choice, final):
    """记忆质检: 判断本次人工介入的「最终回答」是否值得存入纠正记忆。
    纠正记忆的唯一用途是让分身学会"万凯本人的说法/偏好/事实" —— 纯咨询、一次性分析
    结论这类内容存进去只是噪音。任何异常都返回 True(默认保存, 保持旧行为)。"""
    try:
        from agent_core.llm_client import llm_chat, extract_json
        msgs = [{'role': 'system', 'content':
            """你是记忆质检员。个人数字分身系统里 AI 拿不准时由本人(万凯)介入给出了「最终回答」。请判断这条内容是否值得存入「人工纠正记忆」—— 该记忆的唯一用途: 以后分身模仿万凯说话、回答关于万凯的问题时, 把这些记录当作「万凯本人的说法/偏好/事实」优先遵循。
只输出 JSON(不要 markdown 代码块): {"存入": true/false, "理由": "一句话"}
判定标准:
- 存入: 最终回答体现了万凯本人的口吻/表达方式(分身可直接学着说); 本人对事实的更正(如"我其实已经离职了"); 本人对某类事务的处置偏好(如"这种忙我从来帮")
- 不存: 回答是对问题的复述/补充说明; 一次性的分析结论或建议(即便被本人选中, 那也只是"采纳了建议", 不代表本人的事实或立场); 纯寒暄; 与本人无关的客观信息
拿不准时倾向不存(宁缺毋滥, 记忆质量优先)。全部中文。"""},
            {'role': 'user', 'content':
                f"【场景】{'模拟聊天(分身扮演万凯回复消息)' if mode == 'dialog' else '第三人称问答(知己/分析师回答关于万凯的问题)'} · 介入方式: {choice}\n"
                f"【问题】{str(question or '')[:300]}\n【AI 当时草稿】{str(ai_draft or '')[:200]}\n【本人最终回答】{str(final or '')[:400]}"}]
        out = extract_json(llm_chat(msgs, temperature=0.2))
        if isinstance(out, list):
            out = out[0] if out else {}
        return bool(out.get('存入', True)), str(out.get('理由', '') or '')[:80]
    except Exception:
        return True, ''


def save_decision(question, ai_draft, contact, mode, choice,
                  human_answer='', candidates=None, candidate_index=None):
    """保存本人决定, 返回 (最终要发送的回答, 是否已存入纠正记忆)
    (choice: human/candidate/adopt)"""
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
    # 记忆质检: 不值得作为分身训练记忆的直接丢弃(回答照常返回给用户)
    keep, reason = _worth_saving(question, ai_draft, contact, mode, choice, final)
    rec['质检'] = keep
    if not keep:
        return final, False
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
                return final, True
        items.append(json.dumps(rec, ensure_ascii=False))
        if len(items) > _MAX_FEEDBACK:
            items = items[-_MAX_FEEDBACK:]
        tmp = _FEEDBACK_P + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(items) + '\n')
        os.replace(tmp, _FEEDBACK_P)
    return final, True


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


def delete_record(ts):
    """按时间戳删除一条纠正记录(设置页手动清理噪音), 返回是否删除成功"""
    with _lock:
        try:
            with open(_FEEDBACK_P, encoding='utf-8') as f:
                items = [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            return False
        except Exception:
            return False
        kept = []
        removed = False
        for ln in items:
            try:
                if json.loads(ln).get('时间') == ts and not removed:
                    removed = True
                    continue
            except Exception:
                pass
            kept.append(ln)
        if not removed:
            return False
        tmp = _FEEDBACK_P + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(kept) + ('\n' if kept else ''))
        os.replace(tmp, _FEEDBACK_P)
    return True


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
