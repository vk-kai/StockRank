import json
import time
import hmac
import hashlib
import base64
import requests
from config import FEISHU_CONFIG_FILE
from logger import setup_logging

error_logger, _, _ = setup_logging()

def load_feishu_config():
    try:
        with open(FEISHU_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error_logger.error(f"加载飞书配置失败: {e}")
        return None

def generate_sign(timestamp, secret):
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return sign

def send_feishu_message(title, content, analysis_result=None, url=None):
    config = load_feishu_config()
    
    if not config or not config.get('enabled'):
        return False
    
    webhook_url = config.get('webhook_url')
    secret = config.get('secret', '')
    msg_type = config.get('msg_type', 'text')
    
    if not webhook_url:
        error_logger.error("飞书配置不完整：缺少webhook_url")
        return False
    
    timestamp = str(int(time.time()))
    
    if msg_type == 'text':
        message = {
            "title": title,
            "content": content,
            "url": url or ""
        }
    else:
        message = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": "red"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{content}**"
                        }
                    }
                ]
            }
        }
        
        if url:
            elements = message["card"]["elements"]
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "查看原文"
                        },
                        "url": url,
                        "type": "primary"
                    }
                ]
            })
    
    if secret:
        sign = generate_sign(timestamp, secret)
        message["timestamp"] = timestamp
        message["sign"] = sign
    
    try:
        response = requests.post(
            webhook_url,
            json=message,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                return True
            else:
                error_logger.error(f"飞书推送失败: {result}")
                return False
        else:
            error_logger.error(f"飞书推送失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        error_logger.error(f"飞书推送异常: {e}")
        return False

def push_important_news(news_item, analysis_result):
    from datetime import datetime
    
    title = news_item.get('title', '')
    content = news_item.get('content', '')
    news_time = news_item.get('time', '')
    url = news_item.get('url')
    core_event = ''
    if analysis_result:
        core_event = analysis_result.get('core_event', '')
    
    if news_time:
        try:
            ts = int(news_time)
            news_time = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, OSError):
            pass
    
    parts = []
    if news_time:
        parts.append(news_time)
    parts.append(f"<font color='red'>{content}</font>")
    if core_event:
        parts.append(f"AI总结：{core_event}")
    
    formatted_content = "\n\n".join(parts)
    
    return send_feishu_message(title, formatted_content, url=url)
