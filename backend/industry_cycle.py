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

from config import CONFIG_DIR
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
        user_content = f"请对以下行业进行6信号见顶诊断分析：{industry_name}"
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

    # 尝试从markdown代码块中提取JSON
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
    if json_match:
        content = json_match.group(1)
    else:
        # 尝试直接找JSON对象
        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            content = content[first_brace:last_brace + 1]

    try:
        result = json.loads(content)
        # 验证关键字段
        if 'signals' in result or 'overall_verdict' in result:
            if 'industry' not in result:
                result['industry'] = industry_name
            if 'analyze_time' not in result:
                result['analyze_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
            return result
    except json.JSONDecodeError as e:
        error_logger.error(f"行业周期分析结果JSON解析失败: {e}")

    # 尝试更宽松的解析
    try:
        # 移除注释
        content = re.sub(r'//.*?\n', '', content)
        content = re.sub(r'/\*[\s\S]*?\*/', '', content)
        result = json.loads(content)
        if 'signals' in result or 'overall_verdict' in result:
            if 'industry' not in result:
                result['industry'] = industry_name
            if 'analyze_time' not in result:
                result['analyze_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
            return result
    except:
        pass

    return None


def get_analysis_status():
    """获取当前分析状态"""
    return _load_status()


def get_analysis_result():
    """获取最近一次分析结果"""
    return _load_result()
