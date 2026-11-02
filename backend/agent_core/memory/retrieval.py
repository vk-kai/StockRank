# -*- coding: utf-8 -*-
"""统一记忆检索: SQLite FTS5 BM25 + 2-gram 融合
- BM25: 索引级相关性排序, 中文按单字切分索引(unicode61), 相邻短语=精确子串
- 2-gram: 字符二元组重叠评分, 负责容错召回与再排序
- FTS5 不可用时自动退回纯 2-gram 全量扫描(原逻辑)
"""
import os, re, time, sqlite3, threading
from agent_core import config
from agent_core.memory import indexer

_PUNCT = re.compile(r'[，。！？,.!?~…\s（）()【】\[\]“”"\'、;；:：\-—_·<>《》]')
DB_PATH = os.path.join(config.CACHE, 'memory_fts.db')

_lock = threading.Lock()
_state = None   # {'ok': bool}


def clean(text):
    return _PUNCT.sub('', text or '')


def bigrams(text):
    s = clean(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _fts_available():
    try:
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE VIRTUAL TABLE t USING fts5(x)')
        conn.close()
        return True
    except Exception:
        return False


def _ensure():
    """懒建 FTS 索引(磁盘缓存, 消息数变化时重建)"""
    global _state
    if _state is not None:
        return _state
    with _lock:
        if _state is not None:
            return _state
        if not _fts_available():
            print('[检索] 当前 SQLite 不支持 FTS5, 使用 2-gram 扫描回退', flush=True)
            _state = {'ok': False}
            return _state
        idx = indexer.mem_index()
        # 只用「真实聊天」条数判断是否重建: 分身经历持续增长但不需重建(有 recent_for 直注通道),
        # 而真实聊天哪怕新增几十条(如新导入某联系人的记录)也必须重建, 否则检索永远搜不到
        real_n = sum(1 for it in idx if not it['rel'].startswith('经历/'))
        n_real = None
        if os.path.exists(DB_PATH):
            try:
                conn = sqlite3.connect(DB_PATH)
                row = conn.execute('SELECT v FROM meta WHERE k="real"').fetchone()
                n_real = int(row[0]) if row else None   # 旧库无 real 键 → 强制重建一次
                conn.close()
            except Exception:
                n_real = None
        flag = DB_PATH + '.rebuild'   # 数据同步后强制重建标记
        if os.path.exists(flag):
            try:
                os.remove(flag)
            except Exception:
                pass
            n_real = None
        if n_real != real_n:
            try:
                if os.path.exists(DB_PATH):
                    os.remove(DB_PATH)
                conn = sqlite3.connect(DB_PATH)
                conn.execute('CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)')
                conn.execute("CREATE VIRTUAL TABLE msgs USING fts5(spaced, raw UNINDEXED, "
                             "ct UNINDEXED, t UNINDEXED, s UNINDEXED, rel UNINDEXED, line UNINDEXED, "
                             "tokenize='unicode61')")
                batch = []
                for it in idx:
                    spaced = ' '.join(clean(it['c']))
                    if not spaced:
                        continue
                    batch.append((spaced, it['c'], it['ct'], it['t'], it['s'], it['rel'], it['line']))
                    if len(batch) >= 5000:
                        conn.executemany('INSERT INTO msgs VALUES(?,?,?,?,?,?,?)', batch)
                        batch = []
                if batch:
                    conn.executemany('INSERT INTO msgs VALUES(?,?,?,?,?,?,?)', batch)
                conn.execute('INSERT INTO meta VALUES("count", ?)', (str(len(idx)),))
                conn.execute('INSERT INTO meta VALUES("real", ?)', (str(real_n),))
                conn.commit()
                conn.close()
                print(f'[检索] FTS5 索引已建立: 真实聊天 {real_n} 条 + 经历 {len(idx) - real_n} 条', flush=True)
            except Exception as e:
                print(f'[检索] FTS5 建立失败, 回退 2-gram 扫描: {e}', flush=True)
                _state = {'ok': False}
                return _state
        _state = {'ok': True}
        return _state


def _q(s):
    return s.replace('"', '""')


def _bm25_candidates(message, contact, candidate_k):
    """FTS5 检索: 先整句短语(精确子串), 不足再 bigram OR 放宽; 返回统一 item 列表"""
    st = _ensure()
    if not st['ok']:
        return None
    s = clean(message)
    if len(s) < 2:
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        hits, seen = [], set()

        def run(match_sql):
            for raw, ct, t, sp, rel, line, rank in conn.execute(
                    'SELECT raw, ct, t, s, rel, line, bm25(msgs) FROM msgs '
                    'WHERE msgs MATCH ? ORDER BY rank LIMIT ?', (match_sql, candidate_k * 2)):
                key = (rel, line)
                if key in seen:
                    continue
                seen.add(key)
                hits.append({'rel': rel, 'line': line, 't': t, 's': sp, 'c': raw,
                             'cl': (raw or '').lower(), 'ct': ct, 'ty': 'text',
                             'rank': rank})

        run('"' + _q(' '.join(s)) + '"')           # 相邻短语 = 原句子串
        if len(hits) < candidate_k and len(s) >= 3:
            bg = ['"' + _q(' '.join(s[i:i + 2])) + '"' for i in range(min(len(s) - 1, 12))]
            if bg:
                try:
                    run(' OR '.join(bg))           # 二元组放宽召回
                except sqlite3.OperationalError:
                    pass
    finally:
        conn.close()
    if not hits:
        return []
    ranks = [h['rank'] for h in hits]
    best, worst = min(ranks), max(ranks)
    for h in hits:
        h['bm25n'] = (worst - h['rank']) / (worst - best + 1e-9)   # 1=最相关
    return hits


def _scan_fallback(message, contact, candidate_k):
    """2-gram 全量扫描(FTS 不可用时的回退, 即原 mem_related 逻辑)"""
    gs = bigrams(message)
    if not gs:
        return []
    need = 2 if len(gs) > 4 else 1
    idx = indexer.mem_index()
    scored = []
    for it in idx:
        if it['c'] == message or len(it['c']) < 2:
            continue
        sc = sum(1 for g in gs if g in it['cl'])
        if sc >= need:
            scored.append((sc, it))
    scored.sort(key=lambda x: -x[0])
    if contact:
        scored.sort(key=lambda x: 0 if (x[1]['ct'] == contact or x[1].get('s') == contact) else 1)
    out = []
    for sc, it in scored[:candidate_k]:
        it2 = dict(it)
        it2['bm25n'] = sc / (len(gs) + 1)
        out.append(it2)
    return out


def _recency(t):
    """新近度因子(检索三因子之一, 参照 Generative Agents): 指数衰减
    0.995^天数: 昨天≈0.995, 一个月≈0.86, 一年≈0.16 —— 新消息排序自然靠前但不屏蔽旧闻"""
    try:
        ts = time.mktime(time.strptime(str(t)[:19], '%Y-%m-%d %H:%M:%S'))
        return 0.995 ** max(0.0, (time.time() - ts) / 86400)
    except Exception:
        return 0.0


def retrieve(message, contact=None, top_k=12, candidate_k=60):
    """统一检索入口: 数字分身与记忆分析都从这里拿相关历史
    排序 = 词法相关性 + 语义向量(可选) + 当前联系人加权 + 新近度衰减
    返回 top_k 条 [{rel,line,t,s,c,cl,ct,ty,score}] — 与当前联系人相关的优先"""
    s = clean(message)
    if len(s) < 2:
        return []
    cands = _bm25_candidates(message, contact, candidate_k)
    if cands is None:
        cands = _scan_fallback(message, contact, candidate_k)
    # 语义向量召回(可选增强, 配置 embedding_model 后生效): 弥补同义改写/模糊指代的召回
    vec_hits = []
    try:
        from agent_core.memory import vector_recall
        vec_hits = vector_recall.search(message, top_k=candidate_k)
    except Exception:
        vec_hits = []
    if not cands and not vec_hits:
        return []
    gs = bigrams(message)
    pool = {}
    for it in cands:
        pool[(it['rel'], it['line'])] = [it, 0.0]
    for h in vec_hits:
        k = (h['it']['rel'], h['it']['line'])
        e = pool.get(k)
        if e is None:
            e = pool[k] = [h['it'], 0.0]
        e[1] = h['vec_n']   # 语义余弦分 0-1
    scored = []
    for it, vec_n in pool.values():
        ov = len(gs & bigrams(it['c'])) / max(1, len(gs))
        sc = it.get('bm25n', 0) * 0.6 + ov * 0.4
        if vec_n:
            sc = sc * 0.7 + vec_n * 0.5   # 融合: 有语义分时词法分让位 30%, 语义分占半权重
        if contact and (it['ct'] == contact or it['s'] == contact):
            sc += 0.15   # 当前聊天对象优先(按会话名或发言人匹配, 支持群友)
        sc += 0.25 * _recency(it.get('t', ''))
        scored.append((sc, it))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, it in scored[:top_k]:
        it['score'] = round(sc, 4)
        out.append(it)
    return out
