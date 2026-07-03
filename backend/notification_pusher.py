from feishu_pusher import (
    load_feishu_config,
    push_daily_summary_feishu,
    push_important_news as push_important_news_feishu,
    send_feishu_message,
)
from logger import get_logger
from wechat_pusher import (
    load_wechat_config,
    push_daily_summary_wechat,
    push_important_news_wechat,
    send_wechat_message,
)

info_logger = get_logger('system')


def _is_enabled(config):
    return bool(config and config.get('enabled'))


def is_push_enabled():
    return _is_enabled(load_feishu_config()) or _is_enabled(load_wechat_config())


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


def push_important_news(news_item, analysis_result=None):
    feishu_enabled = _is_enabled(load_feishu_config())
    wechat_enabled = _is_enabled(load_wechat_config())

    return _push_to_enabled_channels([
        ('飞书', feishu_enabled, lambda: push_important_news_feishu(news_item, analysis_result)),
        ('企业微信', wechat_enabled, lambda: push_important_news_wechat(news_item, analysis_result)),
    ])


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
