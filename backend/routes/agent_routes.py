# -*- coding: utf-8 -*-
"""个人数字分身 Agent —— Flask 接口层 (对应本地版 个人Agent/server.py 的全部接口)

═══════════════════════════════════════════════════════════════════════════
★ 网关的事儿没干 (留给接手 AI 的重要备注, 用户原话: "网关的事儿没干")
───────────────────────────────────────────────────────────────────────────
LLM API 网关(访问 OpenAI 兼容接口的 base_url/api_key)用户自己解决, 本项目不负责。
agent_core/config.json 只留 base_url/api_key/model(+embedding_model) 结构,
模板见 agent_core/config.example.json。

预研过的方案(用户尚未拍板, 按推荐顺序):
1. 第三方中转站(用户倾向): 直接填中转站 base_url+key, 零运维, 数据过三方;
2. frp 反向隧道: 0vk.top 服务器(有公网 IP)跑 frps, 本地跑 frpc 把本地
   API 网关(如 one-api/new-api)映射到公网; base_url 填 http://0vk.top:PORT/v1;
   免费自建, 密钥不出本地, 需要维护 frpc 常驻;
3. Tailscale/ZeroTier 组网: 云端容器与本地机器同虚拟网, base_url 指本地
   网关的虚拟 IP; 最私密, 但云端重启/本地离线时 AI 功能全断;
4. cloudflared tunnel: 免费穿透, 不需要公网 IP, 延迟略高。
结论: 网关未实施, 以上为预言方案, 接手者可从中直接选型落地。
═══════════════════════════════════════════════════════════════════════════

设计说明:
- 全部路由挂 /api/agent 前缀, 被 auth_routes 的登录守卫自动保护(不在白名单);
- 前端不是本地版的单页 index.html, 而是 frontend 的 Vue 页面(AgentAvatar.vue);
- 数据管道 step1(直连微信增量导出)只在本地可用 —— 云端 env 检测不到 key.txt/
  xwechat_files, pipeline.status().ready=False, 一键同步按钮在云端置灰, 数据由
  本地同步器(scripts/agent_local_sync.py)经 /sync/* 接口推上来;
- 经验: 聊天接口的落盘钩子(experience.log_exchange)与本地版一致。
"""
import json
import threading

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from agent_core import config as agent_config
from agent_core.config import jload
from agent_core.llm_client import LLMError
from agent_core import knowledge, cache_store, pipeline
from agent_core.memory import human_feedback, experience, indexer, retrieval
from agent_core.analysis import profile as ai_profile
from agent_core.analysis import timeline as ai_timeline
from agent_core.analysis import relationships, home
from agent_core.agents import persona_agent, analysis_agent, contact_agent, eq_agent
from agent_core.simulation import engine as sim_engine

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

_builder_started = False


def _maybe_start_builder():
    """向量语义召回后台线程(只启动一次; 未配 embedding_model 时为空操作)"""
    global _builder_started
    if _builder_started:
        return
    _builder_started = True
    try:
        from agent_core.memory import vector_recall
        if vector_recall.enabled():
            threading.Thread(target=vector_recall.builder_loop, daemon=True).start()
    except Exception:
        pass


def _err(msg, code=400):
    return jsonify({'error': msg}), code


def _body():
    if (request.content_length or 0) > agent_config.MAX_BODY:
        raise ValueError('请求体过大')
    return request.get_json(force=True, silent=True) or {}


def _stream(gen):
    """NDJSON 流式响应(前端按行读 {step}/{done} 事件); X-Accel-Buffering 防 nginx 缓冲"""
    return Response(stream_with_context(gen),
                    content_type='application/x-ndjson; charset=utf-8',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _emit_json(obj):
    return json.dumps(obj, ensure_ascii=False) + '\n'


def _valid_contact(name):
    return bool(name) and (name == '新朋友' or name.startswith('陌生·')
                           or knowledge.contact_info(name) is not None)


def _chat_dialog(contact, mode, hist, message, confirms, progress, persona=None,
                 direction='owner'):
    """dialog=第一人称分身 / ask=旁观者问答; 返回统一 dict(含 unsure/candidates)
    direction='contact' 为身份互换: AI 扮演联系人(回复不落盘为万凯经历)"""
    if mode == 'ask':
        hint = None if contact == '新朋友' else contact
        r = analysis_agent.answer(hist, message, contact_hint=hint, confirm_names=confirms,
                                  progress=progress, persona=persona)
        return {'reply': r.get('reply', ''), 'analysis': r.get('analysis'),
                'unsure': r.get('unsure', False), 'candidates': r.get('candidates', [])}
    if direction == 'contact':
        r = contact_agent.reply(contact, hist, message, progress=progress)
        pr = human_feedback.parse_reply(r)
        return {'reply': pr['reply'], 'unsure': pr['unsure'],
                'candidates': pr['candidates'], '_twin': True}
    r = persona_agent.reply(contact, hist, message, progress=progress)
    pr = human_feedback.parse_reply(r)
    return {'reply': pr['reply'], 'unsure': pr['unsure'], 'candidates': pr['candidates']}


# ═══════════════ GET ═══════════════

@agent_bp.before_request
def _init():
    _maybe_start_builder()


@agent_bp.route('/contacts')
def contacts():
    return jsonify({'contacts': knowledge.contacts()})


@agent_bp.route('/style')
def style():
    return jsonify(knowledge.style_profile())


@agent_bp.route('/overview')
def overview():
    return jsonify(jload(agent_config.KB + '/总览统计.json', {}))


@agent_bp.route('/facts')
def facts():
    return jsonify(knowledge.facts())


@agent_bp.route('/config', methods=['GET'])
def get_config():
    cfg = agent_config.load_config()
    return jsonify({'base_url': cfg.get('base_url', ''), 'model': cfg.get('model', ''),
                    'embedding_model': cfg.get('embedding_model', ''),
                    'has_key': bool(cfg.get('api_key'))})


@agent_bp.route('/config', methods=['POST'])
def save_config():
    b = _body()
    cfg = agent_config.load_config()
    for k in ('base_url', 'api_key', 'model', 'embedding_model'):
        if b.get(k) is not None and b.get(k) != '':
            cfg[k] = str(b[k]).strip()[:500]
    agent_config.save_config(cfg)
    return jsonify({'ok': True})


@agent_bp.route('/ai/me', methods=['GET'])
def ai_me_cached():
    r, _ = cache_store.load(agent_config.CACHE + '/profile_me.json')
    return jsonify(r)


@agent_bp.route('/ai/timeline', methods=['GET'])
def ai_timeline_cached():
    r, _ = cache_store.load(agent_config.CACHE + '/timeline.json')
    return jsonify(r)


@agent_bp.route('/daily')
def daily():
    return jsonify({'每日消息数': indexer.mem_daily()})


@agent_bp.route('/day/detail')
def day_detail():
    d = request.args.get('date', '')
    mo = request.args.get('month', '') == '1'
    import re as _re
    if not (mo and _re.match(r'^\d{4}-\d{2}$', d)) and not (not mo and _re.match(r'^\d{4}-\d{2}-\d{2}$', d)):
        raise ValueError('日期格式错误')
    items = indexer.day_breakdown(d, month=mo)
    for it in items:
        ci = knowledge.contact_info(it['name'])
        it['circle'] = (ci or {}).get('圈层猜测', '') if ci else ''
    return jsonify({'date': d, 'month': mo, 'total': sum(x['n'] for x in items),
                    'people': len(items), 'items': items[:80]})


@agent_bp.route('/month/compare')
def month_compare():
    a, b = request.args.get('a', ''), request.args.get('b', '')
    import re as _re
    if not _re.match(r'^\d{4}-\d{2}$', a) or not _re.match(r'^\d{4}-\d{2}$', b):
        raise ValueError('月份格式应为 YYYY-MM')
    A = {(x['name'], x['is_group']): x for x in indexer.day_breakdown(a, month=True)}
    B = {(x['name'], x['is_group']): x for x in indexer.day_breakdown(b, month=True)}
    rows = []
    for k in set(A) | set(B):
        na, nb = A.get(k, {}).get('n', 0), B.get(k, {}).get('n', 0)
        if na == 0 and nb == 0:
            continue
        rows.append({'name': k[0], 'is_group': k[1], 'a': na, 'b': nb, 'd': nb - na})

    def _circ(r):
        ci = knowledge.contact_info(r['name'])
        r['circle'] = (ci or {}).get('圈层猜测', '') if ci else ''
        return r
    inc = sorted((r for r in rows if r['d'] > 0), key=lambda x: -x['d'])[:15]
    dec = sorted((r for r in rows if r['d'] < 0), key=lambda x: x['d'])[:15]
    new = sorted((r for r in rows if r['a'] == 0), key=lambda x: -x['b'])[:8]
    gone = sorted((r for r in rows if r['b'] == 0), key=lambda x: -x['a'])[:8]
    return jsonify({'a': a, 'b': b,
                    'total_a': sum(x['n'] for x in A.values()),
                    'total_b': sum(x['n'] for x in B.values()),
                    'inc': [_circ(r) for r in inc], 'dec': [_circ(r) for r in dec],
                    'new': [_circ(r) for r in new], 'gone': [_circ(r) for r in gone]})


@agent_bp.route('/home/insights')
def home_insights():
    return jsonify(home.home_insights())


@agent_bp.route('/life_stats')
def life_stats():
    return jsonify(relationships.life_stats())


@agent_bp.route('/group/personas')
def group_personas():
    from agent_core.analysis import group_persona
    g = request.args.get('group', '')
    ci = knowledge.contact_info(g)
    if not ci or ci.get('类别') != '群聊':
        raise ValueError('未知群聊')
    return jsonify(group_persona.personas(g))


@agent_bp.route('/group/discover')
def group_discover():
    from agent_core.analysis import group_members
    return jsonify({'candidates': group_members.scan()[:80],
                    'promoted': knowledge.group_friends()})


@agent_bp.route('/sim/status')
def sim_status():
    return jsonify(sim_engine.status())


@agent_bp.route('/sim/timeline')
def sim_timeline():
    tl = sim_engine._timeline()
    return jsonify({'entries': tl[-60:], 'total': len(tl)})


@agent_bp.route('/sim/export')
def sim_export():
    p = sim_engine.export()
    if not p:
        return _err('暂无虚拟经历可导出', 400)
    import os as _os
    return jsonify({'ok': True, 'path': p, 'file': _os.path.basename(p)})


@agent_bp.route('/pipeline/status')
def pipeline_status():
    return jsonify(pipeline.status())


@agent_bp.route('/vector/status')
def vector_status():
    from agent_core.memory import vector_recall
    return jsonify(vector_recall.status())


@agent_bp.route('/interventions')
def interventions_list():
    limit = min(int(request.args.get('limit') or 6), 50)
    return jsonify(human_feedback.load_recent(limit))


@agent_bp.route('/network/circles')
def network_circles():
    return jsonify({'circles': relationships.circles()})


@agent_bp.route('/network/graph')
def network_graph():
    year = request.args.get('year') or None
    limit = min(int(request.args.get('limit') or 140), 321)
    return jsonify(relationships.graph(year=year, limit=limit))


@agent_bp.route('/network/ego')
def network_ego():
    name = request.args.get('name', '')
    if not _valid_contact(name):
        return _err('联系人不存在', 404)
    r = relationships.ego(name)
    if not r:
        return _err('联系人不存在', 404)
    return jsonify(r)


@agent_bp.route('/memory/search')
def memory_search():
    g = lambda k: request.args.get(k, '')
    limit = min(int(g('limit') or 40), 100)
    hits = indexer.mem_search(g('q'), contact=g('contact') or None,
                              date_from=g('from') or None, date_to=g('to') or None,
                              only_me=g('me') == '1', limit=limit)
    fuzzy = False
    if g('fuzzy') == '1' and g('q').strip() and len(hits) < 5:
        # 精确命中太少 → BM25+2gram 融合检索补充近似结果
        extra = retrieval.retrieve(g('q'), contact=g('contact') or None, top_k=limit)
        seen = {(h['rel'], h['line']) for h in hits}
        for it in extra:
            if (it['rel'], it['line']) in seen:
                continue
            seen.add((it['rel'], it['line']))
            it['fuzzy'] = True
            hits.append(it)
        hits.sort(key=lambda x: x['t'], reverse=True)
        hits = hits[:limit]
        fuzzy = True
    return jsonify({'hits': hits, 'fuzzy': fuzzy})


@agent_bp.route('/memory/context')
def memory_context():
    import urllib.parse as _up
    rel = _up.unquote(request.args.get('rel', ''))
    line_no = int(request.args.get('line', 0))
    return jsonify({'messages': indexer.mem_context(rel, line_no)})


@agent_bp.route('/ai/contact', methods=['GET'])
def ai_contact_cached():
    import urllib.parse as _up
    import os as _os
    name = _up.unquote(request.args.get('name', ''))
    r, meta = cache_store.load(_os.path.join(
        agent_config.CACHE, f'contact_{knowledge.safe_fn(name)}.json'))
    # 只要有历史生成结果就返回(不做过期检查): 画像保留生成时刻的认知, 直到用户主动重新生成
    return jsonify({'result': r, 'generated_at': (meta or {}).get('generated_at')})


@agent_bp.route('/recent_chat')
def recent_chat():
    import urllib.parse as _up
    name = _up.unquote(request.args.get('name', ''))
    limit = min(int(request.args.get('limit') or 24), 60)
    f2n, _ = relationships.name_maps()
    rels = [r for r, n in f2n.items() if n == name]
    idx = indexer.mem_index()
    if not rels:
        # 回退: 档案没收录的名字(如原始文件名'随风_soulwyb')按索引显示名匹配
        rels = sorted({it['rel'] for it in idx if it['ct'] == name})
    if not rels and (knowledge.contact_info(name) or {}).get('类别') == '群友':
        # 群友: 无 1:1 会话, 按发言人从群聊消息里取
        rows = sorted((it for it in idx if it['s'] == name and it.get('c')), key=lambda x: x['t'])
        return jsonify({'name': name, 'total': len(rows),
                        'span': [rows[0]['t'][:10], rows[-1]['t'][:10]] if rows else [],
                        'msgs': [{'t': it['t'], 's': it['s'], 'c': it['c']} for it in rows[-limit:]]})
    rows = sorted((it for it in idx if it['rel'] in rels and it.get('c')), key=lambda x: x['t'])
    msgs = [{'t': it['t'], 's': it['s'], 'c': it['c']} for it in rows[-limit:]]
    return jsonify({'name': name, 'total': len(rows),
                    'span': [rows[0]['t'][:10], rows[-1]['t'][:10]] if rows else [],
                    'msgs': msgs})


# ═══════════════ POST ═══════════════

@agent_bp.route('/chat', methods=['POST'])
def chat():
    b = _body()
    contact = str(b.get('contact') or '新朋友').strip()[:60]
    mode = b.get('mode', 'dialog')
    if not _valid_contact(contact):
        raise LLMError(f'联系人「{contact}」不在档案中')
    message = str(b.get('message') or '')[:2000]
    if not message.strip():
        return _err('消息为空', 400)
    hist = b.get('history') if isinstance(b.get('history'), list) else []
    hist = [h for h in hist if isinstance(h, dict) and h.get('content')][:30]
    confirms = b.get('confirm_names') if isinstance(b.get('confirm_names'), list) else []
    confirms = [str(n)[:60] for n in confirms if isinstance(n, str)][:4]

    if b.get('stream'):
        # 流式 NDJSON: 每行一个事件 {step:阶段文案} … 最后 {done:..}
        # LLM 调用放在工作线程, progress 回调经队列转成 {step} 行, 结束发 {done}
        import queue as _q
        out_q = _q.Queue()

        def work():
            try:
                r = _chat_dialog(contact, mode, hist, message, confirms,
                                 progress=lambda s: out_q.put(('step', {'step': s})),
                                 persona='oracle' if b.get('persona') == 'oracle' else None,
                                 direction='contact' if (b.get('direction') or 'owner') == 'contact' else 'owner')
                out_q.put(('done', {'done': True, **r}))
            except (LLMError, ValueError) as e:
                out_q.put(('done', {'done': True, 'error': str(e)}))
            except Exception as e:
                print(f'[error] agent/chat(stream) :: {e}')
                out_q.put(('done', {'done': True, 'error': '服务器内部错误，请查看服务日志'}))

        def gen():
            th = threading.Thread(target=work, daemon=True)
            th.start()
            while True:
                kind, payload = out_q.get()
                yield _emit_json(payload)
                if kind == 'done':
                    break
        return _stream(gen())

    r = _chat_dialog(contact, mode, hist, message, confirms, None,
                     persona='oracle' if b.get('persona') == 'oracle' else None,
                     direction='contact' if (b.get('direction') or 'owner') == 'contact' else 'owner')
    # dialog 有把握的回复自动落盘为分身经历(拿不准的走人工介入后记录)
    # 身份互换(direction=contact, AI 扮演联系人)是模拟对话, 不落盘为万凯经历
    if mode != 'ask' and not r.get('_twin') and not r.get('unsure') and r.get('reply'):
        try:
            experience.log_exchange(contact, message, r['reply'])
        except Exception:
            pass
    return jsonify(r)


@agent_bp.route('/interventions', methods=['POST'])
def interventions_save():
    # 人工介入闭环: 保存本人决定(人工直答/选定候选/直接采用)并写入知识库
    # 经记忆质检后, 对分身训练没有帮助的回答只回复但不入纠正记忆
    b = _body()
    fr, saved = human_feedback.save_decision(
        question=str(b.get('question') or ''),
        ai_draft=str(b.get('ai_draft') or ''),
        contact=str(b.get('contact') or '')[:60],
        mode=str(b.get('mode') or 'dialog')[:10],
        choice=str(b.get('choice') or ''),
        human_answer=str(b.get('human_answer') or ''),
        candidates=b.get('candidates') if isinstance(b.get('candidates'), list) else [],
        candidate_index=b.get('candidate_index'))
    # dialog 模式经人工介入后的最终回答也落盘为分身经历(ask 是旁观问答, 不算)
    if (b.get('mode') or 'dialog') == 'dialog' and fr:
        try:
            experience.log_exchange(str(b.get('contact') or ''),
                                    str(b.get('question') or ''), fr)
        except Exception:
            pass
    return jsonify({'ok': True, 'final_reply': fr, 'memory_saved': bool(saved)})


@agent_bp.route('/feedback/delete', methods=['POST'])
def feedback_delete():
    # 手动删除一条纠正记忆(设置页清理噪音)
    b = _body()
    ok = human_feedback.delete_record(str(b.get('时间') or '')[:30])
    return jsonify({'ok': bool(ok)})


@agent_bp.route('/twin/contact/status')
def twin_status():
    # 身份互换: 查联系人分身塑造状态(消息量门槛/是否已塑造)
    import urllib.parse as _up
    name = _up.unquote(request.args.get('contact', ''))
    return jsonify(contact_agent.status(name))


@agent_bp.route('/twin/contact/build', methods=['POST'])
def twin_build():
    # 身份互换: 为联系人塑造数字分身画像(耗时 30-90 秒, 结果缓存)
    b = _body()
    name = str(b.get('contact') or '').strip()[:60]
    if not _valid_contact(name):
        raise ValueError(f'联系人「{name}」不在档案中')
    return jsonify(contact_agent.build(name))


# ─── 高情商练习(eq): 与分身主对话完全隔离的独立存档 cache/eq_chats/ ───

@agent_bp.route('/eq/chat')
def eq_chat():
    # 读取某发展对象的会话历史
    import urllib.parse as _up
    name = _up.unquote(request.args.get('contact', ''))
    return jsonify({'chat': eq_agent.load_chat(name)})


@agent_bp.route('/eq/reply', methods=['POST'])
def eq_reply():
    # 三方一轮: 她说 girl → 万凯原话 mine → 高情商版回复(一次性落盘三条)
    b = _body()
    contact = str(b.get('contact') or '').strip()[:60]
    girl = str(b.get('girl') or '').strip()[:2000]
    mine = str(b.get('mine') or '').strip()[:2000]
    if not contact or not girl or not mine:
        raise ValueError('需要 contact / girl / mine 三个字段')
    return jsonify(eq_agent.reply(contact, girl, mine))


@agent_bp.route('/eq/diagnose', methods=['POST'])
def eq_diagnose():
    # 诊断万凯原话 vs 高情商版(不落盘)
    b = _body()
    return jsonify(eq_agent.diagnose(str(b.get('contact') or '')[:60],
                                     str(b.get('girl') or '')[:2000],
                                     str(b.get('mine') or '')[:2000],
                                     str(b.get('eq') or '')[:2000]))


@agent_bp.route('/eq/clear', methods=['POST'])
def eq_clear():
    # 清空某发展对象的会话记忆
    b = _body()
    eq_agent.delete_chat(str(b.get('contact') or '').strip()[:60])
    return jsonify({'ok': True})


@agent_bp.route('/who', methods=['POST'])
def who():
    b = _body()
    message = str(b.get('message') or '')[:1000]
    if not message.strip():
        return jsonify({'candidates': []})
    try:
        return jsonify({'candidates': analysis_agent.who(message)})
    except Exception as e:
        print(f'[error] agent/who :: {e}')
        return jsonify({'candidates': []})


@agent_bp.route('/network/insight', methods=['POST'])
def network_insight():
    b = _body()
    message = str(b.get('message') or '')[:1000]
    if not message.strip():
        return _err('消息为空', 400)
    hist = b.get('history') if isinstance(b.get('history'), list) else []
    hist = [h for h in hist if isinstance(h, dict) and h.get('content')][:20]
    names = b.get('names') if isinstance(b.get('names'), list) else []
    names = [str(n)[:60] for n in names if _valid_contact(str(n))][:3]
    ctx = relationships.insight_context(names or None)

    if b.get('stream'):
        import queue as _q
        out_q = _q.Queue()

        def work():
            try:
                r = analysis_agent.answer(hist, message, extra_context=ctx,
                                          progress=lambda s: out_q.put(('step', {'step': s})),
                                          persona='oracle' if b.get('persona') == 'oracle' else None)
                out_q.put(('done', {'done': True, 'reply': r.get('reply', ''),
                                    'analysis': r.get('analysis')}))
            except (LLMError, ValueError) as e:
                out_q.put(('done', {'done': True, 'error': str(e)}))
            except Exception as e:
                print(f'[error] agent/network/insight(stream) :: {e}')
                out_q.put(('done', {'done': True, 'error': '服务器内部错误，请查看服务日志'}))

        def gen():
            th = threading.Thread(target=work, daemon=True)
            th.start()
            while True:
                kind, payload = out_q.get()
                yield _emit_json(payload)
                if kind == 'done':
                    break
        return _stream(gen())
    return jsonify(analysis_agent.answer(hist, message, extra_context=ctx,
                                         persona='oracle' if b.get('persona') == 'oracle' else None))


@agent_bp.route('/group/chat', methods=['POST'])
def group_chat():
    # 群聊模拟: 一条消息 → 多个成员先后冒泡
    from agent_core.analysis import group_persona
    b = _body()
    g = (b.get('group') or '').strip()
    msg = (b.get('message') or '').strip()
    ci = knowledge.contact_info(g)
    if not ci or ci.get('类别') != '群聊':
        raise ValueError('未知群聊')
    if not msg:
        raise ValueError('消息不能为空')
    return jsonify(group_persona.reply_group(g, msg[:500], hist=b.get('hist') or []))


@agent_bp.route('/group/promote', methods=['POST'])
def group_promote():
    from agent_core.analysis import group_members
    b = _body()
    entry = group_members.promote(str(b.get('name') or ''))
    return jsonify({'ok': True, 'entry': entry})


@agent_bp.route('/group/demote', methods=['POST'])
def group_demote():
    from agent_core.analysis import group_members
    b = _body()
    group_members.demote(str(b.get('name') or ''))
    return jsonify({'ok': True})


@agent_bp.route('/pipeline/run', methods=['POST'])
def pipeline_run():
    # 一键同步: 增量导出→重建知识库 (流式 NDJSON 实时进度)
    # 云端(无微信环境) step1 会因检测不到 key.txt 失败, 数据请走 /sync/* 接口由本地推送
    import queue as _q
    out_q = _q.Queue()

    def work():
        try:
            r = pipeline.run_pipeline(progress=lambda s: out_q.put(('step', {'step': s})))
            out_q.put(('done', {'done': True, 'result': r}))
        except Exception as e:
            out_q.put(('done', {'done': True, 'error': str(e) or '同步失败，请查看服务日志'}))

    def gen():
        th = threading.Thread(target=work, daemon=True)
        th.start()
        while True:
            kind, payload = out_q.get()
            yield _emit_json(payload)
            if kind == 'done':
                break
    return _stream(gen())


@agent_bp.route('/sim/step', methods=['POST'])
def sim_step():
    b = _body()
    days = b.get('days', 1)
    days = 1 if days in (1, '1') else (7 if days in (7, '7') else 30)
    return jsonify(sim_engine.run_step(days))


@agent_bp.route('/sim/audit', methods=['POST'])
def sim_audit():
    return jsonify(sim_engine.deep_audit())


@agent_bp.route('/sim/approve', methods=['POST'])
def sim_approve():
    b = _body()
    if not sim_engine.approve(str(b.get('id', '')), b.get('ok', True)):
        return _err('条目不存在', 400)
    return jsonify({'ok': True})


@agent_bp.route('/sim/delete', methods=['POST'])
def sim_delete():
    b = _body()
    return jsonify({'ok': sim_engine.delete(str(b.get('id', '')))})


@agent_bp.route('/sim/config', methods=['POST'])
def sim_config():
    b = _body()
    if 'merge' in b:
        sim_engine.set_merge(b.get('merge'))
    return jsonify(sim_engine.status())


@agent_bp.route('/ai/me', methods=['POST'])
def ai_me_gen():
    return jsonify({'result': ai_profile.generate_me()})


@agent_bp.route('/ai/timeline', methods=['POST'])
def ai_timeline_gen():
    return jsonify({'result': ai_timeline.generate_timeline()})


@agent_bp.route('/ai/contact', methods=['POST'])
def ai_contact_gen():
    b = _body()
    name = str(b.get('contact') or '').strip()[:60]
    if not knowledge.contact_info(name):
        raise LLMError(f'联系人「{name}」不存在')
    if b.get('stream'):
        import queue as _q
        out_q = _q.Queue()

        def work():
            try:
                r = ai_profile.generate_contact(name,
                                                progress=lambda s: out_q.put(('step', {'step': s})))
                out_q.put(('done', {'done': True, 'result': r}))
            except (LLMError, ValueError) as e:
                out_q.put(('done', {'done': True, 'error': str(e)}))
            except Exception as e:
                print(f'[error] agent/ai/contact(stream) :: {e}')
                out_q.put(('done', {'done': True, 'error': '服务器内部错误，请查看服务日志'}))

        def gen():
            th = threading.Thread(target=work, daemon=True)
            th.start()
            while True:
                kind, payload = out_q.get()
                yield _emit_json(payload)
                if kind == 'done':
                    break
        return _stream(gen())
    return jsonify({'result': ai_profile.generate_contact(name)})


# ═══════════════ 数据同步接口(本地同步器专用, 配合 scripts/agent_local_sync.py) ═══════════════
# 方向: 本地(主战场, 微信增量导出+build_kb) → 云端。鉴权走站内登录 session(同步器先
# POST /api/auth/login 拿 cookie), 不引入新凭据体系。

_SYNC_ALLOW_SUBDIRS = ('聊天记录数据', 'Agent知识库')
_SYNC_ALLOW_EXT = ('.jsonl', '.json')


def _safe_sync_path(rel):
    """同步文件路径白名单校验: 只允许 agent_data 下两个子目录的 jsonl/json, 防路径穿越"""
    rel = (rel or '').replace('\\', '/').lstrip('/')
    if '..' in rel or ':' in rel:
        raise ValueError('非法路径')
    parts = rel.split('/')
    if len(parts) < 2 or parts[0] not in _SYNC_ALLOW_SUBDIRS:
        raise ValueError(f'只允许同步 {_SYNC_ALLOW_SUBDIRS} 下的文件')
    if not rel.endswith(_SYNC_ALLOW_EXT):
        raise ValueError('只允许 .jsonl/.json 文件')
    import os as _os
    return _os.path.join(agent_config.DATA_ROOT, *parts)


@agent_bp.route('/sync/poll')
def sync_poll():
    """云端现有数据清单: {rel: [size, mtime]} + 环境状态, 本地比对后只传增量"""
    import os as _os
    files = {}
    for sub in _SYNC_ALLOW_SUBDIRS:
        root = _os.path.join(agent_config.DATA_ROOT, sub)
        for cur, _dirs, fns in _os.walk(root):
            for fn in fns:
                if not fn.endswith(_SYNC_ALLOW_EXT):
                    continue
                p = _os.path.join(cur, fn)
                r = sub + '/' + _os.path.relpath(p, root).replace('\\', '/')
                files[r] = [_os.path.getsize(p), int(_os.path.getmtime(p))]
    return jsonify({'files': files,
                    'kb_dir': agent_config.KB, 'data_dir': agent_config.DATA})


@agent_bp.route('/sync/upload', methods=['POST'])
def sync_upload():
    """批量写入数据文件: {files: [{rel, content(文本), base64?}], delete: [rel,…]}
    原子替换, 不做 1MB 请求体限制(数据文件可达几十 MB); delete 用于对方改名后清理旧文件"""
    import base64 as _b64
    import os as _os
    from agent_core import atomic_write
    b = request.get_json(force=True, silent=True) or {}
    items = b.get('files') if isinstance(b.get('files'), list) else []
    gone = b.get('delete') if isinstance(b.get('delete'), list) else []
    if not items and not gone:
        return _err('没有要上传/删除的文件')
    n, errs = 0, []
    for it in items[:500]:
        try:
            p = _safe_sync_path(it.get('rel', ''))
            data = it.get('content', '')
            if it.get('base64'):
                data = _b64.b64decode(data)
            else:
                data = str(data).encode('utf-8')
            _os.makedirs(_os.path.dirname(p), exist_ok=True)
            atomic_write(p, data)
            n += 1
        except Exception as e:
            errs.append({'rel': it.get('rel', ''), 'error': str(e)})
    deleted, del_errs = 0, []
    for rel in gone[:500]:
        try:
            p = _safe_sync_path(rel)
            if _os.path.exists(p):
                _os.remove(p)
                deleted += 1
        except Exception as e:
            del_errs.append({'rel': rel, 'error': str(e)})
    return jsonify({'ok': True, 'written': n, 'deleted': deleted,
                    'errors': errs + del_errs})


@agent_bp.route('/sync/rebuild', methods=['POST'])
def sync_rebuild():
    """数据推完后让云端重载: 清进程内缓存 + 打 FTS 重建标记(向量增量自动跟上)"""
    import os as _os
    from agent_core.memory import retrieval as _rt
    # 经验: FTS 索引按条数比对, 增量超过容差自动重建; 打标记强制小增量也重建
    try:
        with open(_rt.DB_PATH + '.rebuild', 'w') as f:
            f.write('1')
    except Exception:
        pass
    reloaded = []
    try:
        from agent_core.memory import indexer as _ix
        with _ix._mem_lock:
            _ix._mem_index = None
            _ix._mem_daily = None
        reloaded.append('消息索引')
    except Exception:
        pass
    try:
        with _rt._lock:
            _rt._state = None
        reloaded.append('FTS状态')
    except Exception:
        pass
    try:
        from agent_core.analysis import relationships as _rl
        with _rl._lock:
            _rl._data = None
            _rl._nm_cache = None
        reloaded.append('关系网')
    except Exception:
        pass
    try:
        import agent_core.knowledge as _kn
        _kn._ex_cache.clear()
        reloaded.append('范例缓存')
    except Exception:
        pass
    try:
        from agent_core.analysis import group_persona as _gp
        for attr in ('_persona_cache',):
            if hasattr(_gp, attr):
                setattr(_gp, attr, None)
        reloaded.append('群画像')
    except Exception:
        pass
    return jsonify({'ok': True, 'reloaded': reloaded})


# 统一错误语义(与本地版一致: LLMError/ValueError → 400, 其余 → 500)
@agent_bp.errorhandler(LLMError)
def _on_llm_err(e):
    return jsonify({'error': str(e)}), 400


@agent_bp.errorhandler(ValueError)
def _on_val_err(e):
    return jsonify({'error': str(e)}), 400


@agent_bp.errorhandler(Exception)
def _on_err(e):
    import traceback
    current_app.logger.error(f"[agent] {request.method} {request.path} :: "
                             f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    return jsonify({'error': str(e)}), 500
