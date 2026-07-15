"""行业见顶周期分析引擎

用 AI 对指定行业做"6信号见顶诊断"，并与新能源/医药/白酒历史周期做对标，
返回结构化 JSON 供前端渲染对比表格。

6 信号：
1. 渗透率是否见顶
2. 产能是否过剩
3. 利润率是否下滑
4. 政策是否逆风
5. 全民讨论程度
6. 龙头是否走弱

数据流：
  用户输入行业名 → AI(chat/completions) → JSON → config/industry_cycle_result.json
"""
import os
import json
import time
import threading
import traceback

from config import CONFIG_DIR, INDUSTRY_CYCLE_SCORES_DIR, INDUSTRY_CYCLE_SCORES_FILE, INDUSTRY_CYCLE_BATCH_STATUS_FILE
from ai_analyzer import load_ai_config, call_ai_api
from data_processor import error_logger
from logger import get_logger

info_logger = get_logger('ai')

INDUSTRY_CYCLE_RESULT_FILE = os.path.join(CONFIG_DIR, 'industry_cycle_result.json')
INDUSTRY_CYCLE_STATUS_FILE = os.path.join(CONFIG_DIR, 'industry_cycle_status.json')

_analysis_lock = threading.Lock()
_analysis_running = False

# ==================== AI 提示词 ====================
INDUSTRY_CYCLE_PROMPT = """你是一名顶级行业周期分析师，擅长判断一个行业是否处于见顶阶段。

你需要对用户给出的行业进行"6信号见顶诊断"，并与历史经典见顶行业（新能源、医药、白酒）做周期对标。

【重要】用户消息中会包含"当前日期"，你必须以该日期作为"现在"的时间基准来进行分析和周期对标，不要使用你训练数据的截止时间。

【6大见顶信号】
1. **渗透率是否见顶**：行业产品/服务的市场渗透率是否接近天花板（如新能源车渗透率超50%后增速骤降）
2. **产能是否过剩**：行业内企业是否疯狂扩产导致供大于求（如碳酸锂60万→10万/吨）
3. **利润率是否下滑**：行业龙头毛利率是否从高位持续下滑（如医药集采后毛利率从80%→30%）
4. **政策是否逆风**：政策是否从扶持转向收紧（如新能源补贴退坡、医药集采）
5. **全民讨论程度**：是否出现全民讨论、出租车司机荐股、楼下大爷买基金等现象
6. **龙头是否走弱**：行业龙头是否开始跑输指数或提前崩盘（如2021年宁德时代跑输创业板）

【历史参考周期】
- **新能源**：2019(启动期)→2020(主升浪)→2021(泡沫期)→2022(崩盘期)
- **医药**：2019(启动期)→2020(主升浪)→2021(泡沫期)→2022(崩盘期)
- **白酒**：2017(启动期)→2019(主升浪)→2020(泡沫期)→2021(崩盘期)

【输出格式要求 - 严格JSON】
你必须且只能返回如下JSON结构，不要输出任何其他文字：

```json
{
  "industry": "行业名称",
  "analyze_time": "分析时间",
  "overall_verdict": "总体判断：X期/主升浪中期/泡沫末期等",
  "overall_score": 75,
  "signals": [
    {
      "name": "渗透率",
      "status": "未到顶/接近顶部/已到顶",
      "score": 20,
      "detail": "该行业当前渗透率约XX%，离天花板还有较大空间，类似2019年新能源渗透率10-15%阶段"
    },
    {
      "name": "产能过剩",
      "status": "无过剩/部分过剩/严重过剩",
      "score": 30,
      "detail": "目前GPU/HBM仍供不应求，但CPO方向已有扩产苗头"
    },
    {
      "name": "利润率",
      "status": "上升/持平/下滑",
      "score": 15,
      "detail": "英伟达、海力士利润率创新高，未见下滑迹象"
    },
    {
      "name": "政策风向",
      "status": "强力扶持/中性/逆风",
      "score": 10,
      "detail": "全球各国都在大力扶持AI产业，政策顺风"
    },
    {
      "name": "全民讨论",
      "status": "无人问津/部分关注/全民狂热",
      "score": 40,
      "detail": "有一定讨论热度，但远未到全民买基金的程度"
    },
    {
      "name": "龙头走弱",
      "status": "强势/震荡/走弱",
      "score": 25,
      "detail": "英伟达、台积电创新高，龙头未见走弱信号"
    }
  ],
  "cycle_comparison": {
    "reference_industry": "新能源",
    "current_phase": "主升浪中期",
    "equivalent_year": "2020",
    "phases": [
      {"phase": "启动期", "new_energy": "2019", "target_industry": "2024"},
      {"phase": "主升浪", "new_energy": "2020-2021H1", "target_industry": "2025-2026?"},
      {"phase": "泡沫期", "new_energy": "2021H2", "target_industry": "？"},
      {"phase": "崩盘期", "new_energy": "2022", "target_industry": "？"}
    ]
  },
  "warnings": [
    "如果未来出现：英伟达连续几个季度资本开支放缓、HBM价格大跌、长电等全面扩产导致利润率下滑、OpenAI上市后全民疯狂追捧——其中满足3条，则AI主线可能进入尾声"
  ],
  "summary": "综合6大信号，该行业目前更类似2020年的新能源，处于主升浪中后期而非泡沫末期。尚未出现2021年医药、2022年新能源那种明确的顶部信号。"
}
```

【评分规则】
- 每个信号 score 范围 0-100，0=完全没见顶风险，100=已明确见顶
- overall_score = 6个信号score的加权平均（渗透率25% + 产能20% + 利润率20% + 政策15% + 全民讨论10% + 龙头走弱10%）
- overall_score < 30: 启动期/主升浪早期
- 30-50: 主升浪中后期
- 50-70: 泡沫期
- > 70: 见顶/崩盘期

【分数语义】
- overall_score < 50：行业处于安全期（启动期/主升浪），尚未见顶
- overall_score ≥ 50：行业进入危险期（泡沫期/崩盘期），见顶风险较高
- 分数越高代表见顶风险越大，请务必基于真实数据给出有区分度的评分

请务必基于真实数据和事实进行分析，不要编造数据。如果某些数据不确定，请在detail中说明。
"""


def _load_status():
    """加载分析状态"""
    try:
        if os.path.exists(INDUSTRY_CYCLE_STATUS_FILE):
            with open(INDUSTRY_CYCLE_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        error_logger.error(f"加载行业周期分析状态失败: {e}")
    return {'status': 'idle'}


def _save_status(status_data):
    """保存分析状态"""
    try:
        with open(INDUSTRY_CYCLE_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存行业周期分析状态失败: {e}")


def _load_result():
    """加载分析结果"""
    try:
        if os.path.exists(INDUSTRY_CYCLE_RESULT_FILE):
            with open(INDUSTRY_CYCLE_RESULT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        error_logger.error(f"加载行业周期分析结果失败: {e}")
    return None


def _save_result(result_data):
    """保存分析结果"""
    try:
        with open(INDUSTRY_CYCLE_RESULT_FILE, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存行业周期分析结果失败: {e}")


def start_industry_analysis(industry_name):
    """启动行业见顶分析（异步后台线程）"""
    global _analysis_running

    with _analysis_lock:
        if _analysis_running:
            return {'success': False, 'message': '已有分析任务在运行中'}

        _analysis_running = True

    # 保存初始状态
    _save_status({
        'status': 'running',
        'industry': industry_name,
        'progress': 0,
        'step': '正在调用AI分析...',
        'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
    })

    # 启动后台线程
    thread = threading.Thread(target=_run_analysis, args=(industry_name,), daemon=True)
    thread.start()

    return {'success': True, 'status': 'running', 'industry': industry_name, 'message': '分析任务已启动'}


def _run_analysis(industry_name):
    """后台线程：执行AI分析"""
    global _analysis_running

    try:
        _save_status({
            'status': 'running',
            'industry': industry_name,
            'progress': 20,
            'step': '正在加载AI配置...',
            'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
        })

        config = load_ai_config()
        if not config or not config.get('enabled'):
            _save_status({
                'status': 'failed',
                'industry': industry_name,
                'progress': 0,
                'step': 'AI未启用或配置不完整',
                'error': '请在AI配置中启用并填写API信息'
            })
            return

        api_url = config.get('api_url')
        api_key = config.get('api_key')
        model = config.get('model', 'gpt-3.5-turbo')
        temperature = config.get('temperature', 0.7)
        max_tokens = config.get('max_tokens', 4000)
        timeout = min(config.get('timeout', 180), 300)

        if not api_url or not api_key:
            _save_status({
                'status': 'failed',
                'industry': industry_name,
                'progress': 0,
                'step': 'AI配置不完整',
                'error': '缺少api_url或api_key'
            })
            return

        full_url = config.get('full_url', False)
        if not full_url and not api_url.endswith('/chat/completions'):
            api_url = api_url.rstrip('/') + '/chat/completions'

        _save_status({
            'status': 'running',
            'industry': industry_name,
            'progress': 40,
            'step': 'AI正在深度分析行业周期...',
            'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
        })

        # 构建消息
        current_time = time.strftime('%Y年%m月%d日')
        user_content = f"当前日期：{current_time}\n\n请对以下行业进行6信号见顶诊断分析：{industry_name}"
        messages = [
            {"role": "system", "content": INDUSTRY_CYCLE_PROMPT},
            {"role": "user", "content": user_content}
        ]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # 调用AI
        response = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)

        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')

            _save_status({
                'status': 'running',
                'industry': industry_name,
                'progress': 80,
                'step': '正在解析AI返回结果...',
                'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
            })

            # 解析JSON
            parsed = _parse_industry_result(content, industry_name)

            if parsed:
                _save_result(parsed)
                _save_status({
                    'status': 'completed',
                    'industry': industry_name,
                    'progress': 100,
                    'step': '分析完成',
                    'start_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'complete_time': time.strftime('%Y-%m-%d %H:%M:%S')
                })
                info_logger.info(f"行业周期分析完成: {industry_name}")
            else:
                # 解析失败，保存原始内容
                _save_result({
                    'industry': industry_name,
                    'analyze_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'raw_content': content,
                    'parse_error': True
                })
                _save_status({
                    'status': 'completed',
                    'industry': industry_name,
                    'progress': 100,
                    'step': '分析完成（结果解析部分失败，已保存原始内容）',
                    'start_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'complete_time': time.strftime('%Y-%m-%d %H:%M:%S')
                })
        else:
            error_msg = f'HTTP {response.status_code}'
            try:
                error_data = response.json()
                if isinstance(error_data.get('error'), dict):
                    error_msg = error_data['error'].get('message', error_msg)
            except:
                error_msg = response.text[:200] if response.text else error_msg

            _save_status({
                'status': 'failed',
                'industry': industry_name,
                'progress': 0,
                'step': 'AI调用失败',
                'error': error_msg,
                'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
            })
            error_logger.error(f"行业周期分析AI调用失败: {error_msg}")

    except Exception as e:
        error_logger.error(f"行业周期分析异常: {e}\n{traceback.format_exc()}")
        _save_status({
            'status': 'failed',
            'industry': industry_name,
            'progress': 0,
            'step': '分析异常',
            'error': str(e)[:200],
            'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
        })
    finally:
        with _analysis_lock:
            _analysis_running = False


def _parse_industry_result(content, industry_name):
    """解析AI返回的JSON结果"""
    import re

    # 第1步：尝试从markdown代码块中提取JSON（贪婪匹配，确保拿到完整内容）
    json_match = re.search(r'```(?:json)?\s*([\s\S]*)\s*```', content)
    extracted = None
    if json_match:
        extracted = json_match.group(1).strip()

    # 第2步：如果代码块提取失败或解析失败，尝试从全文找最外层的JSON对象
    # 用括号匹配法找到最外层完整 { ... }
    def extract_json_object(text):
        first_brace = text.find('{')
        if first_brace == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i in range(first_brace, len(text)):
            c = text[i]
            if escape_next:
                escape_next = False
                continue
            if c == '\\':
                escape_next = True
                continue
            if c == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[first_brace:i + 1]
        # 没找到匹配的闭合括号，返回从第一个 { 到末尾
        return text[first_brace:]

    def try_parse(text):
        """尝试解析并验证JSON"""
        try:
            result = json.loads(text)
            if isinstance(result, dict) and ('signals' in result or 'overall_verdict' in result):
                if 'industry' not in result:
                    result['industry'] = industry_name
                # 用服务器当前时间覆盖 analyze_time，确保时间正确
                result['analyze_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # 尝试1：从代码块中提取
    if extracted:
        result = try_parse(extracted)
        if result:
            return result
        # 代码块内容可能不是完整JSON，尝试从中提取JSON对象
        json_obj = extract_json_object(extracted)
        if json_obj:
            result = try_parse(json_obj)
            if result:
                return result

    # 尝试2：从全文提取JSON对象
    json_obj = extract_json_object(content)
    if json_obj:
        result = try_parse(json_obj)
        if result:
            return result

    # 尝试3：移除注释后重试
    cleaned = content
    cleaned = re.sub(r'//.*?\n', '\n', cleaned)
    cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
    json_obj = extract_json_object(cleaned)
    if json_obj:
        result = try_parse(json_obj)
        if result:
            return result

    # 尝试4：移除尾随逗号（AI常见错误）
    def fix_trailing_commas(text):
        # 移除数组/对象中 ] 或 } 前的逗号
        text = re.sub(r',\s*([}\]])', r'\1', text)
        return text

    for source_text in [content, extracted, json_obj]:
        if not source_text:
            continue
        fixed = fix_trailing_commas(source_text)
        json_obj_fixed = extract_json_object(fixed)
        if json_obj_fixed:
            result = try_parse(json_obj_fixed)
            if result:
                return result

    return None


def get_analysis_status():
    """获取当前分析状态"""
    return _load_status()


def get_analysis_result():
    """获取最近一次分析结果"""
    return _load_result()


# ==================== 批量诊断功能 ====================

_batch_lock = threading.Lock()
_batch_running = False
_batch_cancel = threading.Event()


def _load_cycle_scores():
    """加载所有行业的周期诊断结果"""
    try:
        if os.path.exists(INDUSTRY_CYCLE_SCORES_FILE):
            with open(INDUSTRY_CYCLE_SCORES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        error_logger.error(f"加载行业周期诊断结果失败: {e}")
    return {}


def _save_cycle_scores(scores):
    """保存所有行业的周期诊断结果（原子写入）"""
    try:
        os.makedirs(INDUSTRY_CYCLE_SCORES_DIR, exist_ok=True)
        tmp = INDUSTRY_CYCLE_SCORES_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
        # Windows 安全替换
        try:
            os.replace(tmp, INDUSTRY_CYCLE_SCORES_FILE)
        except (PermissionError, OSError):
            with open(tmp, 'r', encoding='utf-8') as src, open(INDUSTRY_CYCLE_SCORES_FILE, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception as e:
        error_logger.error(f"保存行业周期诊断结果失败: {e}")


def _merge_cycle_score(industry_name, result):
    """合并单个行业的诊断结果到持久存储"""
    scores = _load_cycle_scores()
    scores[industry_name] = {
        'overall_score': result.get('overall_score', 0),
        'overall_verdict': result.get('overall_verdict', ''),
        'signals': result.get('signals', []),
        'cycle_comparison': result.get('cycle_comparison'),
        'warnings': result.get('warnings', []),
        'summary': result.get('summary', ''),
        'analyze_time': result.get('analyze_time', time.strftime('%Y-%m-%d %H:%M:%S')),
        'analyzed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    _save_cycle_scores(scores)


def _clear_cycle_scores():
    """清空所有行业周期诊断结果"""
    _save_cycle_scores({})


def _load_batch_status():
    try:
        if os.path.exists(INDUSTRY_CYCLE_BATCH_STATUS_FILE):
            with open(INDUSTRY_CYCLE_BATCH_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'status': 'idle'}


def _save_batch_status(status_data):
    try:
        os.makedirs(INDUSTRY_CYCLE_SCORES_DIR, exist_ok=True)
        tmp = INDUSTRY_CYCLE_BATCH_STATUS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, INDUSTRY_CYCLE_BATCH_STATUS_FILE)
        except (PermissionError, OSError):
            with open(tmp, 'r', encoding='utf-8') as src, open(INDUSTRY_CYCLE_BATCH_STATUS_FILE, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception as e:
        error_logger.error(f"保存行业周期批量诊断状态失败: {e}")


def start_batch_analysis(industries):
    """启动批量行业见顶分析（异步后台线程）
    industries: 行业名称列表，如 ['消费电子', '半导体', '白酒', ...]
    """
    global _batch_running

    with _batch_lock:
        if _batch_running:
            return {'success': False, 'message': '已有批量分析任务在运行中'}

        _batch_running = True
        _batch_cancel.clear()

    # 先清空旧的诊断结果
    _clear_cycle_scores()

    _save_batch_status({
        'status': 'running',
        'total': len(industries),
        'done': 0,
        'failed': 0,
        'current': '',
        'progress': 0,
        'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
    })

    thread = threading.Thread(target=_run_batch_analysis, args=(industries,), daemon=True)
    thread.start()

    return {'success': True, 'status': 'running', 'total': len(industries), 'message': f'批量分析已启动，共{len(industries)}个行业'}


def _run_batch_analysis(industries):
    """后台线程：逐个行业调用AI分析"""
    global _batch_running

    try:
        config = load_ai_config()
        if not config or not config.get('enabled'):
            _save_batch_status({'status': 'failed', 'message': 'AI未启用或配置不完整', 'total': len(industries), 'done': 0, 'failed': 0})
            return

        api_url = config.get('api_url')
        api_key = config.get('api_key')
        model = config.get('model', 'gpt-3.5-turbo')
        temperature = config.get('temperature', 0.7)
        max_tokens = config.get('max_tokens', 4000)
        timeout = min(config.get('timeout', 180), 300)

        if not api_url or not api_key:
            _save_batch_status({'status': 'failed', 'message': 'AI配置不完整', 'total': len(industries), 'done': 0, 'failed': 0})
            return

        full_url = config.get('full_url', False)
        if not full_url and not api_url.endswith('/chat/completions'):
            api_url = api_url.rstrip('/') + '/chat/completions'

        done = 0
        failed = 0
        total = len(industries)

        for i, industry_name in enumerate(industries):
            if _batch_cancel.is_set():
                _save_batch_status({
                    'status': 'interrupted',
                    'total': total, 'done': done, 'failed': failed,
                    'current': industry_name,
                    'progress': int(done / total * 100) if total else 0,
                    'message': f'已手动停止：完成 {done}/{total}'
                })
                return

            _save_batch_status({
                'status': 'running',
                'total': total, 'done': done, 'failed': failed,
                'current': industry_name,
                'progress': int((i) / total * 100) if total else 0,
                'step': f'正在分析：{industry_name}（{i+1}/{total}）'
            })

            try:
                # 构建消息（与单行业相同逻辑）
                current_time = time.strftime('%Y年%m月%d日')
                user_content = f"当前日期：{current_time}\n\n请对以下行业进行6信号见顶诊断分析：{industry_name}"
                messages = [
                    {"role": "system", "content": INDUSTRY_CYCLE_PROMPT},
                    {"role": "user", "content": user_content}
                ]

                response = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)

                if response.status_code == 200:
                    content = response.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                    parsed = _parse_industry_result(content, industry_name)

                    if parsed:
                        # 合并到持久存储
                        _merge_cycle_score(industry_name, parsed)
                        done += 1
                    else:
                        # 解析失败，也保存原始内容
                        _merge_cycle_score(industry_name, {
                            'overall_score': 0,
                            'overall_verdict': '分析失败',
                            'signals': [],
                            'analyze_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                            'raw_content': content,
                            'parse_error': True
                        })
                        failed += 1
                else:
                    failed += 1
                    error_logger.error(f"批量诊断 {industry_name} AI调用失败: HTTP {response.status_code}")

            except Exception as e:
                failed += 1
                error_logger.error(f"批量诊断 {industry_name} 异常: {e}")

            # 批间间隔2秒，避免触发限流
            if i < total - 1:
                _batch_cancel.wait(timeout=2.0)

        _save_batch_status({
            'status': 'completed',
            'total': total, 'done': done, 'failed': failed,
            'current': '',
            'progress': 100,
            'message': f'批量诊断完成：成功 {done}，失败 {failed}',
            'complete_time': time.strftime('%Y-%m-%d %H:%M:%S')
        })
        info_logger.info(f"行业周期批量诊断完成: 成功 {done}, 失败 {failed}")

    except Exception as e:
        error_logger.error(f"行业周期批量诊断异常: {e}\n{traceback.format_exc()}")
        _save_batch_status({
            'status': 'failed',
            'message': f'批量诊断异常: {str(e)[:200]}',
            'total': len(industries), 'done': 0, 'failed': 0
        })
    finally:
        with _batch_lock:
            _batch_running = False


def stop_batch_analysis():
    """停止批量分析"""
    _batch_cancel.set()
    return {'success': True, 'message': '已请求停止批量分析'}


def get_batch_status():
    """获取批量分析状态"""
    with _batch_lock:
        if _batch_running:
            return _load_batch_status()
    status = _load_batch_status()
    # 如果状态文件显示running但线程已死，修正为interrupted
    if status.get('status') == 'running':
        status['status'] = 'interrupted'
        status['message'] = status.get('message') or '上次批量分析未完成'
    return status


def get_all_cycle_scores():
    """获取所有行业的周期诊断结果（供大盘云图着色使用）"""
    scores = _load_cycle_scores()
    return {
        'success': True,
        'count': len(scores),
        'industries': list(scores.keys()),
        'scores': scores,
        'analyzed_at': max((v.get('analyzed_at', '') for v in scores.values()), default='')
    }


def get_single_cycle_score(industry_name):
    """获取单个行业的周期诊断结果"""
    scores = _load_cycle_scores()
    result = scores.get(industry_name)
    if result:
        return {'success': True, 'data': result, 'industry': industry_name}
    return {'success': False, 'message': f'未找到行业"{industry_name}"的诊断结果'}
