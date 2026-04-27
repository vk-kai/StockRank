import json
import time
import hmac
import hashlib
import base64
import requests
from config import FEISHU_CONFIG_FILE
from logger import get_logger

error_logger = get_logger('error')

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

def push_important_news(news_item, analysis_result=None):
    from datetime import datetime
    
    title = news_item.get('title', '')
    content = news_item.get('content', '')
    news_time = news_item.get('time', '')
    url = news_item.get('url')
    
    core_event = ''
    if analysis_result:
        core_event = analysis_result.get('core_event', '')
    else:
        core_event = '请配置AI'
    
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

def format_flow_value(value):
    if value is None:
        return '-'
    if abs(value) >= 10000:
        return f"{value/10000:.2f}亿"
    else:
        return f"{value:.2f}万"

def format_change_value(value):
    if value is None:
        return '-'
    percent = value * 100
    sign = '+' if percent >= 0 else ''
    return f"{sign}{percent:.2f}%"

def push_daily_summary_feishu(comparison_data, period='上午'):
    config = load_feishu_config()
    
    if not config or not config.get('enabled'):
        return False
    
    webhook_url = config.get('webhook_url')
    secret = config.get('secret', '')
    base_url = config.get('base_url', 'http://localhost:5000')
    
    if not webhook_url:
        error_logger.error("飞书配置不完整：缺少webhook_url")
        return False
    
    date_str = comparison_data['date']
    time_str = comparison_data['time']
    top5 = comparison_data['top5']
    
    title = f"📅 {date_str} {time_str} {period}收盘汇总"
    
    content_lines = [
        ""
    ]
    
    for item in top5:
        rank = item['rank']
        name = item['name']
        today_flow = item['today_flow']
        today_change = item['today_change']
        yesterday_flow = item['yesterday_flow']
        yesterday_change = item['yesterday_change']
        strength = item['strength']
        flow_change_percent = item['flow_change_percent']
        
        strength_icon = '🔴' if strength == '增强' else ('🟢' if strength == '减弱' else ('🟡' if strength == '持平' else '🔥'))
        
        content_lines.append(f"**{rank}. {name}**")
        content_lines.append(f"   💰 今日流入：**<font color='red'>{format_flow_value(today_flow)}</font>**")
        content_lines.append(f"   📈 今日涨跌：**{format_change_value(today_change)}**")
        
        if yesterday_flow is not None:
            content_lines.append(f"   📊 昨日流入：{format_flow_value(yesterday_flow)}")
            content_lines.append(f"   📉 昨日涨跌：{format_change_value(yesterday_change)}")
            if flow_change_percent is not None:
                flow_change_sign = '+' if flow_change_percent >= 0 else ''
                content_lines.append(f"   {strength_icon} 资金变化：**{flow_change_sign}{flow_change_percent:.1f}%** ({strength})")
        else:
            content_lines.append(f"   {strength_icon} {strength}板块")
        
        content_lines.append("")
    
    content_lines.append("---")
    content_lines.append("")
    
    formatted_content = "\n".join(content_lines)
    
    timestamp = str(int(time.time()))
    
    message = {
        "title": title,
        "content": formatted_content,
        "url": f"{base_url}/daily-report?date={date_str}"
    }
    
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
