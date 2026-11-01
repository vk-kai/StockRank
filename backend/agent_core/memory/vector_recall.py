# -*- coding: utf-8 -*-
"""向量语义召回(可选增强): BM25 词法检索的语义补充, 解决同义改写/模糊指代召回不到的问题

设计(对照主流混合检索实践: BM25 + 向量 + 融合, 见 Elastic/Qdrant 官方博客):
- 向量化走 config 的 OpenAI 兼容 /embeddings —— 设置里配 embedding_model 即启用, 不配零影响;
- 向量落盘 cache/vector_mem.db(sqlite BLOB, 归一化 float32), 增量补算, 重启不重算;
- 检索: numpy 矩阵点积(归一化后即余弦), 候选交给 retrieval.retrieve() 与词法命中加权融合;
- 覆盖率 ≥80% 才视为就绪, 未就绪/出错/numpy 缺失时一切照旧, 全程可降级。
"""
import os
import time
import sqlite3
import threading

import numpy as np

from agent_core import config
from agent_core.llm_client import embed_texts, LLMError
from agent_core.memory import indexer

DB_PATH = os.path.join(config.CACHE, 'vector_mem.db')
COVERAGE_READY = 0.8   # 就绪门槛: 已向量化比例
BATCH = 64             # 单次向量化条数
_COOLDOWN = 2.0        # 批间休眠(秒), 给网关留余量

_st_lock = threading.Lock()
_st = {'running': False, 'error': ''}
_mat_lock = threading.Lock()
_mat = None   # {'n', 'rows': numpy 矩阵(已归一化), 'items': 对应索引条目列表}


def enabled():
    return bool(config.load_config().get('embedding_model'))


def _set_err(msg):
    with _st_lock:
        _st['error'] = str(msg)[:300]


def _count():
    try:
        conn = sqlite3.connect(DB_PATH)
        n, d = conn.execute('SELECT COUNT(*), COALESCE(MAX(d),0) FROM vec').fetchone()
        conn.close()
        return int(n), int(d)
    except Exception:
        return 0, 0


def ready():
    n_total, _ = _count()
    n_idx = len(indexer.mem_index())
    return enabled() and n_idx > 0 and n_total / n_idx >= COVERAGE_READY


def status():
    with _st_lock:
        st = dict(_st)
    embedded, dim = _count()
    st.update({'enabled': enabled(), 'embedded': embedded, 'total': len(indexer.mem_index()),
               'dim': dim, 'ready': ready()})
    return st


def _matrix():
    """全量向量加载成 numpy 矩阵(行序与 items 对齐); 条数变化时重载"""
    global _mat
    total, dim = _count()
    with _mat_lock:
        if _mat is not None and _mat['n'] == total:
            return _mat
        if not total or not dim:
            return None
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute('SELECT rel, line, v FROM vec ORDER BY rel, line').fetchall()
        conn.close()
        by_key = {(it['rel'], it['line']): it for it in indexer.mem_index()}
        keep, vecs = [], []
        for rel, line, blob in rows:
            it = by_key.get((rel, int(line)))
            if it is None:
                continue   # 数据文件已改名/删除 → 孤儿向量跳过
            keep.append(it)
            vecs.append(np.frombuffer(blob, dtype=np.float32))
        try:
            m = np.vstack(vecs) if vecs else None
        except Exception:
            return None
        if m is not None:
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            m = m / norms   # 入库时已归一化, 再归一一次兜底浮点误差
        _mat = {'n': total, 'rows': m, 'items': keep}
        return _mat


def search(query, top_k=60):
    """语义召回 top_k 条 [{it(索引条目), vec_n(余弦0-1)}]; 未就绪/失败返回 []"""
    if not ready():
        return []
    try:
        qv = embed_texts([str(query or '')[:1000]])[0]
    except LLMError as e:
        _set_err(f'查询向量化失败: {e}')
        return []
    except Exception as e:
        _set_err(f'查询向量化异常: {type(e).__name__}: {e}')
        return []
    q = np.asarray(qv, dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    q = q / n
    m = _matrix()
    if m is None or m['rows'] is None or not len(m['items']):
        return []
    if q.shape[0] != m['rows'].shape[1]:
        _set_err(f'维度不匹配: 查询{q.shape[0]} vs 库{m["rows"].shape[1]}'
                 '(换过 embedding 模型请删除 cache/vector_mem.db 重建)')
        return []
    try:
        sims = m['rows'] @ q
        k = min(top_k * 3, sims.shape[0])
        idx = np.argpartition(-sims, k - 1)[:k]
        out = [{'it': m['items'][int(i)], 'vec_n': float(max(0.0, sims[i]))} for i in idx]
        out.sort(key=lambda x: -x['vec_n'])
        return out[:top_k]
    except Exception as e:
        _set_err(f'向量检索异常: {type(e).__name__}: {e}')
        return []


# ───────── 后台增量建库 ─────────

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS vec(rel TEXT, line INTEGER, d INTEGER, v BLOB, '
                 'PRIMARY KEY(rel, line))')
    conn.commit()
    conn.close()


def _missing(limit):
    """取未向量化的消息(limit 条)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        have = {r for (r,) in conn.execute('SELECT rel || "#" || line FROM vec')}
        conn.close()
    except Exception:
        have = set()
    out = []
    for it in indexer.mem_index():
        if it['rel'] + '#' + str(it['line']) not in have:
            out.append(it)
            if len(out) >= limit:
                break
    return out


def _embed_batch(items):
    texts = [(it['c'] or '（空）')[:1000] for it in items]
    vecs = embed_texts(texts)
    rows = []
    for it, v in zip(items, vecs):
        arr = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(arr))
        if n > 0:
            arr = arr / n
        rows.append((it['rel'], it['line'], int(arr.shape[0]), arr.tobytes()))
    conn = sqlite3.connect(DB_PATH)
    conn.executemany('INSERT OR REPLACE INTO vec VALUES(?,?,?,?)', rows)
    conn.commit()
    conn.close()
    return len(rows)


def builder_loop():
    """后台增量向量化线程(服务启动时拉起): 补算未向量消息, 就绪后低频自检"""
    if not enabled():
        return
    with _st_lock:
        if _st['running']:
            return
        _st['running'] = True
        _st['error'] = ''
    _init_db()
    try:
        idle = 0
        while True:
            todo = _missing(BATCH)
            if not todo:
                idle += 1
                time.sleep(30 if idle < 5 else 300)   # 就绪后低频自检(新消息/新经历)
                continue
            idle = 0
            try:
                _embed_batch(todo)
                time.sleep(_COOLDOWN)
            except Exception as e:
                _set_err(f'{type(e).__name__}: {e}')
                time.sleep(60)   # 出错慢速重试, 不打崩服务
    finally:
        with _st_lock:
            _st['running'] = False
