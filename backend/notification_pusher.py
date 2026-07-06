from feishu_pusher import (
    load_feishu_config,
    push_daily_summary_feishu,
    send_feishu_message,
)
from logger import get_logger
from wechat_pusher import (
    load_wechat_config,
    push_daily_summary_wechat,
    send_wechat_message,
)

info_logger = get_logger('data_push')

IMPORTANT_AI_FILTER = 'important_ai_filter'
IMPORTANT_DIRECT = 'important_direct'
ALL_DIRECT = 'all_direct'
ALL_AI_FILTER = 'all_ai_filter'

NEWS_PUSH_MODES = {
    IMPORTANT_AI_FILTER,
    IMPORTANT_DIRECT,
    ALL_DIRECT,
    ALL_AI_FILTER,
}


def _is_enabled(config):
    return bool(config and config.get('enabled'))


def _get_news_push_mode(config):
    mode = (config or {}).get('news_push_mode', IMPORTANT_AI_FILTER)
    return mode if mode in NEWS_PUSH_MODES else IMPORTANT_AI_FILTER


def is_push_enabled():
    return _is_enabled(load_feishu_config()) or _is_enabled(load_wechat_config())


def get_enabled_news_channels():
    channels = []

    feishu_config = load_feishu_config()
    if _is_enabled(feishu_config):
        channels.append({
            'name': '飞书',
            'key': 'feishu',
            'mode': _get_news_push_mode(feishu_config),
            'send': send_feishu_message,
        })

    wechat_config = load_wechat_config()
    if _is_enabled(wechat_config):
        channels.append({
            'name': '企业微信',
            'key': 'wechat',
            'mode': _get_news_push_mode(wechat_config),
            'send': send_wechat_message,
        })

    return channels


def _push_to_enabled_channels(pushers):
    results = []

    for channel_name, enabled, push_func in pushers:
        if not enabled:
            continue

        success = push_func()
        results.append((channel_name, success))
        if success:
            info_logger.info(f"{channel_name}推送成功")
        else:
            info_logger.error(f"{channel_name}推送失败")

    return any(success for _, success in results)


def _format_news_content(news_item, analysis_result=None, prefix_lines=None):
    from datetime import datetime

    content = news_item.get('content', '')
    news_time = news_item.get('time', '')

    if news_time:
        try:
            ts = int(news_time)
            news_time = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, OSError):
            pass

    parts = []
    if prefix_lines:
        parts.extend(prefix_lines)
    if news_time:
        parts.append(news_time)
    parts.append(f"<font color='red'>{content}</font>")

    if analysis_result and analysis_result.get('core_event'):
        parts.append(f"AI总结：{analysis_result.get('core_event')}")

    return "\n\n".join(parts)


def send_news_item_to_channels(news_item, analysis_result=None, channels=None, prefix_lines=None):
    enabled_channels = channels if channels is not None else get_enabled_news_channels()
    title = news_item.get('title', '')
    content = _format_news_content(news_item, analysis_result, prefix_lines)
    url = news_item.get('url')
    results = []

    for channel in enabled_channels:
        success = channel['send'](title, content, analysis_result, url)
        results.append((channel['key'], channel['name'], success))
        if success:
            info_logger.info(f"{channel['name']}新闻推送成功")
        else:
            info_logger.error(f"{channel['name']}新闻推送失败")

    return results


def push_important_news(news_item, analysis_result=None):
    results = send_news_item_to_channels(news_item, analysis_result)
    return any(success for _, _, success in results)


def send_news_message(title, content, analysis_result=None, url=None):
    feishu_enabled = _is_enabled(load_feishu_config())
    wechat_enabled = _is_enabled(load_wechat_config())

    return _push_to_enabled_channels([
        ('飞书', feishu_enabled, lambda: send_feishu_message(title, content, analysis_result, url)),
        ('企业微信', wechat_enabled, lambda: send_wechat_message(title, content, analysis_result, url)),
    ])


def push_daily_summary(comparison_data, period='上午'):
    feishu_enabled = _is_enabled(load_feishu_config())
    wechat_enabled = _is_enabled(load_wechat_config())

    return _push_to_enabled_channels([
        ('飞书', feishu_enabled, lambda: push_daily_summary_feishu(comparison_data, period)),
        ('企业微信', wechat_enabled, lambda: push_daily_summary_wechat(comparison_data, period)),
    ])
