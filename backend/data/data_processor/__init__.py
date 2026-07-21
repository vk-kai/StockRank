"""data_processor —— 数据处理枢纽（facade，向后兼容层）。

实际实现正逐步从 _legacy 拆分到子模块：
  _common / ths_client / storage / market_index / ai_chain / market_map

过渡期：从 _legacy 全量 re-export，保证 `from data.data_processor import xxx` 零改动。
每拆出一个子模块，此处改由该子模块 re-export，_legacy 相应缩小，直至 _legacy 清空删除。
"""
from ._legacy import *  # noqa: F401,F403  过渡期全量 re-export
from .ai_chain import get_ai_chain_indicators  # noqa: F401  (已从 _legacy 抽出到独立子模块)
from .market_map import (  # noqa: F401  (已从 _legacy 抽出到独立子模块)
    get_market_map_tree, get_market_map_all, get_market_map_sectors,
    get_market_map_stocks, get_all_market_map_stocks, refresh_market_map_cache,
)
from .ths_client import (  # noqa: F401  (已从 _legacy 抽出到独立子模块；含 latest_data accessor)
    generate_random_headers, normalize_ths_sector_headers,
    attach_fresh_ths_cookie, refresh_ths_cookie,
    get_sector_flow_data, get_sector_stocks, get_latest_data,
)
from .storage import (  # noqa: F401  (已从 _legacy 抽出到独立子模块：G3 文件IO + G4 日报 + G9 TOP5)
    get_daily_file_path, get_realtime_file_path,
    load_daily_data, save_daily_data, update_push_status, is_pushed,
    load_realtime_data, save_realtime_data, cleanup_old_data,
    generate_daily_summary, generate_daily_summary_for_date,
    load_recent_daily_data, load_recent_daily_data_with_accumulation,
    get_accumulated_top_sectors, load_recent_realtime_data,
    get_top5_comparison_data,
)
from ._common import error_logger, data_logger, system_logger  # noqa: F401  (logger 的规范归属)
