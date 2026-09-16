import os

from backend.paths import BACKEND_DIR, PROJECT_ROOT, TRADING_DB_PATH


def _load_env_file():
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_text(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


_load_env_file()

T0_ETF_LIST = [
    {"code": "510050", "name": "上证50ETF", "market": 1, "t0": True},
    {"code": "510300", "name": "沪深300ETF", "market": 1, "t0": True},
    {"code": "510500", "name": "中证500ETF", "market": 1, "t0": True},
    {"code": "159919", "name": "沪深300ETF", "market": 0, "t0": True},
    {"code": "512100", "name": "中证1000ETF", "market": 1, "t0": True},
    {"code": "588000", "name": "科创50ETF", "market": 1, "t0": True},
    {"code": "512660", "name": "军工ETF", "market": 1, "t0": True},
    {"code": "512880", "name": "证券ETF", "market": 1, "t0": True},
    {"code": "512010", "name": "医药ETF", "market": 1, "t0": True},
    {"code": "515030", "name": "新能源车ETF", "market": 1, "t0": True},
    {"code": "512690", "name": "酒ETF", "market": 1, "t0": True},
    {"code": "512400", "name": "有色金属ETF", "market": 1, "t0": True},
    {"code": "510880", "name": "红利ETF", "market": 1, "t0": True},
    {"code": "512980", "name": "传媒ETF", "market": 1, "t0": True},
    {"code": "518880", "name": "黄金ETF", "market": 1, "t0": True},
    {"code": "513100", "name": "纳指ETF", "market": 1, "t0": True},
    {"code": "513050", "name": "中概互联ETF", "market": 1, "t0": True},
    {"code": "512200", "name": "房地产ETF", "market": 1, "t0": True},
    {"code": "515790", "name": "光伏ETF", "market": 1, "t0": True},
    {"code": "562500", "name": "机器人ETF", "market": 1, "t0": True},
]

BASE_DIR = str(BACKEND_DIR)
DB_PATH = str(TRADING_DB_PATH)

DEFAULT_BALANCE = 100000.0

ALIPAY_APP_ID = _env_text("ALIPAY_APP_ID")
ALIPAY_PRIVATE_KEY = _env_text("ALIPAY_PRIVATE_KEY")
ALIPAY_PUBLIC_KEY = _env_text("ALIPAY_PUBLIC_KEY")
ALIPAY_NOTIFY_URL = _env_text("ALIPAY_NOTIFY_URL", "https://0vk.top/quant/api/auth/alipay/notify")
ALIPAY_RETURN_URL = _env_text("ALIPAY_RETURN_URL", "https://0vk.top/quant/")
ALIPAY_GATEWAY = _env_text("ALIPAY_GATEWAY", "https://openapi.alipay.com/gateway.do")
MARKET_MAP_PUSH_URL = _env_text("MARKET_MAP_PUSH_URL", "https://0vk.top/api/flow/market-map-push")
MARKET_MAP_PAGE_URL = _env_text("MARKET_MAP_PAGE_URL", "https://0vk.top/market-map?pushed=1")
PAYMENT_MOCK_ENABLED = _env_bool("PAYMENT_MOCK_ENABLED", True)

ACCOUNT_PURCHASE_PLANS = {
    "day": {
        "label": "单日体验",
        "price": 6.99,
        "duration_days": 1,
    },
    "month": {
        "label": "一月",
        "price": 99.0,
        "duration_days": 31,
    },
    "half_year": {
        "label": "一年",
        "price": 999.0,
        "duration_days": 365,
    },
}

PYTDX_SERVERS = []
PYTDX_SERVER_DISCOVERY_ENABLED = True
PYTDX_SERVER_DISCOVERY_CACHE_TTL = 15 * 60
PYTDX_SERVER_PROBE_COUNT = 12
PYTDX_SERVER_POOL_LIMIT = 24

# MACD非背驰回抽0轴买点的"趋势质量"最低分(0-100)。
# 0 = 不过滤,只在信号 reason 里标注质量摘要;>0 时低于该分数的买点直接丢弃。
# 区分目标: 强趋势首次回调(A/B) vs 上涨衰竭后的下跌中继(C,一票否决见 trend_quality.py)。
MACD_PULLBACK_MIN_QUALITY_SCORE = _env_int("MACD_PULLBACK_MIN_QUALITY_SCORE", 0)

PYTDX_CATEGORY = {
    "1min": 8,
    "5min": 0,
    "15min": 1,
    "30min": 2,
    "60min": 3,
    "daily": 4,
    "weekly": 5,
    "monthly": 6,
}

MINUTE_PERIODS = ["intraday", "1", "5", "15", "30", "60", "120"]
DAY_PERIODS = ["daily", "weekly", "monthly", "quarter", "year"]
ALL_PERIODS = MINUTE_PERIODS + DAY_PERIODS

CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]

REALTIME_PUSH_INTERVAL = 3

AUTO_SCAN_TRADING_SESSIONS = (
    ("09:30", "11:30"),
    ("13:00", "15:00"),
)

AUTO_SCAN_PERIOD_RULES = {
    "1min": {"type": "intraday_minutes", "step_minutes": 1},
    "5min": {"type": "intraday_minutes", "step_minutes": 5},
    "15min": {"type": "intraday_minutes", "step_minutes": 15},
    "30min": {"type": "intraday_minutes", "step_minutes": 30},
    "60min": {"type": "intraday_minutes", "step_minutes": 60},
    # 日/周/月线收盘后缓冲窗口：15:00 收盘 → 自动下载（含周五全量复检、失败后整点重试）
    # 可能占用数小时，期间扫描被 readiness 挡住且不消耗 slot（等当天日K下载完成才放行，
    # 见 live_scan/readiness._session_close_download_pending）；缓冲窗口拉长到当天 23:00，
    # 只要当天下载完成，当天收盘扫描仍会触发，不会因下载慢而错过。
    "daily": {"type": "session_close", "slots": ("15:00",), "after_close_buffer_minutes": 480},
    "weekly": {"type": "session_close", "slots": ("15:00",), "after_close_buffer_minutes": 480},
    "monthly": {"type": "session_close", "slots": ("15:00",), "after_close_buffer_minutes": 480},
}

# ---------------------------------------------------------------------------
# 套利背离监控（分时叠加 + 基准背离提示）
#
# 盘中每 ARB_MONITOR_INTERVAL_SECONDS 秒巡检一轮：个股分时 vs 基准（板块指数/
# A股指数/KOSPI）按吻合度 ρ + 价差偏离判背离，触发后写 arb_alerts 并经 WS 推送。
# 所有窗口均为北京时间；基准分时主源东财 trends2，兜底 pytdx 880 板块/新浪快照。
# ---------------------------------------------------------------------------
ARB_MONITOR_ENABLED_DEFAULT = _env_bool("ARB_MONITOR_ENABLED", True)
ARB_MONITOR_INTERVAL_SECONDS = _env_int("ARB_MONITOR_INTERVAL_SECONDS", 15)
# 巡检/取数大窗口（北京时间）：KOSPI 8:00 开盘早于 A 股，窗口覆盖其早盘
ARB_MONITOR_WINDOW = ("08:50", "15:05")
# 背离提示只在 A 股交易时段发出
ARB_ALERT_SESSIONS = (("09:30", "11:30"), ("13:00", "15:00"))
# KOSPI 累积窗口：窗口内每次取数都用新浪实时快照 upsert 当前分钟(东财只低频回填历史段)
ARB_KOSPI_ACCUM_WINDOW = ("08:00", "14:35")
# KOSPI 东财全量基线的刷新间隔秒(基线只补历史段,不需要实时;拉长也降低东财请求频率防封)
ARB_KOSPI_EM_BASE_TTL = _env_int("ARB_KOSPI_EM_BASE_TTL", 600)
# 盘前预示窗口：KOSPI 早盘累计涨跌 vs 个股集合竞价是否平开
ARB_PREOPEN_WINDOW = ("09:15", "09:30")
# 背离算法参数（窗口单位均为分钟数）
ARB_CORR_WINDOW = _env_int("ARB_CORR_WINDOW", 15)             # 吻合度 ρ 回看窗口(一天没几个30分钟,只看最近15分钟形态)
ARB_CORR_MIN = _env_float("ARB_CORR_MIN", 0.5)                # ρ 低于此值视为走势脱钩，不提示
ARB_CORR_SMOOTH_WINDOW = _env_int("ARB_CORR_SMOOTH_WINDOW", 3)  # ρ/β 计算前的分钟级平滑窗口(1=关);先平滑再比折线形状,个股分钟抖动/慢一拍不误杀
ARB_CORR_MAX_LAG = _env_int("ARB_CORR_MAX_LAG", 2)             # ρ 容忍的分钟错位数(0=关);个股恒定慢一两拍形状仍算吻合
ARB_BETA_WINDOW = _env_int("ARB_BETA_WINDOW", 90)             # β 回归窗口
ARB_BETA_MIN = _env_float("ARB_BETA_MIN", 0.2)                # β 夹取下限
ARB_BETA_MAX = _env_float("ARB_BETA_MAX", 5.0)                # β 夹取上限
ARB_SIGMA_WINDOW = _env_int("ARB_SIGMA_WINDOW", 60)           # 价差 σ 窗口
ARB_SPREAD_K = _env_float("ARB_SPREAD_K", 2.0)                # 价差漂移 σ 倍数阈值
ARB_DRIFT_MINUTES = _env_int("ARB_DRIFT_MINUTES", 5)          # 价差漂移回看分钟数
ARB_DRIFT_TAIL_Q = _env_float("ARB_DRIFT_TAIL_Q", 0.95)       # 漂移异常的"自身历史"分位阈值(0.95=超过该对今天95%的同类波动;排除最近bench_mom_window分钟)
ARB_DRIFT_TAIL_MIN_SAMPLES = _env_int("ARB_DRIFT_TAIL_MIN_SAMPLES", 30)  # 自身历史样本低于此数退回σ倍数口径(开盘初期)
ARB_BENCH_MOM_WINDOW = _env_int("ARB_BENCH_MOM_WINDOW", 15)   # 基准动量窗口
ARB_BENCH_MOM_Z = _env_float("ARB_BENCH_MOM_Z", 1.0)          # 基准动量 z 阈值
ARB_BENCH_MOM_MIN_PCT = _env_float("ARB_BENCH_MOM_MIN_PCT", 0.25)  # 基准窗口内最小真实涨跌幅 %,不足不提示(防死水行情误报)
# 全球基准(em_global,如KOSPI)专用放宽:单一大盘指数波动远小于A股题材板块,
# 统一口径下"基准15分钟≥0.25%"与"漂移进自身前5%"几乎不会同时发生,信号常年空转
ARB_GLOBAL_MOM_MIN_PCT = _env_float("ARB_GLOBAL_MOM_MIN_PCT", 0.15)        # em_global: 基准窗口内最小真实涨跌幅 %
ARB_GLOBAL_DRIFT_TAIL_Q = _env_float("ARB_GLOBAL_DRIFT_TAIL_Q", 0.90)      # em_global: 漂移"自身历史"分位阈值(0.90=前10%)
# 信号地板(2026-09-15 14:00 假信号事故): 预热期 β/σ/ρ 全是垃圾统计,微小背离也能刷满
# 相对口径门槛 → 样本不足不出信号;价差漂移另有绝对幅度地板
ARB_SIGNAL_MIN_SAMPLES = _env_int("ARB_SIGNAL_MIN_SAMPLES", 15)             # 出信号所需最少对齐样本数(开盘/重启预热期只观察)
ARB_SPREAD_ABS_PCT = _env_float("ARB_SPREAD_ABS_PCT", 0.30)                 # 价差漂移绝对地板 %(不足不提示,防微小背离刷信号)
ARB_GLOBAL_SPREAD_ABS_PCT = _env_float("ARB_GLOBAL_SPREAD_ABS_PCT", 0.20)   # em_global: 漂移绝对地板 %(低β对的漂移天然小,地板相应放低)
ARB_ALERT_COOLDOWN_MINUTES = _env_int("ARB_ALERT_COOLDOWN_MINUTES", 20)   # 同对同向冷却分钟
ARB_MIN_OVERLAP_SAMPLES = _env_int("ARB_MIN_OVERLAP_SAMPLES", 6)          # 判背离所需最少对齐样本(开盘~6分钟即可判定;漂移/动量窗口不足时自动收缩)
ARB_PREOPEN_KOSPI_PCT = _env_float("ARB_PREOPEN_KOSPI_PCT", 0.8)          # 盘前 KOSPI 累计涨跌阈值 %
ARB_PREOPEN_STOCK_FLAT_PCT = _env_float("ARB_PREOPEN_STOCK_FLAT_PCT", 0.3)  # 个股竞价视为平开阈值 %
ARB_GLOBAL_BENCH_CLOSE = _env_text("ARB_GLOBAL_BENCH_CLOSE", "14:30")       # 全球基准收盘时刻(北京时间;KOSPI 15:30 KST=14:30),收盘后该类基准的配对不再判定
ARB_TRENDS_CACHE_TTL = _env_int("ARB_TRENDS_CACHE_TTL", 12)               # 基准分时缓存秒
ARB_TRENDS_STALE_MAX_SECONDS = _env_int("ARB_TRENDS_STALE_MAX_SECONDS", 300)  # 陈旧基准最大可服务年龄
ARB_MAX_PAIRS = _env_int("ARB_MAX_PAIRS", 20)                             # 每用户最多监控对数

LIVE_SCAN_STRATEGY_OPTIONS = [
    {
        "name": "MA_BULL_PULLBACK_BOLL",
        "description": "MA多头放量阳线",
        "enabled": True,
    },
    {
        "name": "MA_SUPPORT_PULLBACK",
        "description": "MA均线支撑回踩做多",
        "enabled": True,
    },
    {
        "name": "MACD_CHAN_DIVERGENCE",
        "description": "MACD 缠论背驰面积策略",
        "enabled": True,
    },
    {
        "name": "MACD_CHAN_THIRD_BUY",
        "description": "MACD 缠论三买策略",
        "enabled": True,
    },
    {
        "name": "MACD_NON_DIVERGENCE_PULLBACK",
        "description": "MACD 非背驰回抽0轴策略",
        "enabled": True,
    },
    {
        "name": "MACD_Cross",
        "description": "MACD 金叉死叉策略",
        "enabled": False,
    },
    {
        "name": "ETF_T0_MA_RSI",
        "description": "ETF T0 均线 RSI 策略",
        "enabled": False,
    },
]

KLINE_CACHE_TTL = 60
REALTIME_SENSITIVE_KLINE_PERIODS = (
    "1min",
    "5min",
    "15min",
    "30min",
    "60min",
    "daily",
)
KLINE_SOURCE_PRIORITY = {
    "security": {
        "1min": ("local", "pytdx"),
        "5min": ("local", "pytdx"),
        "15min": ("local", "pytdx"),
        "30min": ("local", "pytdx"),
        "60min": ("local", "pytdx"),
        "daily": ("local", "pytdx"),
        "weekly": ("local", "pytdx"),
        "monthly": ("local", "pytdx"),
        "quarter": ("local", "pytdx"),
        "year": ("local", "pytdx"),
    },
    "index": {
        "1min": ("local", "pytdx"),
        "5min": ("local", "pytdx"),
        "15min": ("local", "pytdx"),
        "30min": ("local", "pytdx"),
        "60min": ("local", "pytdx"),
        "daily": ("local", "pytdx"),
        "weekly": ("local", "pytdx"),
        "monthly": ("local", "pytdx"),
        "quarter": ("local", "pytdx"),
        "year": ("local", "pytdx"),
    },
}

# 市场现货与行业数据源优先级策略，保证切换后可持久并可回退
# 巨潮更适合行业分类，不适合作为全市场实时现货主源；实时现货优先腾讯，新浪兜底。
MARKET_SPOT_SOURCE_PRIORITY = (
    "tencent",
    "sina",
)
MARKET_INDEX_SOURCE_PRIORITY = (
    "pytdx",
    "tencent",
    "sina",
)
INDUSTRY_SOURCE_PRIORITY = (
    "cninfo",   # 优先使用巨潮个股行业变更接口，取申万“行业门类-行业次类”
    "sina",     # 兜底使用新浪行业板块-成份映射
)
A_SHARE_LIST_SOURCE_PRIORITY = (
    "akshare_spot",
    "pytdx",
)
STOCK_NAME_SOURCE_PRIORITY = (
    "akshare",
    "pytdx",
)

LOCAL_KLINE_CACHE_RULES = {
    "1min": {
        "min_bars": 1200,
        "full_fetch_bars": 6000,
        "refresh_fetch_bars": 600,
        "keep_latest": 8000,
        "refresh_interval_seconds": 5 * 60,
    },
    "5min": {
        "min_bars": 1200,
        "full_fetch_bars": 5000,
        "refresh_fetch_bars": 240,
        "keep_latest": 6000,
        "refresh_interval_seconds": 10 * 60,
    },
    "15min": {
        "min_bars": 800,
        "full_fetch_bars": 3200,
        "refresh_fetch_bars": 160,
        "keep_latest": 3600,
        "refresh_interval_seconds": 15 * 60,
    },
    "daily": {
        "min_bars": 160,
        "full_fetch_bars": 300,
        "refresh_fetch_bars": 40,
        "keep_latest": 400,
        "refresh_interval_seconds": 8 * 60 * 60,
    },
    "30min": {
        "min_bars": 180,
        "full_fetch_bars": 2200,
        "refresh_fetch_bars": 96,
        "keep_latest": 2400,
        "refresh_interval_seconds": 20 * 60,
    },
    "60min": {
        "min_bars": 180,
        "full_fetch_bars": 1200,
        "refresh_fetch_bars": 48,
        "keep_latest": 1400,
        "refresh_interval_seconds": 30 * 60,
    },
    "weekly": {
        "min_bars": 120,
        "full_fetch_bars": 240,
        "refresh_fetch_bars": 16,
        "keep_latest": 260,
        "refresh_interval_seconds": 24 * 60 * 60,
    },
    "monthly": {
        "min_bars": 60,
        "full_fetch_bars": 120,
        "refresh_fetch_bars": 6,
        "keep_latest": 140,
        "refresh_interval_seconds": 24 * 60 * 60,
    },
}

# 盘中查看K线时本地缓存允许的最大滞后:在常规 refresh_interval_seconds 之外,
# 盘中请求会按该窗口强制重同步本地缓存。akshare 日线历史接口盘中本身返回当天
# 未收盘K线,因此即使实时行情源(腾讯/pytdx)在机房网络下全部不可用,主图也能
# 拿到不超过该窗口的当天bar,而不是退回"只有上次下载的旧历史"。
INTRADAY_KLINE_FRESH_WINDOW_SECONDS = 5 * 60

DOWNLOADABLE_KLINE_PERIODS = (
    "1min",
    "5min",
    "15min",
    "30min",
    "60min",
    "daily",
    "weekly",
    "monthly",
)

HISTORY_DOWNLOAD_DEFAULT_PERIODS = ()

HISTORY_DOWNLOAD_PERIOD_OPTIONS = [
    {"value": "1min", "label": "1分", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "5min", "label": "5分", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "15min", "label": "15分", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "30min", "label": "30分", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "60min", "label": "60分", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "daily", "label": "日线", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "weekly", "label": "周线", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
    {"value": "monthly", "label": "月线", "store": "本地历史K线", "realtime": "实时价格仍走行情接口"},
]

# ---------------------------------------------------------------------------
# 树莓派边缘节点卸载（Pi edge-node offloading）
#
# 通过 SSH 反向隧道（autossh -R）把树莓派暴露为服务器本机的 http://127.0.0.1:<port>，
# 服务器把回测计算卸载到 Pi；失败/超时自动回落本机 run_backtest / ProcessPoolExecutor。
# 默认 PI_NODE_ENABLED=False：现有回测路径零改动、零行为变化。
# ---------------------------------------------------------------------------
PI_NODE_ENABLED = _env_bool("PI_NODE_ENABLED", False)  # 可通过 API 运行时切换


def set_pi_node_enabled(enabled: bool) -> None:
    """运行时切换 Pi 节点启用状态，同时持久化到 .env 以便重启后保留。"""
    global PI_NODE_ENABLED
    PI_NODE_ENABLED = enabled
    os.environ["PI_NODE_ENABLED"] = "true" if enabled else "false"
    _persist_env_key("PI_NODE_ENABLED", "true" if enabled else "false")


def _persist_env_key(key: str, value: str) -> None:
    """将单个 key=value 写入 .env 文件（存在则替换，不存在则追加）。"""
    env_path = PROJECT_ROOT / ".env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
# 服务器访问 Pi 的地址（autossh -R 在服务器侧绑定的 loopback 端口）
PI_NODE_URL = _env_text("PI_NODE_URL", "http://127.0.0.1:8765")
# 可选 X-Node-Token 头；空 = 不鉴权（隧道已绑 127.0.0.1，token 为纵深防御）
PI_NODE_TOKEN = _env_text("PI_NODE_TOKEN", "")
# 卸载范围：both / single_only / full_only（Pi 比服务器慢时可只卸载全量扫描）
PI_NODE_OFFLOAD_MODE = _env_text("PI_NODE_OFFLOAD_MODE", "both")
PI_NODE_SINGLE_TIMEOUT = _env_int("PI_NODE_SINGLE_TIMEOUT", 120)       # 单股 RPC 超时秒
PI_NODE_BATCH_TIMEOUT = _env_int("PI_NODE_BATCH_TIMEOUT", 300)         # 单批全量 RPC 超时秒
PI_NODE_BATCH_CHUNK = _env_int("PI_NODE_BATCH_CHUNK", 50)              # 全量每批发送的标的数
PI_NODE_HEALTH_INTERVAL = _env_int("PI_NODE_HEALTH_INTERVAL", 15)     # 健康检测协程周期秒
PI_NODE_COOLDOWN = _env_int("PI_NODE_COOLDOWN", 60)                   # 失败后冷却秒
PI_NODE_PROBE_TIMEOUT = _env_float("PI_NODE_PROBE_TIMEOUT", 2.0)      # /health 探测超时秒
PI_NODE_MAX_DF_KB = _env_int("PI_NODE_MAX_DF_KB", 512)                # 单标的 df b64 超此 KB 则跳过卸载
