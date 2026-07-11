"""AI 批量股票打分引擎（大盘云图）

用用户配置的 AI（🤖 AI大模型配置）对全市场 ~5000 只 A 股打 0-100 分
（50=中性，≥50 红/正面，<50 绿/谨慎），落盘后供云图着色/筛选/悬浮显示，
与"涨跌幅""融资净流入"并列成为第三个着色维度。

设计要点：
- 批量并发：每批 ~10 只一次 AI 调用，ThreadPoolExecutor(4 worker) 并发，
  全局节流控 RPS。5000 只约 25-40 分钟。
- 增量持久化：每批完成即原子合并到 scores.json，崩溃可续、前端可实时着色。
- 不走 ai_analyzer 的 20s 全局节流（last_ai_call_time）——直接调底层
  call_ai_api + parse_ai_response，避免被新闻节流互相阻塞。
- 异步任务模板镜像 flow_routes 的 analyze-daily（start/status/stop）。

数据流：
  data/realtime/market_map_industry.json (全市场股票清单)
    → 分批 → AI(chat/completions) → JSON{code:score} → data/stock_scores/scores.json
"""
import os
import json
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    AI_CONFIG_FILE, STOCK_SCORE_PROMPT_FILE,
    STOCK_SCORES_FILE, STOCK_SCORE_STATUS_FILE, STOCK_SCORES_DIR,
)
from ai_analyzer import load_ai_config, call_ai_api, parse_ai_response
from data_processor import get_all_market_map_stocks, error_logger
from logger import get_logger

info_logger = get_logger('ai')

# ============================== 调参常量 ==============================
# 默认串行（workers=1）+ 批间间隔 + 429 强制冷却，优先"能用"而非"快"，
# 避免触发智谱/OpenAI 兼容端点的 RPM/TPM 限流（429）。
# 均可在 ai_config.json 用 score_batch_size / score_max_workers / score_batch_interval /
# score_429_cooldown 覆盖（付费大额度用户可调高 workers 提速）。
DEFAULT_BATCH_SIZE = 10        # 每批股票数（AI 一次评分多少只）
DEFAULT_MAX_WORKERS = 1        # 并发 AI 调用数（默认串行，防限流）
MAX_RETRY_PER_BATCH = 3        # 单批失败重试次数（HTTP/超时/JSON 解析/限流）
BATCH_TIMEOUT_SEC = 120        # 单批 AI 请求超时（输出较长，比新闻 60s 宽松）
DEFAULT_BATCH_INTERVAL = 2.0   # 串行下相邻批次最小间隔(秒)，控 RPM
DEFAULT_429_COOLDOWN = 30      # 命中 429 后的强制冷却(秒)，Retry-After 缺省/过小时用此值
RATE_LIMIT_RETRY_CAP = 90      # 单次 429 退避上限(秒)，避免 Retry-After 异常大值

# ============================== 9 档分桶（0-100，50 为红绿分界）==============================
# 半开区间 (min, max]，两极开区间：score-1 只有 max(≤max)；score-9 只有 min(>min)。
# 与前端 inMarginFilter 完全同构，无需特判。50 落 score-5（红侧第一档，最浅红）。
# 配色：深绿(低分/谨慎) → 近50暗灰绿 → 近50暗灰红 → 深红(高分/乐观)，与涨跌幅/融资维度视觉一致。
SCORE_BUCKETS = [
    {'value': 'score-1', 'label': '≤10',    'countTitle': '极谨慎 0-10',    'max': 10,  'color': '#2cbc58'},
    {'value': 'score-2', 'label': '11-25',  'countTitle': '谨慎 11-25',     'min': 10,  'max': 25,  'color': '#2a9a55'},
    {'value': 'score-3', 'label': '26-40',  'countTitle': '偏谨慎 26-40',   'min': 25,  'max': 40,  'color': '#3d7a55'},
    {'value': 'score-4', 'label': '41-49',  'countTitle': '中性偏空 41-49', 'min': 40,  'max': 49,  'color': '#5a5a4a'},
    {'value': 'score-5', 'label': '50-59',  'countTitle': '中性偏多 50-59', 'min': 49,  'max': 59,  'color': '#6a4050'},
    {'value': 'score-6', 'label': '60-69',  'countTitle': '尚可 60-69',     'min': 59,  'max': 69,  'color': '#963c48'},
    {'value': 'score-7', 'label': '70-79',  'countTitle': '较优 70-79',     'min': 69,  'max': 79,  'color': '#c03843'},
    {'value': 'score-8', 'label': '80-89',  'countTitle': '优秀 80-89',     'min': 79,  'max': 89,  'color': '#e2323d'},
    {'value': 'score-9', 'label': '≥90',    'countTitle': '顶级 90-100',    'min': 89,              'color': '#f02d37'},
]

# 未评分时显示的中性色（区别于"被筛选灰显"），与前端 NO_MARGIN_COLOR 同思路
NO_SCORE_COLOR = '#3a4458'


def bucketize(score):
    """0-100 分 → 对应分桶 dict（含 value/label/countTitle/color）；非数值返回中性占位。"""
    if not isinstance(score, (int, float)) or score != score:  # NaN / None
        return {'value': 'score-0', 'label': '未评', 'countTitle': '未评分', 'color': NO_SCORE_COLOR}
    score = int(score)
    for b in SCORE_BUCKETS:
        lo = b.get('min')   # score-1 无 min → 开下区间
        hi = b.get('max')   # score-9 无 max → 开上区间
        if lo is None and hi is not None and score <= hi:
            return b
        if lo is not None and hi is None and score > lo:
            return b
        if lo is not None and hi is not None and lo < score <= hi:
            return b
    return SCORE_BUCKETS[0] if score <= 0 else SCORE_BUCKETS[-1]


# ============================== 默认提示词 ==============================
DEFAULT_STOCK_SCORE_PROMPT = """你是顶级 A 股投资分析师。你将收到一批 A 股股票（每只含：id=裸6位代码、name、l1=一级行业、l2=二级行业、cap=总市值(元)、pe=市盈率）。
请对每只给出 0-100 的综合评分（50=中性，≥50 偏正面/红，<50 偏负面/绿）。

【最重要原则：必须给出有区分度的评分，禁止大量给50】
即使你不熟悉某家具体公司，也必须根据【名称含义 + 所属行业(l1/l2)的周期景气 + 市值规模 + 市盈率 + 代码板块】综合推断，给出能区分好坏的分数。
"认知确定性"只是 8 个维度之一（不熟悉可给 5 分中性），其余 7 维（宏观/行业/龙头/护城河/资金/业绩/估值）都能从行业和财务推断，不要因为不认识公司就把总分压成50。
代码板块：688=科创板(硬科技/高端制造)、300/301=创业板(成长)、600/601=沪市主板、000/002=深市主板、8/4开头=北交所。

【8 维评分（各 0-10，5=中性，求和 ×100/80 = 展示分）】
1. 宏观友好度（利率/政策/流动性对该行业的边际影响）
2. 行业景气度（行业所处的周期：复苏/繁荣/顶部/衰退）
3. 龙头地位（该公司在 l2 细分赛道的市占率与话语权；大市值通常更靠前）
4. 护城河（技术/品牌/规模/牌照/网络效应）
5. 资金面（机构/北向/融资盘对该行业的边际倾向，凭行业认知推断）
6. 业绩质量（结合 pe 合理性、盈利稳定性）
7. 估值合理度（pe 是否匹配成长性；pe<0 亏损本维封顶 3 分）
8. 认知确定性（不熟悉可给 5 分，但不要让它拖垮总分）

【按行业+估值的快速推断锚点（不熟悉公司时据此打分，不要偷懒给50）】
- 成长/景气行业(半导体、AI算力、机器人、新能源、创新药、商业航天、军工电子) + 盈利 + 大中市值 → 65-85
- 科技/高端制造(科创板688/创业板300) + 国产替代/技术壁垒逻辑 → 55-78
- 成长行业 + 小盘 + 高估值(pe>60) → 48-62
- 银行/保险/公用事业/高速公路 + 低pe高股息 → 50-62
- 消费/医药白马 + 合理估值 → 55-70
- 周期股(化工/有色/钢铁/航运/猪肉) 处于景气下行 + 高估值 → 28-42
- 地产/传统基建链 → 25-40
- 亏损(pe<0) 且无反转逻辑 → 18-38
- ST/退市风险/重大违规 → 0-15

【分数带语义（必须落在对应区间，50 为红绿分界）】
90-100 顶级 / 80-89 优秀 / 70-79 较优 / 60-69 尚可 / 50-59 中性偏多 / 41-49 中性偏空 / 26-40 偏谨慎 / 11-25 谨慎 / 0-10 极谨慎

【硬性规则】
1. 每只都必须给有区分度的分数；一批里给 50 分的比例不得超过 20%。宁可基于行业+估值大胆推断，也不要保守地塞 50。
2. pe<0（亏损）：估值维度封顶 3 分。
3. 不得漏掉任何一只；输入 N 只，输出必须 N 条。
4. score 为 0-100 整数；reason ≤15 汉字，必须写具体依据（行业景气/估值高低/市值地位/题材逻辑），禁止只写"信息不足"。
   只有连行业属性都无法判断时（极少），才给 50-55 并写"按行业中性推断"。
5. label 从 9 个里选：顶级/优秀/较优/尚可/中性偏多/中性偏空/偏谨慎/谨慎/极谨慎。

【输出格式——严格 JSON 数组，不要任何解释、不要 markdown 代码块】
[
  {"id":"600519","score":92,"label":"顶级","reason":"白酒龙头护城河深"},
  {"id":"000001","score":58,"label":"中性偏多","reason":"银行稳健低估值"}
]"""


def load_stock_score_prompt():
    """读取打分提示词；文件不存在返回内置默认（不主动写文件）。"""
    try:
        if os.path.exists(STOCK_SCORE_PROMPT_FILE):
            with open(STOCK_SCORE_PROMPT_FILE, 'r', encoding='utf-8') as f:
                txt = f.read()
                return txt or DEFAULT_STOCK_SCORE_PROMPT
    except Exception as e:
        error_logger.error(f"读取股票打分提示词失败: {e}")
    return DEFAULT_STOCK_SCORE_PROMPT


# ============================== 模块级状态（镜像 flow_routes.ai_analysis_status）==============================
_score_status = {
    'status': 'idle',   # idle | running | completed | failed | interrupted
    'run_id': None,
    'message': '',
    'progress': 0,
    'step': '',
    'total': 0,
    'done': 0,
    'failed': 0,
    'last_error': '',
    'started_at': None,
    'updated_at': None,
    'ended_at': None,
}
_status_lock = threading.Lock()
_scores_write_lock = threading.Lock()
_cancel_event = threading.Event()
_worker_thread = None               # 当前后台线程引用（START 判活、崩溃检测用）
_global_rate_lock = threading.Lock()
_last_dispatch_ts = 0.0
_rate_cooldown_until = 0.0          # 命中限流后的"全局放行时间戳"：在此时间前所有 dispatch 都要等待
# 本轮生效的节流参数（由 _run_scoring_background 从 ai_config 读取后注入；默认值见常量）
_active_batch_interval = DEFAULT_BATCH_INTERVAL
_active_429_cooldown = DEFAULT_429_COOLDOWN
_last_batch_error = ''               # 最近一次批次失败原因（worker 写、runner 读，仅用于诊断展示）


def _now_iso():
    return datetime.now().astimezone().isoformat()


def _run_id():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


# ============================== 分数 IO（原子写，镜像 market_map_push_store）==============================
def load_scores():
    if not os.path.exists(STOCK_SCORES_FILE):
        return {}
    try:
        with open(STOCK_SCORES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        error_logger.error(f"读取股票打分失败: {e}")
        return {}


def _safe_replace(tmp, target):
    """os.replace 的 Windows 安全版：杀软/索引器/并发读 偶发锁定目标文件，
    导致 ERROR_ACCESS_DENIED (WinError 5)。重试几次；仍失败则回退为直接覆写
    目标（牺牲原子性换可用性——对低频的打分文件可接受）。"""
    last_err = None
    for i in range(6):
        try:
            os.replace(tmp, target)
            return
        except (PermissionError, OSError) as e:
            last_err = e
            time.sleep(0.15 * (i + 1))   # 约 0.15/0.3/0.45/0.6/0.75/0.9s，累计 ~3s
    # 回退：读到内存再直接覆写目标，然后删 tmp
    try:
        with open(tmp, 'r', encoding='utf-8') as src, open(target, 'w', encoding='utf-8') as dst:
            dst.write(src.read())
        try:
            os.remove(tmp)
        except OSError:
            pass
    except Exception:
        raise last_err


def _write_scores_atomic(scores):
    os.makedirs(STOCK_SCORES_DIR, exist_ok=True)
    tmp = STOCK_SCORES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(scores, f, ensure_ascii=False)
    _safe_replace(tmp, STOCK_SCORES_FILE)


def merge_batch_scores(batch_results, run_id):
    """把一批 {code:{score,label,reason}} 合并进 scores.json（read-modify-write，加锁）。
    每条加 scored_at + run_id。返回成功合并的条数。"""
    if not batch_results:
        return 0
    with _scores_write_lock:
        scores = load_scores()
        added = 0
        ts = _now_iso()
        for code, item in batch_results.items():
            if not isinstance(item, dict):
                continue
            score = item.get('score')
            try:
                score = int(score) if score is not None else None
            except (TypeError, ValueError):
                score = None
            if score is None:
                continue
            scores[code] = {
                'score': max(0, min(100, score)),
                'label': str(item.get('label') or bucketize(score)['countTitle'].split(' ')[0])[:8],
                'reason': str(item.get('reason') or '')[:30],
                'scored_at': ts,
                'run_id': run_id,
            }
            added += 1
        _write_scores_atomic(scores)
        return added


def get_score(code):
    return load_scores().get(str(code))


def clear_scores():
    with _scores_write_lock:
        if os.path.exists(STOCK_SCORES_FILE):
            os.remove(STOCK_SCORES_FILE)
    return True


# ============================== 状态 IO ==============================
def _default_status():
    return {
        'status': 'idle', 'run_id': None, 'message': '', 'progress': 0, 'step': '',
        'total': 0, 'done': 0, 'failed': 0,
        'started_at': None, 'updated_at': None, 'ended_at': None,
    }


def _load_status_file():
    if not os.path.exists(STOCK_SCORE_STATUS_FILE):
        return None
    try:
        with open(STOCK_SCORE_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_status_atomic(status):
    os.makedirs(STOCK_SCORES_DIR, exist_ok=True)
    tmp = STOCK_SCORE_STATUS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False)
    _safe_replace(tmp, STOCK_SCORE_STATUS_FILE)


def _update_status(**fields):
    """更新内存状态并尝试落盘。落盘失败只告警不抛——避免偶发的文件写抖动
    （Windows os.replace 被并发读/杀软短暂锁定）杀掉整个打分后台线程。内存状态始终是最新的。"""
    with _status_lock:
        _score_status.update(fields)
        _score_status['updated_at'] = _now_iso()
        if fields.get('status') in ('completed', 'failed', 'interrupted'):
            _score_status['ended_at'] = _now_iso()
        snapshot = dict(_score_status)
    try:
        _write_status_atomic(snapshot)
    except Exception as e:
        error_logger.warning(f"[股票打分] 状态落盘失败(已忽略，内存状态仍正确): {e}")


def get_status():
    """查询状态。运行中（后台线程存活）直接返回内存状态——更新最及时，且避免与
    后台线程写 status.json 争用 os.replace（Windows 下并发读+replace 会触发 WinError 5）。
    无活线程时读持久化文件以恢复状态（进程重启后），内存显示 running 但线程已死 → interrupted。"""
    global _worker_thread
    alive = _worker_thread is not None and _worker_thread.is_alive()
    if alive:
        with _status_lock:
            return dict(_score_status)
    file_status = _load_status_file()
    if file_status and file_status.get('status') in ('completed', 'failed', 'interrupted'):
        return file_status
    with _status_lock:
        cur = dict(_score_status)
    if cur.get('status') == 'running':
        cur['status'] = 'interrupted'
        cur['message'] = cur.get('message') or '上次打分未完成（进程已重启），已保留已评分结果'
    return cur


# ============================== 股票清单 ==============================
def _bare_code(sina_code):
    """sh600519 / sz000001 / bj830799 → 600519。无效返回 ''。"""
    digits = ''.join(ch for ch in str(sina_code or '') if ch.isdigit())
    return digits if len(digits) == 6 else ''


def _load_stock_list(scope='all'):
    """返回 [(bare_code, {name,l1,l2,value,pe}), ...]。scope：
       'all'          = 全量；
       'missing'      = 仅未评分的（score 为 None）；
       'insufficient' = 仅 reason 含"信息不足"的（针对上一轮被 AI 放弃的，换更强提示词后重评）。"""
    all_stocks = get_all_market_map_stocks()
    if not all_stocks:
        return []
    existing = load_scores() if scope != 'all' else {}
    out = []
    for sina_code, info in all_stocks.items():
        code = _bare_code(sina_code)
        if not code:
            continue
        if scope == 'missing':
            ent = existing.get(code)
            if ent and ent.get('score') is not None:
                continue
        elif scope == 'insufficient':
            ent = existing.get(code)
            if not ent or '信息不足' not in (ent.get('reason') or ''):
                continue
        out.append((code, {
            'name': info.get('name') or code,
            'l1': info.get('l1') or '',
            'l2': info.get('l2') or '',
            'value': info.get('value') or 0,
            'pe': info.get('pe'),
        }))
    return out


def _chunk(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]


# ============================== 单批 AI 调用 ==============================
def _resolve_chat_url(config):
    api_url = config.get('api_url')
    full_url = config.get('full_url', False)
    if not full_url and not api_url.endswith('/chat/completions'):
        api_url = api_url.rstrip('/') + '/chat/completions'
    return api_url


def _call_ai_batch(batch, config, prompt):
    """对一批 [(code, info)] 调用 AI，返回 {code: {score,label,reason}}。
    内含最多 MAX_RETRY_PER_BATCH 次重试（429 退避/超时/解析失败）。不触碰 last_ai_call_time。"""
    api_url = _resolve_chat_url(config)
    api_key = config.get('api_key')
    model = config.get('model', 'gpt-3.5-turbo')
    # 打分要稳定可复现，固定低 temperature（不沿用新闻分析的 0.7）
    temperature = 0.3
    max_tokens = config.get('max_tokens', 5000)
    timeout = min(config.get('timeout', BATCH_TIMEOUT_SEC), BATCH_TIMEOUT_SEC)

    user_lines = []
    for code, info in batch:
        user_lines.append({
            'id': code, 'name': info['name'], 'l1': info['l1'], 'l2': info['l2'],
            'cap': int(info['value'] or 0), 'pe': info['pe'],
        })
    # 用 json.dumps 正确转义（股票名可能含引号/特殊字符，手拼 JSON 会让 AI 解析失败）
    user_msg = '请评估以下股票（id 为裸6位代码），严格按指定 JSON 数组输出，每只一条：\n' + json.dumps(user_lines, ensure_ascii=False)

    messages = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': user_msg},
    ]

    last_err = None
    for attempt in range(1, MAX_RETRY_PER_BATCH + 1):
        if _cancel_event.is_set():
            return {}
        try:
            resp = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)
            if resp.status_code == 200:
                content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                parsed = parse_ai_response(content)  # parse_ai_response 按 item 的 'id' 字段键入
                if parsed is not None:
                    # 归一化为裸6位code，确保与前端 extractDigits 查找一致
                    out = {}
                    for k, v in parsed.items():
                        if not isinstance(v, dict):
                            continue
                        bare = _bare_code(k)
                        if bare:
                            out[bare] = v
                    return out
                last_err = 'AI 返回解析失败'
            elif resp.status_code in (429, 503):
                # 智谱：HTTP 429 / body code 1302 = 账户并发达上限；
                #       HTTP 503 / body code 1305 = 平台服务过载。
                # 官方建议：增加重试间隔、避免立即高频重试。→ 指数退避 + 全局冷却。
                body_code = ''
                try:
                    rj = resp.json()
                    err = rj.get('error') if isinstance(rj.get('error'), dict) else rj
                    code = err.get('code') if isinstance(err, dict) else None
                    if code:
                        body_code = f' (code {code})'
                except Exception:
                    pass
                retry_after = resp.headers.get('Retry-After')
                try:
                    ra = int(retry_after) if retry_after else 0
                except Exception:
                    ra = 0
                base = _active_429_cooldown * (2 ** (attempt - 1))   # 30s → 60s → 90s
                wait = min(max(base, ra), RATE_LIMIT_RETRY_CAP)
                last_err = f'API 限流(HTTP {resp.status_code}{body_code})，退避 {wait}s'
                _apply_rate_cooldown(wait)   # 让后续批次也集体放慢
                if attempt < MAX_RETRY_PER_BATCH:
                    _cancelable_sleep(wait)   # 退避期间点"停止"可立即中断
                    continue
            else:
                # 非 200/429/503（如 400/401/403/404/422/500）：带上响应体片段，便于看智谱原始报错
                body_snippet = ''
                try:
                    body_snippet = ' ' + resp.text[:200].replace('\n', ' ')
                except Exception:
                    pass
                last_err = f'HTTP {resp.status_code}{body_snippet}'
                if attempt < MAX_RETRY_PER_BATCH:
                    _cancelable_sleep(5)
                    continue
        except Exception as e:
            last_err = f'异常: {str(e)[:80]}'
            if attempt < MAX_RETRY_PER_BATCH:
                _cancelable_sleep(5)   # 超时/连接错误：稍候重试，不触发限流冷却
                continue
    error_logger.warning(f"[股票打分] 批次失败({len(batch)}只): {last_err}")
    global _last_batch_error
    _last_batch_error = last_err   # 供 runner 写入 status.last_error，前端/脚本可见
    return {}


def _cancelable_sleep(seconds):
    """可被"停止打分"中断的 sleep：用 _cancel_event.wait 替代 time.sleep，
    取消事件被 set 时立刻返回，让停止尽快生效（不用等完整个退避/节流时长）。"""
    if not seconds or seconds <= 0:
        return
    _cancel_event.wait(timeout=seconds)


def _apply_rate_cooldown(seconds):
    """记录一次限流退避：设全局 _rate_cooldown_until，此后所有 dispatch 都等到该时间之后。
    智谱 1302/1305 命中后用此让后续批次集体放慢，避免"立即高频重试"二次触发限流。"""
    global _rate_cooldown_until
    seconds = max(1, min(int(seconds), RATE_LIMIT_RETRY_CAP))
    with _global_rate_lock:
        _rate_cooldown_until = max(_rate_cooldown_until, time.time() + seconds)


def _global_throttle():
    """节流：① 相邻 dispatch 间隔 ≥ _active_batch_interval（平滑、防 TPM 突发）；
    ② 若处于限流冷却期（_rate_cooldown_until 之后），则等到冷却结束。
    智谱按"并发请求数"限流——串行(1并发)本身已不会触发 1302，本函数主要做平滑与限流后退避。"""
    global _last_dispatch_ts
    with _global_rate_lock:
        now = time.time()
        wait_interval = _active_batch_interval - (now - _last_dispatch_ts)
        wait_cooldown = _rate_cooldown_until - now
        wait = max(0.0, wait_interval, wait_cooldown)
        if wait > 0:
            _cancelable_sleep(min(wait, RATE_LIMIT_RETRY_CAP))  # 单次 sleep 上限；点"停止"可立即中断
        _last_dispatch_ts = time.time()


def _score_worker(batch, config, prompt, run_id, counters, counters_lock):
    """线程池单任务：节流 → 调 AI → 合并落盘 → 更新计数。返回本批成功数。"""
    if _cancel_event.is_set():
        return 0
    _global_throttle()
    if _cancel_event.is_set():
        return 0
    results = _call_ai_batch(batch, config, prompt)
    # 补漏：仅当"部分成功"（AI 漏判部分 code）时，把漏掉的单独再问一次。
    # 整批失败（429/超时/解析失败）不补——否则会用相同请求二次触发限流，由 only_failed 重跑补齐。
    returned = set(results.keys())
    requested = {c for c, _ in batch}
    missing = requested - returned
    if results and missing and not _cancel_event.is_set():
        miss_batch = [(c, info) for c, info in batch if c in missing]
        _global_throttle()
        extra = _call_ai_batch(miss_batch, config, prompt)
        results.update(extra)
    # 只保留本批请求的 code——AI 偶尔会臆造/串入非本批的 code，丢弃它们，
    # 否则 added 会 > len(batch) 导致 failed 计数为负。
    results = {c: v for c, v in results.items() if c in requested}
    added = merge_batch_scores(results, run_id)
    with counters_lock:
        counters['done'] += added
        counters['failed'] += (len(requested) - added)
    return added


# ============================== 后台主线程 ==============================
def _run_scoring_background(run_id, scope):
    """后台主线程：切批 → 线程池并发 → 实时更新进度。镜像 _run_ai_analysis_background。
    scope: 'all' 全量 / 'missing' 仅未评分 / 'insufficient' 仅"信息不足"项重评。"""
    try:
        _update_status(status='running', run_id=run_id, step='加载股票清单', progress=1,
                       total=0, done=0, failed=0, started_at=_now_iso(), ended_at=None)
        config = load_ai_config()
        batch_size = int(config.get('score_batch_size') or DEFAULT_BATCH_SIZE)
        max_workers = max(1, int(config.get('score_max_workers') or DEFAULT_MAX_WORKERS))
        prompt = load_stock_score_prompt()
        # 注入本轮节流参数（智谱按并发限流，默认串行 workers=1；批间间隔与 429 退避可配置）
        global _active_batch_interval, _active_429_cooldown
        _active_batch_interval = float(config.get('score_batch_interval') or DEFAULT_BATCH_INTERVAL)
        _active_429_cooldown = int(config.get('score_429_cooldown') or DEFAULT_429_COOLDOWN)

        stocks = _load_stock_list(scope=scope)
        if not stocks:
            _update_status(status='failed', progress=0, step='失败',
                           message='无待评分股票（请先在大盘云图更新行业缓存）')
            return

        total = len(stocks)
        batches = _chunk(stocks, batch_size)
        concurrency = '串行' if max_workers == 1 else f'{max_workers}并发'
        _update_status(step=f'开始打分（{len(batches)}批 × {batch_size}只，{concurrency}，批间隔{_active_batch_interval:g}s）',
                       progress=2, total=total, done=0, failed=0)

        counters = {'done': 0, 'failed': 0}
        counters_lock = threading.Lock()
        executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = [
            executor.submit(_score_worker, b, config, prompt, run_id, counters, counters_lock)
            for b in batches
        ]
        prev_done = 0
        consecutive_fatal = 0
        FATAL_CODES = ('HTTP 400', 'HTTP 401', 'HTTP 403', 'HTTP 404', 'HTTP 422')
        try:
            for fut in as_completed(futures):
                if _cancel_event.is_set():
                    break
                try:
                    fut.result()
                except Exception as e:
                    error_logger.error(f"[股票打分] worker 异常: {e}")
                with counters_lock:
                    done = counters['done']
                    failed = counters['failed']
                batch_added = done - prev_done
                prev_done = done
                progress = 2 + int((done + failed) / total * 96) if total else 100
                last_err = _last_batch_error if failed else ''
                # 致命错误（认证/权限/余额/参数）连续整批失败 → 提前中止，避免空跑几百批
                if batch_added == 0 and any(last_err.startswith(c) for c in FATAL_CODES):
                    consecutive_fatal += 1
                else:
                    consecutive_fatal = 0
                _update_status(done=done, failed=failed, progress=progress, last_error=last_err,
                               step=f'已评分 {done}/{total}' + (f'（失败 {failed}）' if failed else ''))
                if consecutive_fatal >= 5:
                    # 连续 5 批致命失败（如 403 余额耗尽 / 401 key 失效）：再跑也是空跑，中止
                    _cancel_event.set()
                    _update_status(status='failed', progress=progress,
                                   message=f'连续 {consecutive_fatal} 批致命失败（{last_err}），已提前中止。'
                                           f'请检查 AI 配置/余额/key 状态后重试（可 --scope missing 续跑）。')
                    info_logger.error(f"[股票打分] 连续致命失败中止: {last_err}")
                    break
        finally:
            # 取消未开始的任务；等待在飞的完成（协作式停止）
            for f in futures:
                if not f.running() and not f.done():
                    f.cancel()
            executor.shutdown(wait=True)

        with counters_lock:
            done = counters['done']
            failed = counters['failed']
        if _cancel_event.is_set():
            _update_status(status='interrupted', progress=2 + int((done + failed) / total * 96) if total else 0,
                           done=done, failed=failed, step='已停止',
                           message=f'已手动停止：成功 {done} / 未完成 {total - done}')
        else:
            _update_status(status='completed', progress=100, done=done, failed=failed, step='完成',
                           message=f'完成：成功 {done} / 失败 {failed}' + ('（可重新打分仅跑失败项）' if failed else ''))
            info_logger.info(f"[股票打分] run {run_id} 完成: 成功 {done}, 失败 {failed}")
    except Exception as e:
        error_logger.error(f"[股票打分] 后台任务异常: {e}")
        _update_status(status='failed', progress=0, step='失败', message=f'打分失败: {str(e)[:100]}')


# ============================== 对外入口 ==============================
def start_scoring(scope='all'):
    """启动一轮打分。scope: 'all' 全量 / 'missing' 仅未评分 / 'insufficient' 仅"信息不足"重评。
    running 且线程存活 → 拒绝。返回 {success, status, ...}。"""
    global _worker_thread
    if scope not in ('all', 'missing', 'insufficient'):
        scope = 'all'
    config = load_ai_config()
    if not config or not config.get('enabled'):
        return {'success': False, 'message': 'AI 未启用或配置不完整，请先在「AI大模型配置」中设置'}
    if not (config.get('api_url') and config.get('api_key')):
        return {'success': False, 'message': 'AI 配置不完整：缺少 api_url 或 api_key'}

    with _status_lock:
        alive = _worker_thread is not None and _worker_thread.is_alive()
        if _score_status.get('status') == 'running' and alive:
            return {'success': True, 'status': 'running',
                    'message': '打分任务正在执行中，请稍后查询进度',
                    'progress': _score_status.get('progress', 0),
                    'step': _score_status.get('step', '')}
        run_id = _run_id()
        _cancel_event.clear()
        _score_status.update(_default_status())
        _score_status['status'] = 'running'
        _score_status['run_id'] = run_id
        _score_status['message'] = '打分任务已启动'
        _score_status['started_at'] = _now_iso()
        _write_status_atomic(dict(_score_status))
        _worker_thread = threading.Thread(
            target=_run_scoring_background, args=(run_id, scope), daemon=True
        )
        _worker_thread.start()

    # 估算（按 scope 的实际待评数量算；时长取决于 AI 端点单次响应速度）
    total = len(_load_stock_list(scope=scope))
    batch_size = int(config.get('score_batch_size') or DEFAULT_BATCH_SIZE)
    max_workers = max(1, int(config.get('score_max_workers') or DEFAULT_MAX_WORKERS))
    batches = (total + batch_size - 1) // batch_size if total else 0
    scope_cn = {'all': '全量', 'missing': '仅未评分', 'insufficient': '仅信息不足'}[scope]
    return {
        'success': True, 'status': 'running', 'run_id': run_id,
        'message': f'打分任务已启动（{scope_cn}，共{total}只，'
                   + ('串行避免限流）' if max_workers == 1 else f'{max_workers}并发）'),
        'estimate': {
            'total': total, 'batches': batches,
            'batch_size': batch_size, 'workers': max_workers,
            'eta_minutes': '60-180' if max_workers == 1 else '25-60',
            'scope': scope,
        },
    }


def stop_scoring():
    _cancel_event.set()
    # 立刻把状态 step 改成"停止中"，让前端马上看到反馈（状态仍为 running，
    # 直到后台线程把当前在飞的 HTTP 请求做完、真正退出后转 interrupted）。
    try:
        _update_status(step='已请求停止，等待当前批次完成（最长约2分钟）…',
                       message='已请求停止，当前批次完成后退出，已评分结果保留')
    except Exception:
        pass
    return {'success': True, 'message': '已请求停止，当前批次完成后退出（已评分结果保留）'}


def get_scores_payload():
    """供前端云图着色：{success, run_id, scored_at, count, map:{code:{score,label,reason}}, buckets}。"""
    scores = load_scores()
    last_run = None
    last_at = None
    flat = {}
    insufficient = 0
    for code, v in scores.items():
        if isinstance(v, dict):
            flat[code] = {
                'score': v.get('score'),
                'label': v.get('label', ''),
                'reason': v.get('reason', ''),
            }
            if '信息不足' in (v.get('reason') or ''):
                insufficient += 1
            if v.get('run_id'):
                last_run = v.get('run_id')
            if v.get('scored_at') and (last_at is None or v.get('scored_at') > last_at):
                last_at = v.get('scored_at')
    return {
        'success': True,
        'run_id': last_run,
        'scored_at': last_at,
        'count': len(flat),
        'insufficient_count': insufficient,
        'map': flat,
        'buckets': SCORE_BUCKETS,
    }
