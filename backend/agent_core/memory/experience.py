# -*- coding: utf-8 -*-
"""分身经历落盘: 网页端与分身的每轮对话自动追加为长期经历记忆

背景(主流对照): Mem0/LangMem 等方案的记忆都随对话自动增长, 此前本地方案的记忆
只来自微信记录批量重建 + 人工纠正, 网页端聊天不落盘就"蒸发"。
本模块把每轮 分身对话 写入 Agent知识库/分身经历.jsonl:
- 长期: indexer.mem_index() 把它并入检索语料(不进每日统计, 不污染风格档案);
- 短期: recent_for() 把最近与该联系人的对话直注 prompt, 立刻生效, 无需重建索引。
"""
import os
import json
import time
import threading

from agent_core import config
_P = os.path.join(config.KB, '分身经历.jsonl')
_MAX = 2000
_lock = threading.Lock()


def log_exchange(contact, message, reply):
    """一轮分身对话落盘(对方消息 + 分身最终回复); 失败静默, 不影响聊天主流程"""
    contact = str(contact or '').strip()[:60]
    message = str(message or '').strip()[:2000]
    reply = str(reply or '').strip()[:2000]
    if not contact or not message or not reply:
        return
    rec = {'时间': time.strftime('%Y-%m-%d %H:%M:%S'), '联系人': contact,
           '对方消息': message, '分身回复': reply}
    try:
        with _lock:
            os.makedirs(config.KB, exist_ok=True)
            lines = []
            try:
                with open(_P, encoding='utf-8') as f:
                    lines = [x.strip() for x in f if x.strip()]
            except FileNotFoundError:
                pass
            except Exception:
                lines = []
            # 连续完全相同的一轮不重复记(前端重试等场景)
            if lines:
                try:
                    last = json.loads(lines[-1])
                    if (last.get('联系人') == contact and last.get('对方消息') == message
                            and last.get('分身回复') == reply):
                        return
                except Exception:
                    pass
            lines.append(json.dumps(rec, ensure_ascii=False))
            if len(lines) > _MAX:
                lines = lines[-_MAX:]
            tmp = _P + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            os.replace(tmp, _P)
    except Exception as e:
        print(f'[经历] 落盘失败: {e}', flush=True)


def recent_for(contact, limit=5):
    """最近与该联系人的分身对话(旧→新), 注入分身 prompt 用"""
    out = []
    try:
        with open(_P, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get('联系人') == contact:
                    out.append(r)
    except Exception:
        return []
    return out[-max(1, int(limit)):]
