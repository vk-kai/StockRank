import json
import requests
import time
import re
from config import AI_CONFIG_FILE, AI_PROMPT_FILE
from logger import get_logger

error_logger = get_logger('error')
info_logger = get_logger('ai')

last_ai_call_time = 0
AI_CALL_INTERVAL = 20

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
        error_logger.error(f"AI API请求异常: {e}")
        error_logger.error(f"请求payload: {json.dumps(payload, ensure_ascii=False)[:1000]}")
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
        error_logger.error(f"AI返回内容不是有效JSON: {e}")
        error_logger.error(f"原始返回内容: {content[:500]}")
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
    timeout = config.get('timeout', 60)
    retry_count = config.get('retry_count', 3)
    retry_interval = 10
    
    if not api_url or not api_key:
        error_logger.error("AI配置不完整：缺少api_url或api_key")
        return {}
    
    if not api_url.endswith('/chat/completions'):
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
    
    for attempt in range(1, retry_count + 1):
        try:
            response = call_ai_api(api_url, api_key, model, temperature, max_tokens, timeout, messages)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                
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
                
                if attempt < retry_count:
                    info_logger.info(f"AI返回解析失败，{retry_interval}秒后重试 (第{attempt}/{retry_count}次)")
                    time.sleep(retry_interval)
                    continue
                return {}
            
            elif response.status_code == 429:
                retry_after = response.headers.get('Retry-After', str(retry_interval))
                try:
                    wait_time = int(retry_after)
                except:
                    wait_time = retry_interval
                error_logger.error(f"AI API速率限制(429)，等待 {wait_time} 秒")
                if attempt < retry_count:
                    time.sleep(wait_time)
                    continue
                return {}
            
            else:
                error_logger.error(f"AI API调用失败: {response.status_code} - {response.text[:200]}")
                if response.status_code == 422:
                    error_logger.error(f"422错误详情 - 新闻数量: {len(news_items)}, 消息长度: {len(combined_text)}")
                    error_logger.error(f"消息内容预览: {combined_text[:500]}")
                if attempt < retry_count:
                    info_logger.info(f"{retry_interval}秒后重试 (第{attempt}/{retry_count}次)")
                    time.sleep(retry_interval)
                    continue
                return {}
                
        except requests.exceptions.Timeout:
            error_logger.error(f"AI API请求超时 (timeout={timeout}秒)，新闻数量: {len(news_items)}")
            if attempt < retry_count:
                info_logger.info(f"{retry_interval}秒后重试 (第{attempt}/{retry_count}次)")
                time.sleep(retry_interval)
                continue
            return {}
            
        except requests.exceptions.ConnectionError as e:
            error_logger.error(f"AI API连接失败: {str(e)}")
            if attempt < retry_count:
                info_logger.info(f"{retry_interval}秒后重试 (第{attempt}/{retry_count}次)")
                time.sleep(retry_interval)
                continue
            return {}
            
        except Exception as e:
            error_logger.error(f"AI批量分析异常: {e}")
            if attempt < retry_count:
                info_logger.info(f"{retry_interval}秒后重试 (第{attempt}/{retry_count}次)")
                time.sleep(retry_interval)
                continue
            return {}
    
    return {}

def is_important_news(analysis_result):
    if not analysis_result:
        return False
    
    level = analysis_result.get('level', '')
    action_suggestion = analysis_result.get('action_suggestion', '')
    
    return level == '重大' or action_suggestion == '立即推送'
