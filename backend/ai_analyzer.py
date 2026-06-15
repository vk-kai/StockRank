import json
import requests
import time
import re
import threading
from config import AI_CONFIG_FILE, AI_PROMPT_FILE, AI_DAILY_PROMPT_FILE
from logger import get_logger

error_logger = get_logger('error')
info_logger = get_logger('ai')

last_ai_call_time = 0
AI_CALL_INTERVAL = 20
_heartbeat_callback = None

def set_heartbeat_callback(callback):
    global _heartbeat_callback
    _heartbeat_callback = callback

def clean_text(text):
    if not text:
        return ""
    
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    text = text.replace('\t', ' ')
    
    text = re.sub(r'<[^>]+>', '', text)
    
    text = re.sub(r'\s+', ' ', text)
    
    text = text.strip()
    
    return text

def truncate_text(text, max_length=1000):
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length] + "..."

def load_ai_config():
    try:
        with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error_logger.error(f"加载AI配置失败: {e}")
        return None

def load_ai_prompt():
    try:
        with open(AI_PROMPT_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        error_logger.error(f"加载AI提示词失败: {e}")
        return None

def call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages):
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
    
    try:
        return requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=timeout
        )
    except Exception as e:
        raise

def parse_ai_response(content):
    try:
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            content = json_match.group(1)
        
        first_bracket = content.find('[')
        last_bracket = content.rfind(']')
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            content = content[first_bracket:last_bracket + 1]
        else:
            first_brace = content.find('{')
            last_brace = content.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                content = '[' + content[first_brace:last_brace + 1] + ']'
        
        analysis_list = json.loads(content)
        
        results = {}
        for item in analysis_list:
            item_id = item.get('id', '')
            if item_id:
                results[item_id] = item
        
        return results
    except json.JSONDecodeError as e:
        return None

def batch_analyze_news(news_items):
    global last_ai_call_time
    
    if not news_items:
        return {}
    
    config = load_ai_config()
    
    if not config or not config.get('enabled'):
        return {}
    
    elapsed = time.time() - last_ai_call_time
    if elapsed < AI_CALL_INTERVAL:
        time.sleep(AI_CALL_INTERVAL - elapsed)
    
    last_ai_call_time = time.time()
    
    prompt = load_ai_prompt()
    if not prompt:
        return {}
    
    api_url = config.get('api_url')
    api_key = config.get('api_key')
    model = config.get('model', 'gpt-3.5-turbo')
    temperature = config.get('temperature', 0.7)
    max_tokens = config.get('max_tokens', 2000)
    timeout = min(config.get('timeout', 60), 60)
    retry_count = config.get('retry_count', 3)
    retry_interval = min(config.get('retry_interval', 10), 10)
    
    if not api_url or not api_key:
        error_logger.error("AI配置不完整：缺少api_url或api_key")
        return {}
    
    full_url = config.get('full_url', False)
    if not full_url and not api_url.endswith('/chat/completions'):
        api_url = api_url.rstrip('/') + '/chat/completions'
    
    news_texts = []
    for item in news_items:
        news_id = item.get('id', '')
        title = clean_text(item.get('title', ''))
        content = clean_text(item.get('content', ''))
        
        title = truncate_text(title, 200)
        content = truncate_text(content, 800)
        
        news_texts.append(f"[id:{news_id}]\n标题：{title}\n内容：{content}")
    
    combined_text = "\n\n---\n\n".join(news_texts)
    
    if len(combined_text) > 8000:
        combined_text = combined_text[:8000] + "\n\n[内容过长，已截断...]"
    
    batch_prompt = prompt + "\n\n注意：本次输入包含多条新闻，每条新闻以[id:xxx]开头标识。请返回一个JSON数组，每个元素包含id字段和对应的分析结果，格式如下：\n[\n  {\"id\": \"新闻id\", \"level\": \"重大/一般\", \"impact_type\": \"即时影响/延迟影响\", \"event_type\": \"新闻/行情异动\", \"core_event\": \"一句话总结\", \"reason\": \"对A股的影响逻辑\", \"impact_market\": \"A股/美股/全球\", \"related_sector\": [\"板块1\",\"板块2\"], \"action_suggestion\": \"立即推送/忽略\"},\n  ...\n]\n只输出JSON数组，不要解释。"
    
    messages = [
        {"role": "system", "content": batch_prompt},
        {"role": "user", "content": combined_text}
    ]
    
    failure_reasons = []
    last_response_content = None
    
    for attempt in range(1, retry_count + 1):
        try:
            if _heartbeat_callback:
                _heartbeat_callback()
            
            response = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                last_response_content = content
                
                results = parse_ai_response(content)
                if results is not None:
                    missing_ids = []
                    for item in news_items:
                        if item.get('id') not in results:
                            missing_ids.append(item.get('id'))
                    if missing_ids:
                        info_logger.warning(f"AI返回结果缺少以下新闻ID: {missing_ids}")
                    info_logger.info(f"AI分析成功，处理 {len(results)}/{len(news_items)} 条新闻")
                    return results
                
                failure_reasons.append(f"第{attempt}次: AI返回解析失败")
                if attempt < retry_count:
                    time.sleep(retry_interval)
                    continue
                return {}
            
            elif response.status_code == 429:
                retry_after = response.headers.get('Retry-After', str(retry_interval))
                try:
                    wait_time = int(retry_after)
                except:
                    wait_time = retry_interval
                failure_reasons.append(f"第{attempt}次: API速率限制(429)，等待{wait_time}秒")
                if attempt < retry_count:
                    time.sleep(wait_time)
                    continue
                return {}
            
            else:
                failure_reasons.append(f"第{attempt}次: HTTP {response.status_code} - {response.text[:200]}")
                if response.status_code == 422:
                    failure_reasons[-1] += f" | 422错误详情 - 新闻数量: {len(news_items)}, 消息长度: {len(combined_text)}"
                if response.status_code == 524:
                    failure_reasons[-1] += " | 524超时错误 - AI API响应时间过长"
                if attempt < retry_count:
                    time.sleep(retry_interval)
                    continue
                return {}
                
        except requests.exceptions.Timeout:
            failure_reasons.append(f"第{attempt}次: 请求超时(timeout={timeout}秒)，新闻数量: {len(news_items)}")
            if attempt < retry_count:
                time.sleep(retry_interval)
                continue
            return {}
            
        except requests.exceptions.ConnectionError as e:
            failure_reasons.append(f"第{attempt}次: 连接失败 - {str(e)}")
            if attempt < retry_count:
                time.sleep(retry_interval)
                continue
            return {}
            
        except Exception as e:
            failure_reasons.append(f"第{attempt}次: 异常 - {str(e)}")
            if attempt < retry_count:
                time.sleep(retry_interval)
                continue
            return {}
    
    error_logger.error(f"AI分析失败，共重试{retry_count}次，失败原因:\n" + "\n".join(failure_reasons))
    if last_response_content:
        error_logger.error(f"AI返回内容(前500字符): {last_response_content[:500]}")
    
    info_logger.error(f"AI分析失败，处理 {len(news_items)} 条新闻，失败原因: {failure_reasons[-1] if failure_reasons else '未知'}")
    
    return {}

def is_important_news(analysis_result):
    if not analysis_result:
        return False
    
    level = analysis_result.get('level', '')
    action_suggestion = analysis_result.get('action_suggestion', '')
    
    return level == '重大' or action_suggestion == '立即推送'

def load_ai_daily_prompt():
    try:
        with open(AI_DAILY_PROMPT_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        error_logger.error(f"加载首页AI分析提示词失败: {e}")
        return None

def analyze_daily_flow(minute_data, top_sectors, market_summary=None):
    """分析全天资金流向走势"""
    global last_ai_call_time
    
    info_logger.info("开始AI全天走势分析...")
    
    config = load_ai_config()
    
    if not config or not config.get('enabled'):
        info_logger.info("AI分析未启用")
        return {'success': False, 'message': 'AI分析未启用'}
    
    elapsed = time.time() - last_ai_call_time
    if elapsed < AI_CALL_INTERVAL:
        time.sleep(AI_CALL_INTERVAL - elapsed)
    
    last_ai_call_time = time.time()
    
    prompt = load_ai_daily_prompt()
    if not prompt:
        prompt = """你是一个专业的A股资金流向分析师。

请根据以下全天板块资金流入数据和走势图数据，分析今日市场的资金流向特征、热点板块、市场情绪和潜在机会。

请从以下几个方面进行分析：
1. 整体市场资金流向趋势（流入/流出整体情况）
2. 热点板块分析（资金流入最多的板块及原因推测）
3. 资金流出板块分析（资金流出最多的板块及原因推测）
4. 盘中资金流向变化特点（早盘、午盘、尾盘的资金流向变化）
5. 市场情绪判断（乐观/谨慎/恐慌等）
6. 次日展望和建议

请用简洁专业的语言进行分析，输出格式为纯文本，不要使用JSON格式。"""
    
    api_url = config.get('api_url')
    api_key = config.get('api_key')
    model = config.get('model', 'gpt-3.5-turbo')
    temperature = config.get('temperature', 0.7)
    max_tokens = config.get('max_tokens', 2000)
    # 增加超时时间到180秒，因为数据量大
    timeout = min(config.get('timeout', 180), 180)
    retry_count = config.get('retry_count', 3)
    retry_interval = min(config.get('retry_interval', 10), 10)
    
    info_logger.info(f"AI配置: model={model}, timeout={timeout}s, retry_count={retry_count}")
    
    if not api_url or not api_key:
        error_logger.error("AI配置不完整：缺少api_url或api_key")
        return {'success': False, 'message': 'AI配置不完整：缺少api_url或api_key'}
    
    full_url = config.get('full_url', False)
    if not full_url and not api_url.endswith('/chat/completions'):
        api_url = api_url.rstrip('/') + '/chat/completions'
    
    info_logger.info(f"AI API地址: {api_url}")
    
    # 构建分析数据文本
    analysis_text = "【今日板块资金流向数据】\n\n"
    
    # 添加TOP板块数据
    if top_sectors:
        analysis_text += "资金流入TOP5板块：\n"
        inflow_sectors = [s for s in top_sectors if s.get('flow_direction') == 'in' or s.get('net_flow', 0) > 0]
        for i, sector in enumerate(inflow_sectors[:5], 1):
            name = sector.get('name', '')
            net_flow = sector.get('net_flow', 0)
            change = sector.get('change', 0)
            analysis_text += f"{i}. {name}: 净流入{format_amount(net_flow)}, 涨跌幅{change*100:.2f}%\n"
        
        analysis_text += "\n资金流出TOP5板块：\n"
        outflow_sectors = [s for s in top_sectors if s.get('flow_direction') == 'out' or s.get('net_flow', 0) < 0]
        for i, sector in enumerate(outflow_sectors[:5], 1):
            name = sector.get('name', '')
            net_flow = sector.get('net_flow', 0)
            change = sector.get('change', 0)
            analysis_text += f"{i}. {name}: 净流出{format_amount(abs(net_flow))}, 涨跌幅{change*100:.2f}%\n"
    
    # 添加分钟级走势数据摘要
    time_keys_count = 0
    if minute_data:
        analysis_text += "\n【盘中资金流向走势】\n"
        time_keys = sorted([k for k in minute_data.keys() if not k.startswith('_')])
        time_keys_count = len(time_keys)
        info_logger.info(f"分钟数据时间点数量: {time_keys_count}")
        
        # 数据压缩策略：如果时间点超过25个，每10分钟取一个
        if time_keys_count > 25:
            # 筛选关键时间点：每10分钟取一个
            filtered_times = []
            for i, t in enumerate(time_keys):
                # 解析时间，取每10分钟的点
                try:
                    # 时间格式如 "09:35"
                    hour = int(t.split(':')[0])
                    minute = int(t.split(':')[1])
                    # 每10分钟取一个点（分钟为0, 10, 20, 30, 40, 50）
                    if minute % 10 == 0:
                        filtered_times.append(t)
                except:
                    # 如果解析失败，保留这个点
                    filtered_times.append(t)
            
            # 确保包含开盘和收盘时间点
            if time_keys:
                if time_keys[0] not in filtered_times:
                    filtered_times.insert(0, time_keys[0])
                if time_keys[-1] not in filtered_times:
                    filtered_times.append(time_keys[-1])
            
            info_logger.info(f"数据压缩：从{time_keys_count}个时间点压缩到{len(filtered_times)}个")
            time_keys = filtered_times
        
        # 传递时间点的完整数据
        for t in time_keys:
            data = minute_data.get(t, {})
            if isinstance(data, dict):
                items = data.get('data', [])
            else:
                items = data if isinstance(data, list) else []
            
            if items:
                # 按净流入排序，取流入和流出各前3（减少数据量）
                sorted_items = sorted(items, key=lambda x: x.get('net_flow', 0), reverse=True)
                top_in = sorted_items[:3]
                top_out = [s for s in sorted_items if s.get('net_flow', 0) < 0][:3]
                
                analysis_text += f"\n{t}\n"
                if top_in:
                    analysis_text += "流入: "
                    inflow_strs = []
                    for s in top_in:
                        name = s.get('name', '')
                        net_flow = s.get('net_flow', 0)
                        change = s.get('change', 0)
                        inflow_strs.append(f"{name}(+{format_amount(net_flow)}/{change*100:.2f}%)")
                    analysis_text += ", ".join(inflow_strs) + "\n"
                if top_out:
                    analysis_text += "流出: "
                    outflow_strs = []
                    for s in top_out:
                        name = s.get('name', '')
                        net_flow = s.get('net_flow', 0)
                        change = s.get('change', 0)
                        outflow_strs.append(f"{name}(-{format_amount(abs(net_flow))}/{change*100:.2f}%)")
                    analysis_text += ", ".join(outflow_strs) + "\n"
    
    # 添加大盘摘要数据
    if market_summary:
        analysis_text += "\n【大盘行情摘要】\n"
        breadth = market_summary.get('breadth', {})
        if breadth:
            up_count = breadth.get('up_count', 0)
            down_count = breadth.get('down_count', 0)
            limit_up = breadth.get('limit_up_count', 0)
            limit_down = breadth.get('limit_down_count', 0)
            analysis_text += f"涨跌家数: 涨{up_count}家, 跌{down_count}家\n"
            analysis_text += f"涨停跌停: 涨停{limit_up}家, 跌停{limit_down}家\n"
        
        turnover = market_summary.get('turnover', {})
        if turnover:
            total_turnover = turnover.get('turnover', 0)
            turnover_change = turnover.get('turnover_change', 0)
            analysis_text += f"成交额: {format_amount(total_turnover)}\n"
            if turnover_change:
                analysis_text += f"较上日变化: {format_amount(turnover_change, show_sign=True)}\n"
    
    # 记录数据长度
    data_length = len(analysis_text)
    info_logger.info(f"构建分析数据完成，数据长度: {data_length} 字符, 时间点数: {time_keys_count}")
    
    # 如果数据过长，进行截断
    if data_length > 15000:
        info_logger.warning(f"数据过长({data_length}字符)，进行截断至15000字符")
        analysis_text = analysis_text[:15000] + "\n\n[数据过长，已截断...]"
        data_length = len(analysis_text)
    
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": analysis_text}
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
    
    info_logger.info(f"开始调用AI API，timeout={timeout}s")
    
    for attempt in range(1, retry_count + 1):
        try:
            if _heartbeat_callback:
                _heartbeat_callback()
            
            start_time = time.time()
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=timeout
            )
            elapsed_time = time.time() - start_time
            info_logger.info(f"AI API响应时间: {elapsed_time:.2f}s, 状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                info_logger.info(f"AI全天走势分析成功，返回内容长度: {len(content)} 字符")
                return {'success': True, 'analysis': content}
            
            elif response.status_code == 429:
                retry_after = response.headers.get('Retry-After', str(retry_interval))
                try:
                    wait_time = int(retry_after)
                except:
                    wait_time = retry_interval
                info_logger.warning(f"API速率限制(429)，等待{wait_time}秒后重试，当前第{attempt}次")
                if attempt < retry_count:
                    time.sleep(wait_time)
                    continue
                return {'success': False, 'message': f'API速率限制，请稍后重试'}
            
            elif response.status_code == 504:
                error_logger.error(f"AI API返回504 Gateway Timeout，数据长度: {data_length}, timeout设置: {timeout}s")
                if attempt < retry_count:
                    info_logger.info(f"第{attempt}次失败，等待{retry_interval}秒后重试")
                    time.sleep(retry_interval)
                    continue
                return {'success': False, 'message': 'AI API超时(504)，数据量过大或API响应过慢，请稍后重试'}
            
            else:
                error_msg = f'HTTP {response.status_code}'
                try:
                    error_data = response.json()
                    if isinstance(error_data.get('error'), dict):
                        error_msg = error_data['error'].get('message', error_msg)
                except:
                    error_msg = response.text[:200] if response.text else error_msg
                error_logger.error(f"AI API错误: {error_msg}, 状态码: {response.status_code}, 第{attempt}次尝试")
                if attempt < retry_count:
                    time.sleep(retry_interval)
                    continue
                return {'success': False, 'message': error_msg}
                
        except requests.exceptions.Timeout:
            elapsed_time = time.time() - start_time
            error_logger.error(f"AI API请求超时，已等待{elapsed_time:.2f}s，数据长度: {data_length}, timeout设置: {timeout}s")
            if attempt < retry_count:
                info_logger.info(f"第{attempt}次超时，等待{retry_interval}秒后重试")
                time.sleep(retry_interval)
                continue
            return {'success': False, 'message': f'请求超时({timeout}秒)，数据量过大，请稍后重试'}
            
        except requests.exceptions.ConnectionError as e:
            error_logger.error(f"AI API连接失败: {str(e)}")
            if attempt < retry_count:
                time.sleep(retry_interval)
                continue
            return {'success': False, 'message': f'连接失败: {str(e)[:100]}'}
            
        except Exception as e:
            error_logger.error(f"AI API异常: {str(e)}, 第{attempt}次尝试")
            if attempt < retry_count:
                time.sleep(retry_interval)
                continue
            return {'success': False, 'message': f'异常: {str(e)[:100]}'}
    
    return {'success': False, 'message': 'AI分析失败，请稍后重试'}

def format_amount(value, show_sign=False):
    """格式化金额显示"""
    if value is None:
        return '--'
    
    amount = abs(value)
    sign = '+' if value > 0 else '-' if value < 0 else ''
    
    if amount >= 100000000:
        formatted = f"{amount/100000000:.2f}亿"
    elif amount >= 10000:
        formatted = f"{amount/10000:.2f}万"
    else:
        formatted = f"{amount:.0f}"
    
    if show_sign and value != 0:
        return sign + formatted
    return formatted
