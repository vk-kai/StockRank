import json
import requests
import time
import re
from config import AI_CONFIG_FILE, AI_PROMPT_FILE
from logger import setup_logging

error_logger, info_logger, _ = setup_logging()

last_ai_call_time = 0
AI_CALL_INTERVAL = 20

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
    
    if not api_url or not api_key:
        error_logger.error("AI配置不完整：缺少api_url或api_key")
        return {}
    
    if not api_url.endswith('/chat/completions'):
        api_url = api_url.rstrip('/') + '/chat/completions'
    
    news_texts = []
    for item in news_items:
        news_id = item.get('id', '')
        title = item.get('title', '')
        content = item.get('content', '')
        news_texts.append(f"[id:{news_id}]\n标题：{title}\n内容：{content}")
    
    combined_text = "\n\n---\n\n".join(news_texts)
    
    batch_prompt = prompt + "\n\n注意：本次输入包含多条新闻，每条新闻以[id:xxx]开头标识。请返回一个JSON数组，每个元素包含id字段和对应的分析结果，格式如下：\n[\n  {\"id\": \"新闻id\", \"level\": \"重大/一般\", \"impact_type\": \"即时影响/延迟影响\", \"event_type\": \"新闻/行情异动\", \"core_event\": \"一句话总结\", \"reason\": \"对A股的影响逻辑\", \"impact_market\": \"A股/美股/全球\", \"related_sector\": [\"板块1\",\"板块2\"], \"action_suggestion\": \"立即推送/忽略\"},\n  ...\n]\n只输出JSON数组，不要解释。"
    
    messages = [
        {"role": "system", "content": batch_prompt},
        {"role": "user", "content": combined_text}
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
    
    try:
        response = requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            
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
                return {}
        else:
            error_logger.error(f"AI API调用失败: {response.status_code} - {response.text[:200]}")
            return {}
            
    except Exception as e:
        error_logger.error(f"AI批量分析异常: {e}")
        return {}

def is_important_news(analysis_result):
    if not analysis_result:
        return False
    
    level = analysis_result.get('level', '')
    action_suggestion = analysis_result.get('action_suggestion', '')
    
    return level == '重大' or action_suggestion == '立即推送'
