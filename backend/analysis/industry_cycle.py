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

from core.config import CONFIG_DIR, INDUSTRY_CYCLE_SCORES_DIR, INDUSTRY_CYCLE_SCORES_FILE, INDUSTRY_CYCLE_BATCH_STATUS_FILE
from analysis.ai_analyzer import load_ai_config, call_ai_api
from analysis.ai_json import parse_with_ai_repair
from data.data_processor import error_logger
from core.logger import get_logger

info_logger = get_logger('ai')

INDUSTRY_CYCLE_RESULT_FILE = os.path.join(CONFIG_DIR, 'industry_cycle_result.json')
INDUSTRY_CYCLE_STATUS_FILE = os.path.join(CONFIG_DIR, 'industry_cycle_status.json')

_analysis_lock = threading.Lock()
_analysis_running = False

# ==================== AI 提示词 ====================
INDUSTRY_CYCLE_PROMPT = """你是一名顶级行业周期分析师，擅长识别行业所处的完整生命周期阶段——既能发现泡沫，也能发现黄金时代。

你需要对用户给出的行业进行"9维产业周期雷达"分析，并与历史经典行业周期做对标。

【重要】用户消息中会包含"当前日期"，你必须以该日期作为"现在"的时间基准来进行分析和周期对标，不要使用你训练数据的截止时间。

【9维产业周期雷达】
1. **渗透率**：行业产品/服务的市场渗透率是否接近天花板（如新能源车渗透率超50%后增速骤降）
2. **产能过剩**：行业内企业是否疯狂扩产导致供大于求（如碳酸锂60万→10万/吨）
3. **利润率**：行业龙头毛利率是否从高位持续下滑（如医药集采后毛利率从80%→30%）
4. **政策风向**：政策是否从扶持转向收紧（如新能源补贴退坡、医药集采）
5. **全民讨论**：是否出现全民讨论、出租车司机荐股、楼下大爷买基金等现象（反向指标！）
6. **龙头表现**：行业龙头是否持续跑输指数（需连续12个月跑输行业指数20%以上并伴随盈利下修才算走弱，短期横盘不算）
7. **行业成长性**：行业未来3-5年需求CAGR预测，成长性越高分数越低（安全）
8. **估值泡沫**：行业龙头PE/PB/PS所处历史百分位，越贵分数越高（危险）
9. **CAPEX周期**：行业资本开支趋势，CAPEX见顶回落是科技行业最领先的见顶信号

【各维度评分方向】
- 渗透率：已到顶=高分，未到顶=低分
- 产能过剩：严重过剩=高分，供不应求=低分
- 利润率：持续下滑=高分，上升/持平=低分
- 政策风向：逆风=高分，强力扶持=低分
- 全民讨论：全民狂热=高分（反向指标），无人问津=低分
- 龙头表现：持续走弱=高分，强势创新高=低分
- 行业成长性：需求CAGR<5%=高分，CAGR>30%=低分
- 估值泡沫：历史百分位>90%=高分，<30%=低分
- CAPEX周期：连续下降=高分，增长50%以上=低分

【"全民讨论"信号方向 - 极其重要】
全民讨论是一个**反向指标**：
- **全民狂热/人人都在讨论** → 说明见顶风险极高（如2021年大妈买新能源基金）→ score应给 80-100
- **部分关注/机构为主** → 中等风险 → score给 30-50
- **无人问津/市场冰点** → 说明已经跌过头或远未泡沫化 → score应给 0-15
绝不能把"无人问津"当作危险信号！无人关注恰恰意味着安全边际高。

【"龙头走弱"定义 - 避免误判】
龙头走弱不能仅凭短期跑输指数判断。成长行业龙头经常横盘一年后再涨数倍（如英伟达2022、茅台2018、宁德2021）。
只有满足以下**全部条件**才算"走弱"：
- 连续12个月以上跑输行业指数20%以上
- 同时伴随盈利预期下修（分析师集体下调EPS）
- 资金持续净流出（机构连续3个季度减仓）
仅凭短期震荡或回调不算走弱。

【"行业成长性"评分标准】
- 未来5年需求CAGR > 30%：0-10分（高速成长，远未见顶）
- 20%-30%：10-25分
- 10%-20%：25-50分
- 5%-10%：50-70分
- 0%-5%：70-85分
- 负增长：85-100分

【"估值泡沫"评分标准】
- PE/PB/PS历史百分位 < 30%：0-15分
- 30%-50%：15-30分
- 50%-70%：30-55分
- 70%-90%：55-80分
- > 90%：80-100分

【"CAPEX周期"评分标准】
- CAPEX同比增长 > 50%：0-15分（行业仍在快速扩张期）
- 增长20%-50%：15-30分
- 持平（±10%）：40-55分
- 下降10%-30%：55-75分
- 连续下降超30%：75-100分

【传统行业处理】
对于银行、保险、地产等传统低估值行业，不要套用成长行业的泡沫分析框架。这些行业通常：
- 渗透率早已见顶但周期属性明显，应结合周期位置而非成长天花板打分
- 如果行业处于估值底部、政策转向宽松期，overall_score应偏低（<40）
- 如果行业处于估值高位、政策收紧期，overall_score才应偏高
- 传统行业成长性评分应结合周期复苏预期，不能简单按CAGR给高分

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
  "overall_verdict": "主升浪中期",
  "overall_score": 35,
  "signals": [
    {
      "name": "渗透率",
      "status": "未到顶",
      "score": 20,
      "detail": "该行业当前渗透率约XX%，离天花板还有较大空间"
    },
    {
      "name": "产能过剩",
      "status": "无过剩",
      "score": 15,
      "detail": "产能利用率XX%，供需紧平衡"
    },
    {
      "name": "利润率",
      "status": "上升",
      "score": 10,
      "detail": "龙头毛利率创新高，行业盈利趋势向上"
    },
    {
      "name": "政策风向",
      "status": "强力扶持",
      "score": 10,
      "detail": "政策顺风，各国大力扶持"
    },
    {
      "name": "全民讨论",
      "status": "无人问津",
      "score": 15,
      "detail": "市场关注度低，远未到全民狂热"
    },
    {
      "name": "龙头表现",
      "status": "强势",
      "score": 15,
      "detail": "龙头股创新高，未出现连续12个月跑输"
    },
    {
      "name": "行业成长性",
      "status": "高速成长",
      "score": 10,
      "detail": "未来5年CAGR约XX%，处于高速增长期"
    },
    {
      "name": "估值泡沫",
      "status": "合理偏低",
      "score": 20,
      "detail": "行业龙头PE处于历史XX%分位，估值合理"
    },
    {
      "name": "CAPEX周期",
      "status": "扩张期",
      "score": 15,
      "detail": "行业CAPEX同比增长XX%，仍处于扩张阶段"
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
    "如果未来出现：XXX——其中满足2条，则行业可能进入下一阶段"
  ],
  "summary": "综合9维雷达，该行业目前处于XXX阶段。"
}
```

【评分规则】
- 每个维度 score 范围 0-100，0=完全没见顶风险，100=已明确见顶
- overall_score = 9个维度score的加权平均：
  渗透率15% + 产能15% + 利润率10% + 政策10% + 全民讨论15% + 龙头表现10% + 行业成长性10% + 估值泡沫10% + CAPEX周期5%
- overall_score < 30: 启动期/主升浪早期
- 30-50: 主升浪中后期
- 50-70: 泡沫期
- > 70: 见顶/崩盘期

【分数语义】
- overall_score < 50：行业处于安全期（启动期/主升浪），尚未见顶
- overall_score ≥ 50：行业进入危险期（泡沫期/崩盘期），见顶风险较高
- 分数越高代表见顶风险越大，请务必基于真实数据给出有区分度的评分

【评分校准 - 避免偏见】
你必须避免"所有行业都危险"的偏见。请严格遵守以下校准：
- 一个行业中，如果超过一半的维度score < 50，则overall_score必须 < 50
- 只有当至少5个维度score ≥ 50时，overall_score才应 ≥ 50
- 如果行业刚经历深度出清（产能出清80%+、估值历史低位、资金冰点），即使渗透率已高，overall_score也应偏低（<35），因为最坏的时刻已过
- 成熟行业 ≠ 见顶行业！渗透率早已见顶但成长性依然良好的行业（如互联网、消费、半导体），不应仅因渗透率高就给高分
- overall_verdict 不要加"总体判断："前缀，直接写阶段名称，如"主升浪中期"、"泡沫末期"、"崩盘期/出清阶段"

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
            parsed = _parse_industry_result(
                content, industry_name,
                call_fn=_make_ai_caller(api_url, api_key, model, temperature, max_tokens, timeout))

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


def _make_ai_caller(api_url, api_key, model, temperature, max_tokens, timeout):
    """构造 call_ai_fn(messages)->content 适配器，供 _parse_industry_result 的 AI 自修复重试用。"""
    def _call(messages):
        try:
            r = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)
        except Exception:
            return None
        if r is None or getattr(r, 'status_code', 0) != 200:
            return None
        try:
            return r.json().get('choices', [{}])[0].get('message', {}).get('content', '')
        except Exception:
            return None
    return _call


def _parse_industry_result(content, industry_name, call_fn=None):
    """解析 AI 返回的行业周期 JSON 结果（两轮容错）。

    先本地容错解析（未转义引号/尾逗号/围栏/散文括号/注释）；本地失败且传了 call_fn 时，
    回喂 AI 修正一次再解析（Tier2）。提取不到含 signals/overall_verdict 的对象则返回 None。
    """
    obj = parse_with_ai_repair(content, call_fn, prefer='object', logger=info_logger)
    if isinstance(obj, dict) and ('signals' in obj or 'overall_verdict' in obj):
        if 'industry' not in obj:
            obj['industry'] = industry_name
        obj['analyze_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
        return obj
    info_logger.warning("JSON解析失败：未能从AI返回中提取行业周期结果")
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
        failed_list = []

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
                    parsed = _parse_industry_result(
                content, industry_name,
                call_fn=_make_ai_caller(api_url, api_key, model, temperature, max_tokens, timeout))

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
                        failed_list.append(industry_name)
                else:
                    failed += 1
                    failed_list.append(industry_name)
                    error_logger.error(f"批量诊断 {industry_name} AI调用失败: HTTP {response.status_code}")

            except Exception as e:
                failed += 1
                failed_list.append(industry_name)
                error_logger.error(f"批量诊断 {industry_name} 异常: {e}")

            # 批间间隔2秒，避免触发限流
            if i < total - 1:
                _batch_cancel.wait(timeout=2.0)

        _save_batch_status({
            'status': 'completed',
            'total': total, 'done': done, 'failed': failed,
            'failed_industries': failed_list,
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
