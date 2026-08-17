import json
import re
from datetime import datetime

import requests

from core.config import WECHAT_CONFIG_FILE
from pushers.feishu_pusher import format_change_value, format_flow_value, build_ai_chain_env_lines
from core.logger import get_logger

error_logger = get_logger('error')


def load_wechat_config():
    try:
        with open(WECHAT_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        error_logger.error(f"加载企业微信配置失败: {e}")
        return {}


def _normalize_markdown(content):
    if not content:
        return ''

    normalized = content
    normalized = re.sub(
        r"<font\s+color=['\"]?red['\"]?>(.*?)</font>",
        r'<font color="warning">\1</font>',
        normalized,
        flags=re.IGNORECASE | re.DOTALL
    )
    normalized = re.sub(r"</?strong>", "**", normalized, flags=re.IGNORECASE)
    return normalized


def _plain_text(content):
    if not content:
        return ''
    return re.sub(r"</?font[^>]*>", "", content, flags=re.IGNORECASE)


def send_wechat_message(title, content, analysis_result=None, url=None):
    config = load_wechat_config()

    if not config or not config.get('enabled'):
        return False

    webhook_url = config.get('webhook_url')
    msg_type = config.get('msg_type', 'markdown')

    if not webhook_url:
        error_logger.error("企业微信配置不完整：缺少webhook_url")
        return False

    if msg_type == 'text':
        text_parts = [title, _plain_text(content)]
        if url:
            text_parts.append(f"原文链接：{url}")
        message = {
            "msgtype": "text",
            "text": {
                "content": "\n\n".join(part for part in text_parts if part)
            }
        }
    else:
        markdown_parts = [f"**{title}**", _normalize_markdown(content)]
        if url:
            markdown_parts.append(f"[查看原文]({url})")
        message = {
            "msgtype": "markdown",
            "markdown": {
                "content": "\n\n".join(part for part in markdown_parts if part)
            }
        }

    try:
        response = requests.post(webhook_url, json=message, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                return True
            error_logger.error(f"企业微信推送失败: {result}")
            return False

        error_logger.error(f"企业微信推送失败: {response.status_code} - {response.text}")
        return False

    except Exception as e:
        error_logger.error(f"企业微信推送异常: {e}")
        return False


def push_important_news_wechat(news_item, analysis_result=None):
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
    parts.append(f"<font color=\"warning\">{content}</font>")
    if core_event:
        parts.append(f"AI总结：{core_event}")

    formatted_content = "\n\n".join(parts)

    return send_wechat_message(title, formatted_content, url=url)


def push_daily_summary_wechat(comparison_data, period='上午'):
    config = load_wechat_config()

    if not config or not config.get('enabled'):
        return False

    base_url = config.get('base_url', 'http://localhost:5000')

    date_str = comparison_data['date']
    time_str = comparison_data['time']
    top5 = comparison_data['top5']

    title = f"📅 {date_str} {time_str} {period}收盘汇总"

    content_lines = []
    # 上午汇总头部追加 AI产业链外部环境灯（与飞书对称，跟随各通道 enabled 开关）
    if period == '上午':
        content_lines.extend(build_ai_chain_env_lines())

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
        content_lines.append(f"> 今日净流入：<font color=\"warning\">{format_flow_value(today_flow)}</font>")
        content_lines.append(f"> 今日涨跌：{format_change_value(today_change)}")

        if yesterday_flow is not None:
            content_lines.append(f"> 昨日净流入：{format_flow_value(yesterday_flow)}")
            content_lines.append(f"> 昨日涨跌：{format_change_value(yesterday_change)}")
            if flow_change_percent is not None:
                flow_change_sign = '+' if flow_change_percent >= 0 else ''
                content_lines.append(f"> {strength_icon} 资金变化：{flow_change_sign}{flow_change_percent:.1f}% ({strength})")
        else:
            content_lines.append(f"> {strength_icon} {strength}板块")

        content_lines.append("")

    content_lines.append(f"[查看日报]({base_url.rstrip('/')}/daily-report?date={date_str})")

    formatted_content = "\n".join(content_lines)

    return send_wechat_message(title, formatted_content)
