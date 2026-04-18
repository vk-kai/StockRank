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

def analyze_news_with_ai(news_item):
    global last_ai_call_time
    
    config = load_ai_config()
    
    if not config or not config.get('enabled'):
        return None
    
    elapsed = time.time() - last_ai_call_time
    if elapsed < AI_CALL_INTERVAL:
        time.sleep(AI_CALL_INTERVAL - elapsed)
    
    last_ai_call_time = time.time()
    
    prompt = load_ai_prompt()
    if not prompt:
        return None
    
    api_url = config.get('api_url')
    api_key = config.get('api_key')
    model = config.get('model', 'gpt-3.5-turbo')
    temperature = config.get('temperature', 0.7)
    max_tokens = config.get('max_tokens', 1000)
    timeout = config.get('timeout', 30)
    
    if not api_url or not api_key:
        error_logger.error("AI配置不完整：缺少api_url或api_key")
        return None
    
    if not api_url.endswith('/chat/completions'):
        api_url = api_url.rstrip('/') + '/chat/completions'
    
    news_text = f"标题：{news_item.get('title', '')}\n内容：{news_item.get('content', '')}"
    
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": news_text}
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
                
                first_brace = content.find('{')
                last_brace = content.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    content = content[first_brace:last_brace + 1]
                
                analysis_result = json.loads(content)
                return analysis_result
            except json.JSONDecodeError as e:
                error_logger.error(f"AI返回内容不是有效JSON: {e}")
                error_logger.error(f"原始返回内容: {content}")
                return None
        else:
            error_logger.error(f"AI API调用失败: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        error_logger.error(f"AI分析异常: {e}")
        return None

def is_important_news(analysis_result):
    if not analysis_result:
        return False
    
    level = analysis_result.get('level', '')
    action_suggestion = analysis_result.get('action_suggestion', '')
    
    return level == '重大' or action_suggestion == '立即推送'
