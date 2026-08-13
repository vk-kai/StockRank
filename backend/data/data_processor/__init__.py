"""data_processor —— 数据处理枢纽（facade，向后兼容层）。

按职责拆分为 6 个子模块，本 facade 聚合 re-export 全部公共符号，
保证 `from data.data_processor import xxx` 对 15+ 依赖文件零改动：
  _common      loggers + 解析工具(_safe_float/_parse_*/...) + 跨组 URL 常量
  ths_client   同花顺采集(板块资金/个股) + latest_data accessor
  storage      文件IO + 日报聚合 + TOP5 对比
  market_index 大盘指数 + 市场摘要(latest_market_data 共享态)
  ai_chain     AI 产业链外部环境温度计
  market_map   大盘云图(行业→个股)
"""
from ._common import error_logger, data_logger, system_logger  # noqa: F401
from .ths_client import (  # noqa: F401
    generate_random_headers, normalize_ths_sector_headers,
    attach_fresh_ths_cookie, refresh_ths_cookie,
    get_sector_flow_data, get_sector_stocks, get_latest_data,
)
from .proxy_pool import get_verified_proxy, mark_bad, pool_status  # noqa: F401
from .storage import (  # noqa: F401
    get_daily_file_path, get_realtime_file_path,
    load_daily_data, save_daily_data, update_push_status, is_pushed,
    load_realtime_data, save_realtime_data, cleanup_old_data,
    generate_daily_summary, generate_daily_summary_for_date,
    load_recent_daily_data, load_recent_daily_data_with_accumulation,
    get_accumulated_top_sectors, load_recent_realtime_data,
    get_top5_comparison_data,
)
from .market_index import (  # noqa: F401
    latest_market_data, MARKET_FAST_REFRESH_SECONDS, MARKET_TURNOVER_REFRESH_SECONDS,
    get_eastmoney_market_index_data, get_sina_market_index_data, get_market_index_data,
    get_global_market_indices, get_stock_statistics, get_market_overview,
    get_ths_market_breadth, get_ths_turnover_summary, get_jrj_market_breadth,
    get_market_summary, get_market_fast_summary, should_refresh_market_turnover,
    refresh_market_summary_cache, save_market_summary_cache, load_market_summary_cache,
    is_market_summary_complete,
)
from .ai_chain import get_ai_chain_indicators  # noqa: F401
from .market_map import (  # noqa: F401
    get_market_map_tree, get_market_map_all, get_market_map_sectors,
    get_market_map_stocks, get_all_market_map_stocks, refresh_market_map_cache,
)
