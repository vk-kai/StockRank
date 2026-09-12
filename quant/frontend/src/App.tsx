import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Sidebar from "./components/Sidebar";
import AutoScanPanel from "./components/AutoScanPanel";
import ArbMonitorPanel from "./components/ArbMonitorPanel";
import DataDownloadModal from "./components/DataDownloadModal";
import UserManagementModal from "./components/UserManagementModal";
import KlineChart from "./components/KlineChart";
import PeriodSelector from "./components/PeriodSelector";
import BacktestPanel from "./components/BacktestPanel";
import LoginModal, { type LoginModalView } from "./components/LoginModal";
import SystemStatsWidget from "./components/SystemStatsWidget";
import NodeStatusChip from "./components/NodeStatusChip";
import { useWebSocket } from "./hooks/useWebSocket";
import {
  fetchAuthSession,
  fetchArbStatus,
  fetchWatchlist,
  fetchKline,
  fetchSecurityDetail,
  fetchBenchmarkTrends,
  searchBenchmarks,
  fetchMajorIndexQuotes,
  fetchSignalDiagnosis,
  fetchScanStatus,
  fetchHistoryDownloadStatus,
  saveScanSettings,
  runScanNow,
  markScanSignalsRead,
  markArbAlertsRead,
  deleteScanRun,
  pushScanRunToMarketMap,
  startHistoryDownload,
  logoutAuth,
  trackSignal,
  untrackSignal,
  fetchTrackedSignals,
  fetchSettledSignals,
} from "./api";
import type { AuthSessionData, AuthUser } from "./api/auth";
import { parseChartTimestampText, normalizeSignalChartPeriod, formatSignalPeriodLabel } from "./lib/chartTime";
import {
  DEFAULT_KLINE_COUNT,
  calculateChartIndicators,
  getDefaultKlineCount,
  HISTORY_KLINE_STEP,
  isLikelyTradingTime,
  KLINE_FALLBACK_POLL_MS,
  KLINE_FRONTEND_CACHE_MAX,
  KLINE_FRONTEND_CACHE_TTL_MS,
  KLINE_PREFETCH_INITIAL_DELAY_MS,
  KLINE_PREFETCH_PERIODS,
  KLINE_PREFETCH_STAGGER_MS,
  PREFETCH_NEARBY_WATCHLIST_COUNT,
  REALTIME_KLINE_REFRESH_MS,
} from "./lib/kline";
import { isIndexCode } from "./lib/market";
import { playArbAlertSound } from "./lib/alertSound";
import { isArbNameHidden, maskArbStockLabel, onArbNameHiddenChange } from "./lib/arbPrivacy";
import {
  buildChanAutoDrawResult,
  diagnoseFractal,
  diagnoseSegmentEndpoint,
} from "./lib/chan";
import type { FractalDiagnosis, SegmentEndpointDiagnosis } from "./lib/chan";
import type {
  WatchlistSecurityInfo,
  KlineData,
  SignalInfo,
  BacktestResult,
  BatchExtremeDetail,
  KlineResponse,
  ScanSignal,
  ScanStatus,
  SignalDiagnosisResult,
  IndexQuote,
  HistoryDownloadStatus,
  TradeRecordItem,
  TrackedSignal,
  TrackedSignalSettlement,
  SettledSignal,
  BenchmarkTrends,
  BenchKind,
  ArbAlert,
} from "./types";

const DRAW_PANEL_WIDTH = 300;
const DRAW_PANEL_MIN_TOP = 88;
const DRAW_PANEL_GUTTER = 12;

// 分时叠加基准预设;searchKeyword 的项由后端 bench_registry/东财在线解析板块代码
const BENCH_PRESETS: Array<{
  key: string;
  label: string;
  kind?: BenchKind;
  code?: string;
  searchKeyword?: string;
}> = [
  { key: "none", label: "无基准" },
  { key: "idx-sh", label: "上证指数", kind: "em_index", code: "000001" },
  { key: "idx-sz", label: "深证成指", kind: "em_index", code: "399001" },
  { key: "idx-cyb", label: "创业板指", kind: "em_index", code: "399006" },
  { key: "idx-kc50", label: "科创50", kind: "em_index", code: "000688" },
  { key: "kospi", label: "韩国KOSPI", kind: "em_global", code: "KS11" },
  // 国家大基金持股 = 东财概念板块 BK0717(内置直连,不依赖在线解析;后端 resolve_board_code 也内置了同名兜底)
  { key: "fund-board", label: "国家大基金持股", kind: "em_board", code: "BK0717" },
];

function getKlineTradingDate(bar: Pick<KlineData, "time" | "timestamp">) {
  const timeText = typeof bar.time === "string" ? bar.time.trim() : "";
  const matched = timeText.match(/^(\d{4}-\d{2}-\d{2})/);
  if (matched) {
    return matched[1];
  }
  const date = new Date(bar.timestamp * 1000);
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function formatDiagnosisBarTime(bar: Pick<KlineData, "time" | "timestamp">) {
  const timeText = typeof bar.time === "string" ? bar.time.trim() : "";
  if (timeText) {
    return timeText;
  }
  if (!Number.isFinite(bar.timestamp) || bar.timestamp <= 0) {
    return "--";
  }
  const date = new Date(bar.timestamp * 1000);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function renderDiagnosisReason(reason: string) {
  const tokenPattern = /(DIF|DEA|MACD|BOLL|MA\d+|0轴|金叉|死叉|止损价|止损位|买入价|入场价|参考低点|最低价|最高价|收盘价|收盘|当前价格|当前价|价格|面积x2|面积|间距|低点|高点|红柱|绿柱|黄白线|[<>]=?|=|[-+]?\d+(?:\.\d+)?%?)/g;
  const parts = reason.split(tokenPattern);
  return parts.filter(Boolean).map((part, index) => {
    const isNumber = /^[-+]?\d+(?:\.\d+)?%?$/.test(part);
    const isOperator = /^(?:[<>]=?|=)$/.test(part);
    const isKeyword = /^(?:DIF|DEA|MACD|BOLL|MA\d+|0轴|金叉|死叉|止损价|止损位|买入价|入场价|参考低点|最低价|最高价|收盘价|收盘|当前价格|当前价|价格|面积x2|面积|间距|低点|高点|红柱|绿柱|黄白线)$/.test(part);
    if (!isNumber && !isOperator && !isKeyword) {
      return <span key={`${part}-${index}`}>{part}</span>;
    }
    return (
      <span
        key={`${part}-${index}`}
        className={`signal-diagnosis-inline-token ${
          isOperator ? "operator" : isNumber ? "number" : "keyword"
        }`}
      >
        {part}
      </span>
    );
  });
}

type HighlightedTrade = {
  timestamp: number;
  direction: string;
} | null;

type SignalDiagnosisContext =
  | {
      source: "backtest";
      strategyName: string;
      rangeStart: string;
      rangeEnd: string;
    }
  | {
      source: "scan";
      strategyName: string;
    }
  | null;

type SettlementModalState = {
  visible: boolean;
  code: string;
  name: string;
  removedFromWatchlist: boolean;
  items: TrackedSignalSettlement[];
};

type CachedKlineEntry = {
  response: KlineResponse;
  cachedAt: number;
};

type KlineCursorState = {
  requestedCount: number;
  nextBeforeTs: string | null;
  hasMore: boolean;
};

export default function App() {
  const [watchlist, setWatchlist] = useState<WatchlistSecurityInfo[]>([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [selectedName, setSelectedName] = useState("");
  const [period, setPeriod] = useState("daily");
  const [klineData, setKlineData] = useState<KlineData[]>([]);
  const [maData, setMaData] = useState<Record<string, number[]> | null>(null);
  const [macdData, setMacdData] = useState<{
    DIF: number[];
    DEA: number[];
    MACD: number[];
  } | null>(null);
  const [bollData, setBollData] = useState<{
    MID: number[];
    UPPER: number[];
    LOWER: number[];
  } | null>(null);
  const [backtestSignals, setBacktestSignals] = useState<SignalInfo[]>([]);
  const [currentPrice, setCurrentPrice] = useState(0);
  const [realtimeMap, setRealtimeMap] = useState<Record<string, any>>({});
  const [showMA, setShowMA] = useState(true);
  const [showMACD, setShowMACD] = useState(true);
  const [showBOLL, setShowBOLL] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [autoDrawEnabled, setAutoDrawEnabled] = useState(false);
  const [autoDrawVisible, setAutoDrawVisible] = useState(true);
  const [showAutoSegments, setShowAutoSegments] = useState(true);
  const [showAutoPens, setShowAutoPens] = useState(false);
  const [autoDrawStartDate, setAutoDrawStartDate] = useState("");
  const [autoDrawHistoryLoading, setAutoDrawHistoryLoading] = useState(false);
  const [autoDrawHistoryError, setAutoDrawHistoryError] = useState<string | null>(null);
  const [autoDrawColor, setAutoDrawColor] = useState("#ffd166");
  const [autoDrawWidthLevel, setAutoDrawWidthLevel] = useState<1 | 2 | 3 | 4>(3);
  const [showDrawPanel, setShowDrawPanel] = useState(false);
  const [drawPanelPosition, setDrawPanelPosition] = useState({ left: 0, top: DRAW_PANEL_MIN_TOP });
  const [isDraggingDrawPanel, setIsDraggingDrawPanel] = useState(false);
  const [loading, setLoading] = useState(false);
  const [securityDetail, setSecurityDetail] = useState<Record<string, any> | null>(null);
  const [showInfo, setShowInfo] = useState(false);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [historyDownloadStatus, setHistoryDownloadStatus] = useState<HistoryDownloadStatus | null>(null);
  const [scanAlerts, setScanAlerts] = useState<ScanSignal[]>([]);
  const [activeReminder, setActiveReminder] = useState<ScanSignal | null>(null);
  const [trackedSignals, setTrackedSignals] = useState<TrackedSignal[]>([]);
  const [settledSignals, setSettledSignals] = useState<SettledSignal[]>([]);
  const [settlementModal, setSettlementModal] = useState<SettlementModalState>({
    visible: false,
    code: "",
    name: "",
    removedFromWatchlist: false,
    items: [],
  });
  const [sidebarTab, setSidebarTab] = useState<"watchlist" | "scan">("watchlist");
  const [shIndexQuote, setShIndexQuote] = useState<IndexQuote | null>(null);
  // 右上角实时北京时间(精确到秒),显示在上证指数左侧
  const [beijingClock, setBeijingClock] = useState("");
  const [showScanSettings, setShowScanSettings] = useState(false);
  // 分时叠加基准 + 套利监控
  const [benchChoice, setBenchChoice] = useState<string>(() => {
    try {
      return localStorage.getItem("tz_bench_choice") || "none";
    } catch {
      return "none";
    }
  });
  const [benchResolved, setBenchResolved] = useState<{ kind: BenchKind; code: string; label: string } | null>(null);
  const [benchTrends, setBenchTrends] = useState<BenchmarkTrends | null>(null);
  const [benchError, setBenchError] = useState<string | null>(null);
  const [showArbMonitor, setShowArbMonitor] = useState(false);
  const [arbReminder, setArbReminder] = useState<ArbAlert | null>(null);
  // 套利小眼睛:个股名称隐藏开关(面板里切换,弹窗横幅跟着打码)
  const [arbNamesHidden, setArbNamesHidden] = useState(isArbNameHidden);
  // 套利按钮未读角标: WS 新告警实时累加,打开面板看完关闭即清零
  const [arbUnread, setArbUnread] = useState(0);
  const [showDataDownload, setShowDataDownload] = useState(false);
  const [showUserManagement, setShowUserManagement] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [gatewayMode, setGatewayMode] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now());
  const [defaultStrategy, setDefaultStrategy] = useState("MACD_Cross");
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [loginReason, setLoginReason] = useState("");
  const [loginInitialView, setLoginInitialView] = useState<LoginModalView>("login");
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [rightPanelWidth, setRightPanelWidth] = useState(460);
  const [isResizingLayout, setIsResizingLayout] = useState(false);
  const [highlightedTrade, setHighlightedTrade] = useState<HighlightedTrade>(null);
  const [klineReloadKey, setKlineReloadKey] = useState(0);
  const [historyCursor, setHistoryCursor] = useState<KlineCursorState>({
    requestedCount: DEFAULT_KLINE_COUNT,
    nextBeforeTs: null,
    hasMore: true,
  });
  const [historyLoadInfo, setHistoryLoadInfo] = useState<{ requestId: number; prependedBars: number } | null>(null);
  const [signalDiagnosisContext, setSignalDiagnosisContext] = useState<SignalDiagnosisContext>(null);
  const [signalDiagnosisLoading, setSignalDiagnosisLoading] = useState(false);
  const [signalDiagnosisResult, setSignalDiagnosisResult] = useState<SignalDiagnosisResult | null>(null);
  const [signalDiagnosisError, setSignalDiagnosisError] = useState<string | null>(null);
  const [signalDiagnosisBarTime, setSignalDiagnosisBarTime] = useState<string>("");
  const [autoDrawDiagnosisMode, setAutoDrawDiagnosisMode] = useState<"fractal" | "segment_feature">("fractal");
  const [autoDrawDiagnosisTargetBar, setAutoDrawDiagnosisTargetBar] = useState<KlineData | null>(null);
  const [fractalDiagnosisResult, setFractalDiagnosisResult] = useState<FractalDiagnosis | null>(null);
  const [segmentFeatureDiagnosisResult, setSegmentFeatureDiagnosisResult] =
    useState<SegmentEndpointDiagnosis | null>(null);
  const [autoDrawDiagnosisError, setAutoDrawDiagnosisError] = useState<string | null>(null);
  const [autoDrawDiagnosisBarTime, setAutoDrawDiagnosisBarTime] = useState<string>("");
  const [pushResultDialog, setPushResultDialog] = useState<{ visible: boolean; success: boolean; count: number; url: string; error: string }>({ visible: false, success: false, count: 0, url: "", error: "" });
  const appBodyRef = useRef<HTMLDivElement>(null);
  const highlightTimerRef = useRef<number | null>(null);
  const reminderTimerRef = useRef<number | null>(null);
  const arbReminderTimerRef = useRef<number | null>(null);
  const selectedCodeRef = useRef("");
  const selectedNameRef = useRef("");
  const periodRef = useRef("daily");
  const historyCursorRef = useRef<KlineCursorState>({
    requestedCount: DEFAULT_KLINE_COUNT,
    nextBeforeTs: null,
    hasMore: true,
  });
  const preferredInitialKlineCountRef = useRef<number | null>(null);
  const klineDataRef = useRef<KlineData[]>([]);
  const silentKlineRefreshTimerRef = useRef<number | null>(null);
  const lastSilentKlineRefreshAtRef = useRef(0);
  const silentKlineRefreshInFlightRef = useRef(false);
  const historyLoadInFlightRef = useRef(false);
  const hasMoreMinuteHistoryRef = useRef(true);
  const previousScanRunningRef = useRef(false);
  const historyDownloadRunningRef = useRef(false);
  const klineCacheRef = useRef<Map<string, CachedKlineEntry>>(new Map());
  const klineRequestSeqRef = useRef(0);
  const prefetchingKlineKeysRef = useRef<Set<string>>(new Set());
  const watchlistPrefetchedRef = useRef(false);
  const drawPanelPositionRef = useRef(drawPanelPosition);
  const drawPanelDragRef = useRef<{
    pointerStartX: number;
    pointerStartY: number;
    panelStartLeft: number;
    panelStartTop: number;
  } | null>(null);
  const lastShowDrawPanelRef = useRef(false);

  const { lastMessage, connected, subscribe, unsubscribe } = useWebSocket(
    "/ws/realtime"
  );
  const canDownloadKline = (authUser?.username || "").toLowerCase() === "vk";
  const authRole = (authUser?.role || "user").toLowerCase();
  const authExpiryLabel = (() => {
    if (!authUser?.expires_at) return "";
    const expiresAt = new Date(authUser.expires_at);
    if (Number.isNaN(expiresAt.getTime())) return "";
    const remainingMs = expiresAt.getTime() - nowMs;
    if (remainingMs <= 0) return "（已过期）";
    if (authRole === "trial" && remainingMs < 24 * 60 * 60 * 1000) {
      return `（剩余${Math.ceil(remainingMs / (60 * 1000))}分钟）`;
    }
    return `（剩余${Math.ceil(remainingMs / (24 * 60 * 60 * 1000))}天）`;
  })();

  const autoDrawMinDate = useMemo(() => {
    if (klineData.length === 0) return "";
    return getKlineTradingDate(klineData[0]);
  }, [klineData]);

  const autoDrawMaxDate = useMemo(() => {
    if (klineData.length === 0) return "";
    return getKlineTradingDate(klineData[klineData.length - 1]);
  }, [klineData]);

  const autoDrawSourceData = useMemo(() => {
    if (period !== "5" || klineData.length === 0) {
      return [];
    }
    if (!autoDrawStartDate) {
      return klineData;
    }
    return klineData.filter((item) => getKlineTradingDate(item) >= autoDrawStartDate);
  }, [period, klineData, autoDrawStartDate]);

  const autoDrawResult = useMemo(() => {
    if (!autoDrawEnabled || period !== "5" || autoDrawSourceData.length === 0) {
      return { pens: [], segments: [], lines: [] };
    }
    return buildChanAutoDrawResult(autoDrawSourceData);
  }, [autoDrawEnabled, period, autoDrawSourceData]);

  const autoDrawLines = useMemo(() => {
    return autoDrawResult.lines.filter((line) => {
      if (line.kind === "segment") return showAutoSegments;
      if (line.kind === "pen") return showAutoPens;
      return false;
    });
  }, [autoDrawResult.lines, showAutoSegments, showAutoPens]);

  const closeFractalDiagnosisModal = useCallback(() => {
    setAutoDrawDiagnosisTargetBar(null);
    setFractalDiagnosisResult(null);
    setSegmentFeatureDiagnosisResult(null);
    setAutoDrawDiagnosisError(null);
    setAutoDrawDiagnosisBarTime("");
  }, []);

  useEffect(() => {
    drawPanelPositionRef.current = drawPanelPosition;
  }, [drawPanelPosition]);

  // 北京时间跳秒钟:按 Asia/Shanghai 时区格式化,与客户端本地时区无关
  useEffect(() => {
    const fmt = () =>
      new Date().toLocaleTimeString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    setBeijingClock(fmt());
    const timer = window.setInterval(() => setBeijingClock(fmt()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const clampDrawPanelPosition = useCallback((left: number, top: number) => {
    if (typeof window === "undefined") {
      return { left, top };
    }
    const maxLeft = Math.max(DRAW_PANEL_GUTTER, window.innerWidth - DRAW_PANEL_WIDTH - DRAW_PANEL_GUTTER);
    const maxTop = Math.max(DRAW_PANEL_MIN_TOP, window.innerHeight - 140);
    return {
      left: Math.max(DRAW_PANEL_GUTTER, Math.min(left, maxLeft)),
      top: Math.max(DRAW_PANEL_MIN_TOP, Math.min(top, maxTop)),
    };
  }, []);

  const placeDrawPanelNearBacktest = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const defaultLeft = window.innerWidth - rightPanelWidth + DRAW_PANEL_GUTTER;
    setDrawPanelPosition(
      clampDrawPanelPosition(defaultLeft, DRAW_PANEL_MIN_TOP)
    );
  }, [clampDrawPanelPosition, rightPanelWidth]);

  useEffect(() => {
    if (showDrawPanel && !lastShowDrawPanelRef.current) {
      placeDrawPanelNearBacktest();
    }
    lastShowDrawPanelRef.current = showDrawPanel;
  }, [showDrawPanel, placeDrawPanelNearBacktest]);

  useEffect(() => {
    if (!showDrawPanel) return;

    const handleResize = () => {
      setDrawPanelPosition((current) => clampDrawPanelPosition(current.left, current.top));
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [showDrawPanel, clampDrawPanelPosition]);

  useEffect(() => {
    if (!isDraggingDrawPanel) {
      return;
    }

    const handleMouseMove = (event: MouseEvent) => {
      const drag = drawPanelDragRef.current;
      if (!drag) return;
      const nextLeft = drag.panelStartLeft + (event.clientX - drag.pointerStartX);
      const nextTop = drag.panelStartTop + (event.clientY - drag.pointerStartY);
      setDrawPanelPosition(clampDrawPanelPosition(nextLeft, nextTop));
    };

    const handleMouseUp = () => {
      setIsDraggingDrawPanel(false);
      drawPanelDragRef.current = null;
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDraggingDrawPanel, clampDrawPanelPosition]);

  const handleDrawPanelHeaderMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement;
      if (target.closest("button, input, select, label")) {
        return;
      }
      drawPanelDragRef.current = {
        pointerStartX: event.clientX,
        pointerStartY: event.clientY,
        panelStartLeft: drawPanelPositionRef.current.left,
        panelStartTop: drawPanelPositionRef.current.top,
      };
      setIsDraggingDrawPanel(true);
    },
    []
  );

  selectedCodeRef.current = selectedCode;
  selectedNameRef.current = selectedName;
  periodRef.current = period;
  historyCursorRef.current = historyCursor;
  klineDataRef.current = klineData;

  const getKlineCacheKey = useCallback((code: string, name: string, p: string, count: number, beforeTs?: string | null) => {
    return `${code}|${name}|${p}|${count}|${beforeTs || "latest"}`;
  }, []);

  const getCachedKlineResponse = useCallback((code: string, name: string, p: string, count: number, beforeTs?: string | null) => {
    const key = getKlineCacheKey(code, name, p, count, beforeTs);
    const cache = klineCacheRef.current.get(key);
    if (!cache) return null;
    if (Date.now() - cache.cachedAt > KLINE_FRONTEND_CACHE_TTL_MS) {
      klineCacheRef.current.delete(key);
      return null;
    }
    klineCacheRef.current.delete(key);
    klineCacheRef.current.set(key, cache);
    return cache.response;
  }, [getKlineCacheKey]);

  const setCachedKlineResponse = useCallback((code: string, name: string, p: string, count: number, response: KlineResponse, beforeTs?: string | null) => {
    if (!response.success || !response.data) return;
    const key = getKlineCacheKey(code, name, p, count, beforeTs);
    // 指标前端会重算，入缓存时丢弃后端 indicators，控制批量预取下的内存占用
    const slimmed = { ...response, indicators: undefined };
    klineCacheRef.current.delete(key);
    klineCacheRef.current.set(key, { response: slimmed, cachedAt: Date.now() });
    while (klineCacheRef.current.size > KLINE_FRONTEND_CACHE_MAX) {
      const oldestKey = klineCacheRef.current.keys().next().value;
      if (!oldestKey) break;
      klineCacheRef.current.delete(oldestKey);
    }
  }, [getKlineCacheKey]);

  const applyKlineResponse = useCallback((res: KlineResponse, options?: { appendMode?: "replace" | "prepend" }) => {
    if (res.success && res.data) {
      const appendMode = options?.appendMode || "replace";
      const merged = appendMode === "prepend" && klineDataRef.current.length > 0
        ? [...res.data, ...klineDataRef.current]
        : res.data;
      const targetData = merged
        .filter((item, index, arr) => arr.findIndex((candidate) => candidate.timestamp === item.timestamp) === index)
        .sort((a, b) => a.timestamp - b.timestamp);
      klineDataRef.current = targetData;

      setKlineData(targetData);
      const indicators = calculateChartIndicators(targetData);
      setMaData(indicators.ma);
      setMacdData(indicators.macd);
      setBollData(indicators.boll);
      if (targetData.length > 0) {
        setCurrentPrice(targetData[targetData.length - 1].close);
      }
    }
  }, []);

  const prependMinuteHistoryOnce = useCallback(async () => {
    const code = selectedCodeRef.current;
    const name = selectedNameRef.current;
    const currentPeriod = periodRef.current;
    if (
      !code ||
      currentPeriod !== "5" ||
      historyLoadInFlightRef.current ||
      !hasMoreMinuteHistoryRef.current
    ) {
      return { prependedBars: 0, hasMore: hasMoreMinuteHistoryRef.current };
    }

    const currentCursor = historyCursorRef.current;
    const nextBeforeTs = currentCursor.nextBeforeTs;
    if (!nextBeforeTs) {
      hasMoreMinuteHistoryRef.current = false;
      const nextCursor = { ...historyCursorRef.current, hasMore: false };
      historyCursorRef.current = nextCursor;
      setHistoryCursor(nextCursor);
      return { prependedBars: 0, hasMore: false };
    }

    const pageCount = HISTORY_KLINE_STEP;
    historyLoadInFlightRef.current = true;
    const prevLength = klineDataRef.current.length;

    try {
      const cached = getCachedKlineResponse(code, name, currentPeriod, pageCount, nextBeforeTs);
      const res = cached || await fetchKline(code, name, currentPeriod, pageCount, nextBeforeTs);
      if (code !== selectedCodeRef.current || currentPeriod !== periodRef.current) {
        return { prependedBars: 0, hasMore: hasMoreMinuteHistoryRef.current };
      }

      const prependData = res.success && res.data ? res.data : [];
      const prependedBars = prependData.filter(
        (item) => !klineDataRef.current.some((existing) => existing.timestamp === item.timestamp)
      ).length;
      const nextHasMore = !!res.has_more && !!res.next_before_ts;
      hasMoreMinuteHistoryRef.current = nextHasMore;
      const nextCursor = {
        requestedCount: historyCursorRef.current.requestedCount + prependedBars,
        nextBeforeTs: res.next_before_ts ?? null,
        hasMore: nextHasMore,
      };
      historyCursorRef.current = nextCursor;
      setHistoryCursor(nextCursor);
      setHistoryLoadInfo({ requestId: Date.now(), prependedBars });

      if (!cached) {
        setCachedKlineResponse(code, name, currentPeriod, pageCount, res, nextBeforeTs);
      }
      if (prependedBars > 0 && res.success) {
        applyKlineResponse(res, { appendMode: "prepend" });
      }
      if (prependedBars === 0 || prevLength + prependedBars <= prevLength) {
        hasMoreMinuteHistoryRef.current = false;
        const exhaustedCursor = { ...historyCursorRef.current, hasMore: false };
        historyCursorRef.current = exhaustedCursor;
        setHistoryCursor(exhaustedCursor);
        return { prependedBars, hasMore: false };
      }

      return { prependedBars, hasMore: nextHasMore };
    } catch (e) {
      console.error("加载更早K线失败:", e);
      throw e;
    } finally {
      historyLoadInFlightRef.current = false;
    }
  }, [applyKlineResponse, getCachedKlineResponse, setCachedKlineResponse]);

  const loadWatchlist = useCallback(async () => {
    const res = await fetchWatchlist();
    if (res.success) {
      setWatchlist(res.data);
    }
  }, []);

  const loadTrackedSignals = useCallback(async () => {
    const res = await fetchTrackedSignals();
    if (res.success) {
      setTrackedSignals(res.data);
    }
  }, []);

  const loadSettledSignals = useCallback(async () => {
    const res = await fetchSettledSignals();
    if (res.success) {
      setSettledSignals(res.data);
    }
  }, []);

  useEffect(() => {
    if (!autoDrawStartDate) {
      setAutoDrawHistoryLoading(false);
      setAutoDrawHistoryError(null);
      return;
    }
    if (autoDrawMaxDate && autoDrawStartDate > autoDrawMaxDate) {
      setAutoDrawHistoryError(`起始日期不能晚于当前最新K线日期 ${autoDrawMaxDate}。`);
      setAutoDrawHistoryLoading(false);
      return;
    }
    if (period !== "5") {
      setAutoDrawHistoryLoading(false);
      setAutoDrawHistoryError("自动补历史仅在 5 分钟周期下生效。");
      return;
    }

    let cancelled = false;

    const ensureHistoryCoverage = async () => {
      const currentMinDate = klineDataRef.current.length > 0 ? getKlineTradingDate(klineDataRef.current[0]) : "";
      if (currentMinDate && currentMinDate <= autoDrawStartDate) {
        // #region debug-point A:history-covered
        fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"A",location:"App.tsx:556",msg:"[DEBUG] auto-draw history already covers start date",data:{autoDrawStartDate,currentMinDate,period},ts:Date.now()})}).catch(()=>{});
        // #endregion
        setAutoDrawHistoryLoading(false);
        setAutoDrawHistoryError(null);
        return;
      }

      setAutoDrawHistoryLoading(true);
      setAutoDrawHistoryError(null);

      try {
        let rounds = 0;
        while (!cancelled) {
          const loadedMinDate = klineDataRef.current.length > 0 ? getKlineTradingDate(klineDataRef.current[0]) : "";
          // #region debug-point E:history-loop
          fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"E",location:"App.tsx:568",msg:"[DEBUG] auto-draw history coverage loop",data:{autoDrawStartDate,loadedMinDate,rounds,hasMoreMinuteHistory:hasMoreMinuteHistoryRef.current,klineCount:klineDataRef.current.length},ts:Date.now()})}).catch(()=>{});
          // #endregion
          if (loadedMinDate && loadedMinDate <= autoDrawStartDate) {
            break;
          }
          if (!hasMoreMinuteHistoryRef.current) {
            break;
          }

          const result = await prependMinuteHistoryOnce();
          rounds += 1;
          // #region debug-point A:history-prepend-result
          fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"A",location:"App.tsx:577",msg:"[DEBUG] prepend minute history result",data:{rounds,prependedBars:result.prependedBars,hasMore:result.hasMore,nextBeforeTs:historyCursorRef.current.nextBeforeTs},ts:Date.now()})}).catch(()=>{});
          // #endregion
          if (result.prependedBars <= 0 || rounds >= 500) {
            break;
          }
        }

        if (cancelled) {
          return;
        }

        const loadedMinDate = klineDataRef.current.length > 0 ? getKlineTradingDate(klineDataRef.current[0]) : "";
        if (loadedMinDate && loadedMinDate <= autoDrawStartDate) {
          setAutoDrawHistoryError(null);
        } else if (!hasMoreMinuteHistoryRef.current) {
          // #region debug-point A:history-exhausted
          fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"A",location:"App.tsx:591",msg:"[DEBUG] auto-draw history exhausted before reaching start date",data:{autoDrawStartDate,loadedMinDate,hasMoreMinuteHistory:hasMoreMinuteHistoryRef.current},ts:Date.now()})}).catch(()=>{});
          // #endregion
          setAutoDrawHistoryError(`本地或接口可提供的最早 5 分钟K线只到 ${loadedMinDate || "--"}，尚未覆盖你选择的 ${autoDrawStartDate}。`);
        } else {
          // #region debug-point A:history-unfinished
          fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"A",location:"App.tsx:593",msg:"[DEBUG] auto-draw history ended in unfinished state",data:{autoDrawStartDate,loadedMinDate,hasMoreMinuteHistory:hasMoreMinuteHistoryRef.current,historyCursor:historyCursorRef.current},ts:Date.now()})}).catch(()=>{});
          // #endregion
          setAutoDrawHistoryError("自动补历史未能完成，请稍后重试。");
        }
      } catch (error: any) {
        if (!cancelled) {
          // #region debug-point A:history-error
          fetch("http://127.0.0.1:7777/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"segment-regression",runId:"pre-fix",hypothesisId:"A",location:"App.tsx:597",msg:"[DEBUG] auto-draw history load threw error",data:{message:error?.message || String(error),autoDrawStartDate,period},ts:Date.now()})}).catch(()=>{});
          // #endregion
          setAutoDrawHistoryError(error?.message || "自动加载起始日期所需历史K线失败。");
        }
      } finally {
        if (!cancelled) {
          setAutoDrawHistoryLoading(false);
        }
      }
    };

    void ensureHistoryCoverage();
    return () => {
      cancelled = true;
    };
  }, [autoDrawMaxDate, autoDrawStartDate, period, prependMinuteHistoryOnce]);

  useEffect(() => {
    if (!autoDrawStartDate || period !== "5" || klineData.length === 0) {
      return;
    }

    const loadedMinDate = getKlineTradingDate(klineData[0]);
    if (loadedMinDate && loadedMinDate <= autoDrawStartDate) {
      setAutoDrawHistoryLoading(false);
      setAutoDrawHistoryError(null);
    }
  }, [autoDrawStartDate, klineData, period]);

  const loadKline = useCallback(async () => {
    if (!selectedCode) return;
    const code = selectedCode;
    const name = selectedName;
    const currentPeriod = period;
    const count = historyCursorRef.current.requestedCount;
    const cached = getCachedKlineResponse(code, name, currentPeriod, count, null);
    const requestSeq = ++klineRequestSeqRef.current;

    if (cached) {
      applyKlineResponse(cached);
      setLoading(false);
    } else {
      setLoading(true);
    }

    try {
      const res = await fetchKline(code, name, currentPeriod, count);
      if (
        requestSeq !== klineRequestSeqRef.current ||
        code !== selectedCodeRef.current ||
        currentPeriod !== periodRef.current
      ) {
        return;
      }
      const nextCursor = {
        requestedCount: count,
        nextBeforeTs: res.next_before_ts ?? null,
        hasMore: res.has_more !== false,
      };
      historyCursorRef.current = nextCursor;
      setHistoryCursor(nextCursor);
      setCachedKlineResponse(code, name, currentPeriod, count, res, null);
      applyKlineResponse(res, { appendMode: "replace" });
    } catch (e) {
      console.error("加载K线失败:", e);
    } finally {
      if (requestSeq === klineRequestSeqRef.current) {
        setLoading(false);
      }
    }
  }, [selectedCode, selectedName, period, applyKlineResponse, getCachedKlineResponse, setCachedKlineResponse]);

  const refreshKlineSilently = useCallback(async () => {
    const code = selectedCodeRef.current;
    const name = selectedNameRef.current;
    const currentPeriod = periodRef.current;
    if (!code || silentKlineRefreshInFlightRef.current) return;

    silentKlineRefreshInFlightRef.current = true;
    try {
      const count = historyCursorRef.current.requestedCount;
      const res = await fetchKline(code, name, currentPeriod, count);
      if (code !== selectedCodeRef.current || currentPeriod !== periodRef.current) {
        return;
      }
      const nextCursor = {
        ...historyCursorRef.current,
        nextBeforeTs: res.next_before_ts ?? historyCursorRef.current.nextBeforeTs,
        hasMore: res.has_more !== false,
      };
      historyCursorRef.current = nextCursor;
      setHistoryCursor(nextCursor);
      setCachedKlineResponse(code, name, currentPeriod, count, res, null);
      applyKlineResponse(res, { appendMode: "replace" });
    } catch (e) {
      console.error("实时刷新K线失败:", e);
    } finally {
      silentKlineRefreshInFlightRef.current = false;
    }
  }, [applyKlineResponse, setCachedKlineResponse]);

  const scheduleRealtimeKlineRefresh = useCallback(() => {
    if (!selectedCodeRef.current) return;
    if (silentKlineRefreshTimerRef.current != null) return;

    const elapsed = Date.now() - lastSilentKlineRefreshAtRef.current;
    const delay = Math.max(0, REALTIME_KLINE_REFRESH_MS - elapsed);

    silentKlineRefreshTimerRef.current = window.setTimeout(() => {
      silentKlineRefreshTimerRef.current = null;
      lastSilentKlineRefreshAtRef.current = Date.now();
      refreshKlineSilently();
    }, delay);
  }, [refreshKlineSilently]);

  const loadMajorIndexQuotes = useCallback(async () => {
    const res = await fetchMajorIndexQuotes();
    if (res.success && res.data && res.data.length > 0) {
      setShIndexQuote(res.data[0]);
    }
  }, []);

  const loadSecurityDetail = useCallback(async () => {
    if (!selectedCode) return;
    const res = await fetchSecurityDetail(selectedCode, {
      name: selectedName,
      includeMargin: showInfo,
    });
    if (res.success && res.data) {
      setSecurityDetail(res.data);
    } else {
      setSecurityDetail(null);
    }
  }, [selectedCode, selectedName, showInfo]);

  const loadScanStatus = useCallback(async () => {
    const res = await fetchScanStatus();
    if (res.success) {
      setScanStatus(res.data);
      setScanAlerts(res.data.recent_signals || []);
    }
  }, []);

  const openLoginModal = useCallback((reason?: string, view: LoginModalView = "login") => {
    setLoginReason(reason || "");
    setLoginInitialView(view);
    setShowLoginModal(true);
  }, []);

  const applyAuthSession = useCallback((data: AuthSessionData) => {
    setAuthUser(data.user || null);
    setDefaultStrategy(data.default_strategy || "MACD_Cross");
    setGatewayMode(!!data.gateway);
  }, []);

  const handleLoginSuccess = useCallback((data: AuthSessionData) => {
    applyAuthSession(data);
    setLoginReason("");
    loadScanStatus();
  }, [applyAuthSession, loadScanStatus]);

  const handleLogout = useCallback(async () => {
    setShowUserMenu(false);
    const res = await logoutAuth();
    if (res.success && res.data) {
      applyAuthSession(res.data);
    } else {
      setAuthUser(null);
      setDefaultStrategy("MACD_Cross");
    }
    loadScanStatus();
  }, [applyAuthSession, loadScanStatus]);

  const loadHistoryDownloadStatus = useCallback(async () => {
    const res = await fetchHistoryDownloadStatus();
    if (res.success) {
      const wasRunning = historyDownloadRunningRef.current;
      const isRunning = !!res.data.running;
      setHistoryDownloadStatus(res.data);
      if (wasRunning && !isRunning && !res.data.error) {
        klineCacheRef.current.clear();
        lastSilentKlineRefreshAtRef.current = 0;
        setKlineReloadKey((value) => value + 1);
      }
      historyDownloadRunningRef.current = isRunning;
    }
  }, []);

  useEffect(() => {
    loadWatchlist();
    loadScanStatus();
    loadMajorIndexQuotes();
    loadTrackedSignals();
    loadSettledSignals();
  }, [loadWatchlist, loadScanStatus, loadMajorIndexQuotes, loadTrackedSignals, loadSettledSignals]);

  useEffect(() => {
    fetchAuthSession().then((res) => {
      if (res.success && res.data) {
        applyAuthSession(res.data);
        loadScanStatus();
      }
    });
  }, [applyAuthSession, loadScanStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 60 * 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!authUser) return;
    const timer = window.setInterval(() => {
      fetchAuthSession().then((res) => {
        if (res.success && res.data) {
          applyAuthSession(res.data);
          loadScanStatus();
        }
      });
    }, 30 * 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [applyAuthSession, authUser?.username, loadScanStatus]);

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current != null) {
        window.clearTimeout(highlightTimerRef.current);
      }
      if (silentKlineRefreshTimerRef.current != null) {
        window.clearTimeout(silentKlineRefreshTimerRef.current);
      }
      if (reminderTimerRef.current != null) {
        window.clearTimeout(reminderTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    let startX = 0;
    let startY = 0;
    let lastY = 0;
    let pageScrolling = false;

    const isMobileLayout = () => window.matchMedia("(max-width: 900px)").matches;

    const shouldBridgePageScroll = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false;
      if (target.closest(".etf-list, .scan-results-sidebar")) return false;
      return !!target.closest(".app-header, .sidebar-tabs, .sidebar-header, .header-center, .right-panel");
    };

    const handleTouchStart = (event: TouchEvent) => {
      if (!isMobileLayout() || event.touches.length !== 1 || !shouldBridgePageScroll(event.target)) {
        pageScrolling = false;
        return;
      }
      const touch = event.touches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      lastY = touch.clientY;
      pageScrolling = false;
    };

    const handleTouchMove = (event: TouchEvent) => {
      if (!isMobileLayout() || event.touches.length !== 1 || !shouldBridgePageScroll(event.target)) return;

      const touch = event.touches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;

      if (!pageScrolling && Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx) * 1.1) {
        pageScrolling = true;
      }

      if (!pageScrolling) return;

      window.scrollBy({ top: lastY - touch.clientY, behavior: "auto" });
      lastY = touch.clientY;
      event.preventDefault();
      event.stopPropagation();
    };

    const handleTouchEnd = () => {
      pageScrolling = false;
    };

    document.addEventListener("touchstart", handleTouchStart, { capture: true, passive: true });
    document.addEventListener("touchmove", handleTouchMove, { capture: true, passive: false });
    document.addEventListener("touchend", handleTouchEnd, { capture: true });
    document.addEventListener("touchcancel", handleTouchEnd, { capture: true });

    return () => {
      document.removeEventListener("touchstart", handleTouchStart, { capture: true });
      document.removeEventListener("touchmove", handleTouchMove, { capture: true });
      document.removeEventListener("touchend", handleTouchEnd, { capture: true });
      document.removeEventListener("touchcancel", handleTouchEnd, { capture: true });
    };
  }, []);

  useEffect(() => {
    const intervalMs = scanStatus?.running ? 1000 : 20000;
    const timer = window.setInterval(() => {
      loadScanStatus();
    }, intervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [loadScanStatus, scanStatus?.running]);

  useEffect(() => {
    const isRunning = !!scanStatus?.running;
    if (previousScanRunningRef.current && !isRunning && scanStatus?.latest_run) {
      setSidebarTab("scan");
    }
    previousScanRunningRef.current = isRunning;
  }, [scanStatus?.running, scanStatus?.latest_run?.id]);

  useEffect(() => {
    loadHistoryDownloadStatus();
    const intervalMs = historyDownloadStatus?.running ? 2000 : 10000;
    const timer = window.setInterval(() => {
      loadHistoryDownloadStatus();
    }, intervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [loadHistoryDownloadStatus, historyDownloadStatus?.running]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadMajorIndexQuotes();
    }, 15000);
    return () => {
      window.clearInterval(timer);
    };
  }, [loadMajorIndexQuotes]);

  useEffect(() => {
    lastSilentKlineRefreshAtRef.current = 0;
    historyLoadInFlightRef.current = false;
    hasMoreMinuteHistoryRef.current = true;
    const initialCount = preferredInitialKlineCountRef.current ?? getDefaultKlineCount(period);
    preferredInitialKlineCountRef.current = null;
    const initialCursor = {
      requestedCount: initialCount,
      nextBeforeTs: null,
      hasMore: true,
    };
    historyCursorRef.current = initialCursor;
    setHistoryCursor(initialCursor);
    setHistoryLoadInfo(null);
    if (silentKlineRefreshTimerRef.current != null) {
      window.clearTimeout(silentKlineRefreshTimerRef.current);
      silentKlineRefreshTimerRef.current = null;
    }
  }, [selectedCode, period]);

  const loadMoreMinuteHistory = useCallback(async () => {
    try {
      await prependMinuteHistoryOnce();
    } catch (e) {
      console.error("加载更早K线失败:", e);
    }
  }, [prependMinuteHistoryOnce]);

  const prefetchNearbyKline = useCallback(async (code: string, name: string, p: string, count: number) => {
    const key = getKlineCacheKey(code, name, p, count, null);
    if (getCachedKlineResponse(code, name, p, count, null) || prefetchingKlineKeysRef.current.has(key)) {
      return;
    }

    prefetchingKlineKeysRef.current.add(key);
    try {
      const res = await fetchKline(code, name, p, count);
      setCachedKlineResponse(code, name, p, count, res, null);
    } catch (e) {
      console.error("预加载K线失败:", e);
    } finally {
      prefetchingKlineKeysRef.current.delete(key);
    }
  }, [getCachedKlineResponse, getKlineCacheKey, setCachedKlineResponse]);

  useEffect(() => {
    loadKline();
  }, [loadKline, klineReloadKey]);

  useEffect(() => {
    if (watchlist.length === 0) return;
    const currentIndex = watchlist.findIndex((item) => item.code === selectedCode);
    if (currentIndex < 0) return;
    const baseIndex = currentIndex >= 0 ? currentIndex : 0;
    const periodToPrefetch = period;
    const count = getDefaultKlineCount(periodToPrefetch);

    const nearbyTargets = watchlist
      .slice(baseIndex + 1, baseIndex + 1 + PREFETCH_NEARBY_WATCHLIST_COUNT)
      .map((item) => ({ code: item.code, name: item.name }));

    nearbyTargets.forEach((item, idx) => {
      window.setTimeout(() => {
        prefetchNearbyKline(item.code, item.name, periodToPrefetch, count);
      }, 120 * (idx + 1));
    });
  }, [watchlist, selectedCode, period, prefetchNearbyKline]);

  // 首次拿到自选列表后，串行预取所有自选股 × 常用周期的默认可见K线（仅首屏窗口，
  // 缩放/翻页触发的动态历史请求不预取）。串行执行保证同时只有一个预取请求在途，
  // 不与用户点击图表触发的实时请求抢占浏览器的并发连接。
  useEffect(() => {
    if (watchlist.length === 0 || watchlistPrefetchedRef.current) return;
    watchlistPrefetchedRef.current = true;

    const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
    void (async () => {
      await wait(KLINE_PREFETCH_INITIAL_DELAY_MS);
      for (const item of watchlist) {
        for (const p of KLINE_PREFETCH_PERIODS) {
          await prefetchNearbyKline(item.code, item.name, p, getDefaultKlineCount(p));
          await wait(KLINE_PREFETCH_STAGGER_MS);
        }
      }
    })();
  }, [watchlist, prefetchNearbyKline]);

  useEffect(() => {
    loadSecurityDetail();
  }, [loadSecurityDetail]);

  useEffect(() => {
    if (watchlist.length === 0) return;
    if (!selectedCode) {
      setSelectedCode(watchlist[0].code);
      setSelectedName(watchlist[0].name);
      return;
    }

    const current = watchlist.find((item) => item.code === selectedCode);
    if (!current) {
      return;
    }

    if (current.name !== selectedName) {
      setSelectedName(current.name);
    }
  }, [watchlist, selectedCode, selectedName]);

  // 订阅 = 选中股 + 全部自选:后端推送循环把所有客户端的订阅并集合并成一次批量
  // pytdx 查价,多订阅代码不增加上游请求;只订选中股的话,自选列表其余行会整场
  // 僵死在挂载时的价格
  useEffect(() => {
    const codes = Array.from(
      new Set([selectedCode, ...watchlist.map((item) => item.code)].filter((c): c is string => Boolean(c)))
    );
    if (codes.length > 0) {
      subscribe(codes);
    }
    return () => {
      unsubscribe();
    };
  }, [selectedCode, watchlist, subscribe, unsubscribe]);

  // K线静默刷新只由上方 WS quotes 推送触发，一旦推送断连/消息里没有当前标的
  // （或标签页隔夜未刷新），主图会停留在首屏数据一整天。加低频轮询与页面聚焦
  // 兜底：scheduleRealtimeKlineRefresh 内部仍有 15 秒节流与在途请求去重，不会
  // 与 WS 触发的刷新叠加打爆请求。
  useEffect(() => {
    const maybeRefresh = () => {
      if (document.visibilityState === "visible" && isLikelyTradingTime()) {
        scheduleRealtimeKlineRefresh();
      }
    };
    const pollTimer = window.setInterval(maybeRefresh, KLINE_FALLBACK_POLL_MS);
    document.addEventListener("visibilitychange", maybeRefresh);
    window.addEventListener("focus", maybeRefresh);
    return () => {
      window.clearInterval(pollTimer);
      document.removeEventListener("visibilitychange", maybeRefresh);
      window.removeEventListener("focus", maybeRefresh);
    };
  }, [scheduleRealtimeKlineRefresh]);

  useEffect(() => {
    if (lastMessage?.type === "quotes" && lastMessage.data) {
      const map: Record<string, any> = {};
      lastMessage.data.forEach((q: any) => {
        map[q.code] = q;
      });
      setRealtimeMap((prev) => ({ ...prev, ...map }));

      const current = map[selectedCode];
      if (current) {
        setCurrentPrice(current.price);
        scheduleRealtimeKlineRefresh();
      }
    }
    if (lastMessage?.type === "scan_alerts" && Array.isArray(lastMessage.data) && lastMessage.data.length > 0) {
      const incoming: ScanSignal[] = lastMessage.data;
      setScanAlerts((prev) => {
        const merged = [...incoming, ...prev];
        const deduped = merged.filter((item, index, arr) => {
          const key = `${item.code}-${item.direction}-${item.signal_time}-${item.strategy_name}`;
          return arr.findIndex((candidate) => (
            `${candidate.code}-${candidate.direction}-${candidate.signal_time}-${candidate.strategy_name}` === key
          )) === index;
        });
        return deduped.slice(0, 50);
      });
      setSidebarTab("scan");
      setActiveReminder(incoming[0]);
      if (reminderTimerRef.current != null) {
        window.clearTimeout(reminderTimerRef.current);
      }
      reminderTimerRef.current = window.setTimeout(() => {
        setActiveReminder(null);
        reminderTimerRef.current = null;
      }, 8000);
      loadScanStatus();
    }
    if (lastMessage?.type === "arb_alerts" && Array.isArray(lastMessage.data) && lastMessage.data.length > 0) {
      const incomingArb: ArbAlert[] = lastMessage.data;
      setArbReminder(incomingArb[0]);
      setArbUnread((prev) => prev + incomingArb.length);
      playArbAlertSound(incomingArb[0].direction);
      if (arbReminderTimerRef.current != null) {
        window.clearTimeout(arbReminderTimerRef.current);
      }
      arbReminderTimerRef.current = window.setTimeout(() => {
        setArbReminder(null);
        arbReminderTimerRef.current = null;
      }, 8000);
    }
  }, [lastMessage, selectedCode, scheduleRealtimeKlineRefresh, loadScanStatus]);

  // 套利角标初始未读数: 挂载时取一次,之后靠 WS 累加(断线重连也不丢,刷新页面重新校准)
  useEffect(() => {
    let cancelled = false;
    fetchArbStatus()
      .then((res) => {
        if (!cancelled && res.success && res.data) {
          setArbUnread((res.data.alerts || []).filter((item) => !item.is_read).length);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // 套利小眼睛开关联动:面板切换时刷新本组件,弹窗横幅实时打码/还原
  useEffect(() => onArbNameHiddenChange(() => setArbNamesHidden(isArbNameHidden())), []);

  // 分时叠加: 预设 → {kind,code,label}(板块类预设走后端在线解析)
  useEffect(() => {
    try {
      localStorage.setItem("tz_bench_choice", benchChoice);
    } catch {}
    const preset = BENCH_PRESETS.find((item) => item.key === benchChoice);
    if (!preset || preset.key === "none") {
      setBenchResolved(null);
      setBenchError(null);
      return;
    }
    if (preset.kind && preset.code) {
      setBenchResolved({ kind: preset.kind, code: preset.code, label: preset.label });
      setBenchError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const keyword = preset.searchKeyword || preset.label;
      try {
        const res = await searchBenchmarks(keyword);
        if (cancelled) return;
        const candidates = res.data || [];
        const hit = candidates.find((item) => item.kind === "em_board") || candidates[0];
        if (hit) {
          setBenchResolved({ kind: hit.kind, code: hit.code, label: hit.label || preset.label });
          setBenchError(null);
        } else {
          setBenchResolved(null);
          setBenchError(`未解析到"${keyword}"的板块基准代码`);
        }
      } catch {
        if (!cancelled) {
          setBenchResolved(null);
          setBenchError("板块基准解析请求失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [benchChoice]);

  // 分时叠加: 基准曲线拉取(交易时段 15s 轮询刷新)
  useEffect(() => {
    if (period !== "intraday" || !benchResolved) {
      setBenchTrends(null);
      return;
    }
    let cancelled = false;
    let busy = false;
    const load = async () => {
      if (busy) return;
      busy = true;
      try {
        const res = await fetchBenchmarkTrends(benchResolved.kind, benchResolved.code, benchResolved.label);
        if (cancelled) return;
        if (res.success && res.data && res.data.points.length > 0) {
          setBenchTrends(res.data);
          setBenchError(null);
        } else if (!res.success) {
          setBenchError(res.message || "基准数据不可用");
        }
      } catch {
        if (!cancelled) {
          setBenchError("基准数据请求失败");
        }
      } finally {
        busy = false;
      }
    };
    load();
    const timer = window.setInterval(() => {
      if (isLikelyTradingTime()) {
        load();
      }
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [period, benchResolved]);

  // 叠加归一化用的个股昨收: 详情优先,实时报价兜底;取不到就不进叠加模式
  const stockPctBase = useMemo(() => {
    const fromDetail = Number(securityDetail?.prev_close);
    if (Number.isFinite(fromDetail) && fromDetail > 0) return fromDetail;
    const fromQuote = Number(realtimeMap[selectedCode]?.pre_close);
    if (Number.isFinite(fromQuote) && fromQuote > 0) return fromQuote;
    return null;
  }, [securityDetail, realtimeMap, selectedCode]);

  const handleSaveScanSettings = useCallback(async (params: {
    enabled?: boolean;
    strategy_name?: string;
    interval_minutes?: number;
    scan_scope_type?: string;
    scan_scope_codes?: string[];
    scan_focus_codes?: string[];
    scan_period?: string;
    auto_download_enabled?: boolean;
    auto_download_hour?: number;
    kline_force_refresh?: boolean;
  }) => {
    const res = await saveScanSettings(params);
    if (res.success) {
      setScanStatus(res.data);
      setScanAlerts(res.data.recent_signals || []);
      return;
    }
    const message = (res as any).message || "保存扫描设置失败";
    if ((res as any).status === 401 || /登录/.test(message)) {
      openLoginModal(message);
    } else {
      setPushResultDialog({ visible: true, success: false, count: 0, url: "", error: message });
    }
    throw new Error(message);
  }, [openLoginModal]);

  const handleRunScanNow = useCallback(async () => {
    setScanStatus((prev) => prev ? { ...prev, running: true, current_message: "正在启动扫描..." } : prev);
    const res = await runScanNow();
    if (res.success) {
      setScanStatus(res.data.status);
      setScanAlerts(res.data.status.recent_signals || []);
      return;
    }
    const message = (res as any).message || "启动扫描失败";
    setScanStatus((prev) => prev ? { ...prev, running: false, current_message: message } : prev);
    if ((res as any).status === 401 || /登录/.test(message)) {
      openLoginModal(message);
    } else {
      alert(message);
    }
    throw new Error(message);
  }, [openLoginModal]);

  const handleMarkScanRead = useCallback(async (ids: number[]) => {
    if (ids.length === 0) return;
    const res = await markScanSignalsRead(ids);
    if (res.success) {
      setScanAlerts((prev) => prev.filter((item) => !(item.id && ids.includes(item.id))));
      setScanStatus((prev) => prev ? {
        ...prev,
        recent_signals: prev.recent_signals.filter((item) => !(item.id && ids.includes(item.id))),
        unread_count: prev.recent_signals.filter((item) => !(item.id && ids.includes(item.id))).length,
      } : prev);
    } else if ((res as any).status === 401) {
      openLoginModal((res as any).message || "请先登录后再删除扫描结果");
    } else if (!res.success) {
      alert(res.message || "删除扫描结果失败");
    }
  }, [openLoginModal]);

  const handleDeleteScanRun = useCallback(async (runId: number) => {
    try {
      const res = await deleteScanRun(runId);
      if (!res.success) {
        if ((res as any).status === 401) {
          openLoginModal((res as any).message || "请先登录后再删除扫描结果");
        } else {
          alert(res.message || "删除扫描结果失败");
        }
        return;
      }
      await loadScanStatus();
    } catch {
      alert("删除扫描结果失败，请重试");
    }
  }, [loadScanStatus, openLoginModal]);

  const handlePushScanRun = useCallback(async (runId: number) => {
    const res = await pushScanRunToMarketMap(runId);
    if (res.success && res.data?.market_map_url) {
      setPushResultDialog({ visible: true, success: true, count: res.data.pushed_count || 0, url: res.data.market_map_url, error: "" });
      await loadScanStatus();
      return;
    }
    const message = (res as any).message || "推送到大盘云图失败";
    if ((res as any).status === 401 || /登录/.test(message)) {
      openLoginModal(message);
    } else {
      setPushResultDialog({ visible: true, success: false, count: 0, url: "", error: message });
    }
    throw new Error(message);
  }, [loadScanStatus, openLoginModal]);

  const handleStartHistoryDownload = useCallback(async (params: {
    periods: string[];
    force_refresh?: boolean;
    codes?: string[];
    time_span?: string;
  }) => {
    if (!canDownloadKline) {
      alert("目前只有管理员能下载 K 线数据。");
      return;
    }
    const res = await startHistoryDownload(params);
    if (res.success && res.data) {
      setHistoryDownloadStatus(res.data);
    } else {
      await loadHistoryDownloadStatus();
    }
  }, [canDownloadKline, loadHistoryDownloadStatus, openLoginModal]);

  const handleTrackSignal = useCallback(async (signal: ScanSignal) => {
    if (!signal.id) return;
    const res = await trackSignal(signal.id);
    if (res.success) {
      loadTrackedSignals();
      loadWatchlist();
    } else {
      const message = (res as any).message || "跟踪失败";
      if ((res as any).status === 401 || /登录/.test(message)) {
        openLoginModal(message);
      } else {
        alert(message);
      }
    }
  }, [loadTrackedSignals, loadWatchlist, openLoginModal]);

  const handleUntrackSignal = useCallback(async (trackedIds: number[], removeFromWatchlist: boolean = false) => {
    if (!trackedIds.length) return;
    const settlements: TrackedSignalSettlement[] = [];
    let settlementCode = "";
    let settlementName = "";
    for (const trackedId of trackedIds) {
      const res = await untrackSignal(trackedId, removeFromWatchlist);
      if (!res.success || !res.data?.settlement) {
        const message = (res as any).message || "取消跟踪失败";
        if ((res as any).status === 401 || /登录/.test(message)) {
          openLoginModal(message);
        } else {
          alert(message);
        }
        return;
      }
      settlementCode = res.data.code || settlementCode;
      settlementName = res.data.name || settlementName;
      settlements.push(res.data.settlement);
    }
    setSettlementModal({
      visible: settlements.length > 0,
      code: settlementCode,
      name: settlementName,
      removedFromWatchlist: removeFromWatchlist,
      items: settlements,
    });
    loadTrackedSignals();
    loadWatchlist();
    loadSettledSignals();
  }, [loadTrackedSignals, loadWatchlist, loadSettledSignals, openLoginModal]);

  const handleSelectSettledSignal = useCallback((settled: SettledSignal) => {
    if (highlightTimerRef.current != null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    // 切到该股票及信号对应周期
    setSelectedCode(settled.code);
    setSelectedName(settled.name);
    const targetPeriod = normalizeSignalChartPeriod(settled.period);
    setPeriod(targetPeriod);
    periodRef.current = targetPeriod;
    setHighlightedTrade(null);
    setSignalDiagnosisContext({
      source: "scan",
      strategyName: settled.strategy_name,
    });
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");

    // 买点 = 跟踪时记录的 signal，卖点 = 结束跟踪时的 exit
    const buyTs = parseChartTimestampText(settled.signal_time) ?? 0;
    const sellTs = parseChartTimestampText(settled.exit_time) ?? 0;
    const markerSignals: SignalInfo[] = [];
    if (buyTs > 0) {
      markerSignals.push({
        direction: "buy",
        price: settled.signal_price,
        time: settled.signal_time,
        reason: settled.reason,
        timestamp: buyTs,
      });
    }
    if (sellTs > 0) {
      markerSignals.push({
        direction: "sell",
        price: settled.exit_price,
        time: settled.exit_time,
        reason: `结束跟踪 收益 ${settled.return_pct > 0 ? "+" : ""}${settled.return_pct.toFixed(2)}%`,
        timestamp: sellTs,
      });
    }
    setBacktestSignals(markerSignals);

    // 高亮卖点（结束跟踪点），让用户一眼定位这段历史
    if (sellTs > 0) {
      setHighlightedTrade({ timestamp: sellTs, direction: "sell" });
      highlightTimerRef.current = window.setTimeout(() => {
        setHighlightedTrade(null);
        highlightTimerRef.current = null;
      }, 2600);
    }
  }, []);

  const handleSelectWatchlistSecurity = (code: string) => {
    if (code === selectedCodeRef.current) return;
    if (highlightTimerRef.current != null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    setSelectedCode(code);
    setBacktestSignals([]);
    setHighlightedTrade(null);
    setSignalDiagnosisContext(null);
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");
    const security = watchlist.find((item) => item.code === code);
    if (security) {
      setSelectedName(security.name);
    }
    const codeTrackedSignals = trackedSignals.filter((t) => t.code === code);
    if (codeTrackedSignals.length > 0) {
      const signalInfos: SignalInfo[] = codeTrackedSignals.map((t) => ({
        direction: t.direction,
        price: t.signal_price,
        time: t.signal_time,
        reason: t.reason,
        timestamp: parseChartTimestampText(t.signal_time) ?? 0,
      }));
      setBacktestSignals(signalInfos);
      setSignalDiagnosisContext({
        source: "scan",
        strategyName: codeTrackedSignals[0].strategy_name,
      });
    }
  };

  const handleSelectScanSignal = useCallback((signal: ScanSignal) => {
    if (highlightTimerRef.current != null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    setSelectedCode(signal.code);
    setSelectedName(signal.name);
    const targetPeriod = normalizeSignalChartPeriod(signal.period);
    setPeriod(targetPeriod);
    periodRef.current = targetPeriod;
    setShowScanSettings(false);
    setSignalDiagnosisContext({
      source: "scan",
      strategyName: signal.strategy_name,
    });
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");

    // 将该股票所有同策略的扫描信号标注到K线上
    const sameCodeSignals = scanAlerts.filter(
      (s) => s.code === signal.code && s.strategy_name === signal.strategy_name && normalizeSignalChartPeriod(s.period) === targetPeriod
    );
    const scanSignalInfos: SignalInfo[] = sameCodeSignals.map((s) => {
      const ts = parseChartTimestampText(s.signal_time) ?? 0;
      return {
        direction: s.direction,
        price: s.price,
        time: s.signal_time,
        reason: s.reason,
        timestamp: ts,
      };
    });
    setBacktestSignals(scanSignalInfos);

    // 高亮点击的那条信号
    const ts = parseChartTimestampText(signal.signal_time) ?? 0;
    if (ts > 0) {
      setHighlightedTrade({ timestamp: ts, direction: signal.direction });
      highlightTimerRef.current = window.setTimeout(() => {
        setHighlightedTrade(null);
        highlightTimerRef.current = null;
      }, 2600);
    }
  }, [scanAlerts]);

  const handleSelectPeriod = (p: string) => {
    setPeriod(p);
    setBacktestSignals([]);
    setHighlightedTrade(null);
    setSignalDiagnosisContext(null);
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");
  };

  const highlightBacktestTrade = useCallback((trade: TradeRecordItem) => {
    const ts =
      trade.timestamp ??
      trade.signal_timestamp ??
      parseChartTimestampText(trade.signal_time || "") ??
      parseChartTimestampText(trade.date);
    if (ts == null) return;

    if (highlightTimerRef.current != null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }

    setHighlightedTrade({
      timestamp: ts,
      direction: trade.direction,
    });

    highlightTimerRef.current = window.setTimeout(() => {
      setHighlightedTrade((current) => {
        if (!current) return current;
        return current.timestamp === ts && current.direction === trade.direction ? null : current;
      });
      highlightTimerRef.current = null;
    }, 2600);
  }, []);

  const applyBacktestChartContext = useCallback((params: {
    code?: string;
    name?: string;
    period?: string;
    barCount?: number;
    strategyName?: string;
    rangeStart?: string;
    rangeEnd?: string;
    tradeRecords?: TradeRecordItem[];
  }, focusTrade?: TradeRecordItem | null) => {
    const resultPeriod = params.period || periodRef.current;
    const backtestCount = Math.max(
      getDefaultKlineCount(resultPeriod),
      (params.barCount || 0) + 20
    );
    preferredInitialKlineCountRef.current = backtestCount;
    const nextCursor = {
      requestedCount: backtestCount,
      nextBeforeTs: null,
      hasMore: true,
    };
    historyCursorRef.current = nextCursor;
    setHistoryCursor(nextCursor);
    setHistoryLoadInfo(null);
    hasMoreMinuteHistoryRef.current = true;

    if (params.code) {
      setSelectedCode(params.code);
    }
    if (params.name) {
      setSelectedName(params.name);
    }
    if (params.period) {
      setPeriod(params.period);
      periodRef.current = params.period;
    }
    setKlineReloadKey((value) => value + 1);

    if (params.tradeRecords) {
      const bSignals: SignalInfo[] = params.tradeRecords.map(t => {
        const ts =
          t.timestamp ??
          t.signal_timestamp ??
          parseChartTimestampText(t.signal_time || "") ??
          parseChartTimestampText(t.date) ??
          0;
        return {
          direction: t.direction,
          price: t.price,
          time: String(ts),
          reason: t.reason ? `${t.reason}; 成交: ${t.price} x ${t.size}` : `回测成交: ${t.price} x ${t.size}`,
          size: t.size,
          amount: t.value,
          commission: t.commission,
          timestamp: ts,
        };
      });
      setBacktestSignals(bSignals);
      setHighlightedTrade(null);
      if (focusTrade) {
        highlightBacktestTrade(focusTrade);
      }
    } else {
      setBacktestSignals([]);
      setHighlightedTrade(null);
    }

    if (params.strategyName && params.rangeStart && params.rangeEnd) {
      setSignalDiagnosisContext({
        source: "backtest",
        strategyName: params.strategyName,
        rangeStart: params.rangeStart,
        rangeEnd: params.rangeEnd,
      });
    } else {
      setSignalDiagnosisContext(null);
    }
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");
  }, [highlightBacktestTrade]);

  const handleBacktestComplete = (result: BacktestResult) => {
    if (result.mode === "batch") {
      setBacktestSignals([]);
      setHighlightedTrade(null);
      setSignalDiagnosisContext(null);
      setSignalDiagnosisResult(null);
      setSignalDiagnosisError(null);
      setSignalDiagnosisBarTime("");
      return;
    }
    applyBacktestChartContext({
      period: result.period,
      barCount: result.bar_count,
      strategyName: result.strategy_name,
      rangeStart: result.range_start,
      rangeEnd: result.range_end,
      tradeRecords: result.trade_records,
    });
  };

  const handleClearBacktestSignals = () => {
    if (highlightTimerRef.current != null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
    setBacktestSignals([]);
    setHighlightedTrade(null);
    setSignalDiagnosisContext(null);
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");
  };

  const closeSignalDiagnosisModal = useCallback(() => {
    setSignalDiagnosisLoading(false);
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);
    setSignalDiagnosisBarTime("");
  }, []);

  const runAutoDrawDiagnosis = useCallback((bar: KlineData, mode: "fractal" | "segment_feature") => {
    setFractalDiagnosisResult(null);
    setSegmentFeatureDiagnosisResult(null);
    setAutoDrawDiagnosisError(null);

    if (period !== "5") {
      setAutoDrawDiagnosisError("自动画线诊断仅在 5 分钟周期下可用，请先切换到 5 分钟周期。");
      return;
    }

    try {
      if (mode === "fractal") {
        const diagnosis = diagnoseFractal(
          klineDataRef.current,
          bar.timestamp,
          bar.time,
          autoDrawStartDate || undefined
        );
        setFractalDiagnosisResult(diagnosis);
        return;
      }

      const diagnosis = diagnoseSegmentEndpoint(
        klineDataRef.current,
        bar.timestamp,
        bar.time,
        autoDrawStartDate || undefined
      );
      setSegmentFeatureDiagnosisResult(diagnosis);
    } catch (error: any) {
      console.error("自动画线诊断失败:", error);
      setAutoDrawDiagnosisError(error?.message || "自动画线诊断失败，请重试。");
    }
  }, [autoDrawStartDate, period]);

  const handleSelectAutoDrawDiagnosisMode = useCallback((mode: "fractal" | "segment_feature") => {
    setAutoDrawDiagnosisMode(mode);
    if (autoDrawDiagnosisTargetBar) {
      runAutoDrawDiagnosis(autoDrawDiagnosisTargetBar, mode);
    }
  }, [autoDrawDiagnosisTargetBar, runAutoDrawDiagnosis]);

  const handleDiagnoseSignalBar = useCallback(async (bar: KlineData) => {
    const diagnosisBarTime = formatDiagnosisBarTime(bar);
    if (autoDrawEnabled) {
      closeSignalDiagnosisModal();
      setAutoDrawDiagnosisTargetBar(bar);
      setAutoDrawDiagnosisBarTime(diagnosisBarTime);
      runAutoDrawDiagnosis(bar, autoDrawDiagnosisMode);
      return;
    }

    closeFractalDiagnosisModal();
    setSignalDiagnosisBarTime(diagnosisBarTime);
    setSignalDiagnosisResult(null);
    setSignalDiagnosisError(null);

    if (!signalDiagnosisContext) {
      setSignalDiagnosisError("请先完成一次回测，或从扫描结果中进入图表后，再双击K线查看原因。");
      return;
    }

    setSignalDiagnosisLoading(true);
    try {
      const res = await fetchSignalDiagnosis({
        source: signalDiagnosisContext.source,
        code: selectedCode,
        name: selectedName,
        period,
        strategy_name: signalDiagnosisContext.strategyName,
        target_timestamp: bar.timestamp,
        range_start: signalDiagnosisContext.source === "backtest" ? signalDiagnosisContext.rangeStart : undefined,
        range_end: signalDiagnosisContext.source === "backtest" ? signalDiagnosisContext.rangeEnd : undefined,
      });
      if (res.success && res.data) {
        setSignalDiagnosisResult(res.data);
        setSignalDiagnosisError(null);
      } else {
        setSignalDiagnosisError(res.message || "诊断失败");
      }
    } catch (error: any) {
      setSignalDiagnosisError(error?.message || "诊断失败");
    } finally {
      setSignalDiagnosisLoading(false);
    }
  }, [
    autoDrawEnabled,
    autoDrawDiagnosisMode,
    autoDrawStartDate,
    closeFractalDiagnosisModal,
    closeSignalDiagnosisModal,
    period,
    runAutoDrawDiagnosis,
    selectedCode,
    selectedName,
    signalDiagnosisContext,
  ]);

  const closeAllDiagnosisModals = useCallback(() => {
    closeSignalDiagnosisModal();
    closeFractalDiagnosisModal();
  }, [closeSignalDiagnosisModal, closeFractalDiagnosisModal]);

  const handleToggleAutoDraw = useCallback(() => {
    setAutoDrawEnabled((value) => {
      const next = !value;
      if (!next) {
        setAutoDrawVisible(true);
        closeFractalDiagnosisModal();
      } else {
        closeSignalDiagnosisModal();
      }
      return next;
    });
  }, [closeFractalDiagnosisModal, closeSignalDiagnosisModal]);

  const handleSelectBacktestTrade = (trade: TradeRecordItem) => {
    highlightBacktestTrade(trade);
  };

  const handleInspectBatchDetail = useCallback((detail: BatchExtremeDetail, focusTrade?: TradeRecordItem) => {
    applyBacktestChartContext(
      {
        code: detail.code,
        name: detail.name,
        period: detail.period,
        barCount: detail.bar_count,
        strategyName: detail.strategy_name,
        rangeStart: detail.range_start,
        rangeEnd: detail.range_end,
        tradeRecords: detail.trade_records,
      },
      focusTrade ?? null
    );
  }, [applyBacktestChartContext]);

  const formatMarketValue = (v: number | null | undefined) => {
    if (v == null || isNaN(v)) return "--";
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(2) + "万";
    return v.toFixed(2);
  };

  const formatCapitalAmount = (v: number | null | undefined) => {
    if (v == null || isNaN(v)) return "--";
    const abs = Math.abs(v);
    const sign = v > 0 ? "+" : v < 0 ? "-" : "";
    if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`;
    if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(2)}万`;
    return `${sign}${abs.toFixed(2)}`;
  };

  const renderMarginTrend = (series: Array<{ date: string; net_inflow?: number | null }> | undefined) => {
    if (!series || series.length === 0) return null;
    const values = series.map((item) => item.net_inflow ?? 0);
    const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);

    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 6 }}>最近30天融资净流入走势</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 52 }}>
          {series.map((item) => {
            const value = item.net_inflow ?? 0;
            const height = Math.max(4, Math.round((Math.abs(value) / maxAbs) * 42));
            return (
              <div
                key={item.date}
                title={`${item.date} ${formatCapitalAmount(value)}`}
                style={{
                  flex: 1,
                  minWidth: 4,
                  height,
                  borderRadius: 2,
                  background: value >= 0 ? "#ef5350" : "#26a69a",
                  opacity: value === 0 ? 0.45 : 0.9,
                }}
              />
            );
          })}
        </div>
      </div>
    );
  };

  useEffect(() => {
    if (!isResizingLayout) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!appBodyRef.current) return;
      const rect = appBodyRef.current.getBoundingClientRect();
      const nextWidth = rect.right - e.clientX;
      const minWidth = 420;
      const maxWidth = Math.max(minWidth, rect.width - 380);
      setRightPanelWidth(Math.max(minWidth, Math.min(nextWidth, maxWidth)));
    };

    const handleMouseUp = () => {
      setIsResizingLayout(false);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizingLayout]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1 className="app-title">TrendZen</h1>
          <span className={`ws-status ${connected ? "connected" : "disconnected"}`}>
            {connected ? "● 已连接" : "○ 未连接"}
          </span>
          <NodeStatusChip />
          <span className="app-author" title="by vk">by vk</span>
          <button className="header-settings-btn" onClick={() => setShowScanSettings(true)}>
            <span className="btn-text">扫描设置</span>
          </button>
          <button
            className={`header-settings-btn ${arbUnread > 0 ? "arb-alert-btn" : ""}`}
            onClick={() => setShowArbMonitor(true)}
            type="button"
          >
            <span className="btn-text">套利监控</span>
            {arbUnread > 0 && (
              <span className="arb-alert-badge">{arbUnread > 99 ? "99+" : arbUnread}</span>
            )}
          </button>
          <button 
            className={`header-settings-btn ${historyDownloadStatus?.running ? 'progress-btn' : ''}`} 
            onClick={() => setShowDataDownload(true)}
            style={historyDownloadStatus?.running ? {
              '--progress-width': `${historyDownloadStatus?.progress_pct || 0}%`
            } as any : {}}
          >
            <span className="btn-text">
              {historyDownloadStatus?.running 
                ? `数据下载 ${historyDownloadStatus?.progress_pct || 0}%` 
                : "数据下载"}
            </span>
          </button>
          {canDownloadKline && (
            <button className="header-settings-btn" onClick={() => setShowUserManagement(true)} type="button">
              <span className="btn-text">用户管理</span>
            </button>
          )}
        </div>
        <div className="header-center" style={{ position: "relative" }}>
          <span className="current-security">
            {selectedName} ({selectedCode})
          </span>
          <span
            className="info-icon"
            onClick={() => setShowInfo(!showInfo)}
            title="标的详情"
            style={{
              cursor: "pointer",
              marginLeft: 4,
              fontSize: 13,
              color: "#8b949e",
              fontWeight: 700,
              userSelect: "none",
            }}
          >
            ⓘ
          </span>
          <span className="current-price-display" style={{
            color: currentPrice > 0 ? (
              realtimeMap[selectedCode]?.change_pct > 0 ? "#ef5350" :
              realtimeMap[selectedCode]?.change_pct < 0 ? "#26a69a" : "#d1d4dc"
            ) : "#d1d4dc"
          }}>
            {currentPrice ? currentPrice.toFixed(3) : "--"}
          </span>
          {realtimeMap[selectedCode]?.change_pct !== undefined && (
            <span style={{
              color: realtimeMap[selectedCode].change_pct > 0 ? "#ef5350" :
                     realtimeMap[selectedCode].change_pct < 0 ? "#26a69a" : "#d1d4dc",
              marginLeft: 8,
            }}>
              {realtimeMap[selectedCode].change_pct > 0 ? "+" : ""}
              {realtimeMap[selectedCode].change_pct.toFixed(2)}%
            </span>
          )}
          {showInfo && securityDetail && (
            <div className="security-info-popup">
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <strong>{securityDetail.name} ({securityDetail.code})</strong>
                <span style={{ cursor: "pointer", color: "#8b949e" }} onClick={() => setShowInfo(false)}>✕</span>
              </div>
              <div className="info-grid">
                <div><span className="info-label">最新价</span><span>{securityDetail.price?.toFixed(3) || "--"}</span></div>
                <div><span className="info-label">涨跌幅</span><span style={{ color: (securityDetail.change_pct || 0) > 0 ? "#ef5350" : (securityDetail.change_pct || 0) < 0 ? "#26a69a" : "#d1d4dc" }}>{securityDetail.change_pct?.toFixed(2) || "--"}%</span></div>
                <div><span className="info-label">IOPV估值</span><span>{securityDetail.iopv?.toFixed(3) || "--"}</span></div>
                <div><span className="info-label">溢价率</span><span style={{ color: (securityDetail.premium_rate || 0) > 0 ? "#ef5350" : (securityDetail.premium_rate || 0) < 0 ? "#26a69a" : "#d1d4dc" }}>{securityDetail.premium_rate != null ? securityDetail.premium_rate.toFixed(3) + "%" : "--"}</span></div>
                <div><span className="info-label">换手率</span><span>{securityDetail.turnover_rate?.toFixed(2) || "--"}%</span></div>
                <div><span className="info-label">总市值</span><span>{formatMarketValue(securityDetail.total_mv)}</span></div>
                <div><span className="info-label">今开</span><span>{securityDetail.open?.toFixed(3) || "--"}</span></div>
                <div><span className="info-label">最高</span><span>{securityDetail.high?.toFixed(3) || "--"}</span></div>
                <div><span className="info-label">最低</span><span>{securityDetail.low?.toFixed(3) || "--"}</span></div>
                <div><span className="info-label">昨收</span><span>{securityDetail.prev_close?.toFixed(3) || "--"}</span></div>
              </div>
              {securityDetail.margin_profile && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #2a2a3e" }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>融资信息</div>
                  <div className="info-grid">
                    <div><span className="info-label">最新日期</span><span>{securityDetail.margin_profile.latest_trade_date || "--"}</span></div>
                    <div><span className="info-label">当日净流入</span><span style={{ color: (securityDetail.margin_profile.latest_net_inflow || 0) > 0 ? "#ef5350" : (securityDetail.margin_profile.latest_net_inflow || 0) < 0 ? "#26a69a" : "#d1d4dc" }}>{formatCapitalAmount(securityDetail.margin_profile.latest_net_inflow)}</span></div>
                    <div><span className="info-label">融资余额</span><span>{formatCapitalAmount(securityDetail.margin_profile.latest_financing_balance)}</span></div>
                    <div><span className="info-label">30天净流入</span><span style={{ color: (securityDetail.margin_profile.rolling_net_inflow_30d || 0) > 0 ? "#ef5350" : (securityDetail.margin_profile.rolling_net_inflow_30d || 0) < 0 ? "#26a69a" : "#d1d4dc" }}>{formatCapitalAmount(securityDetail.margin_profile.rolling_net_inflow_30d)}</span></div>
                  </div>
                  {renderMarginTrend(securityDetail.margin_profile.series)}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="header-right">
          <div className="top-beijing-clock" title="北京时间">
            {beijingClock}
          </div>
          {shIndexQuote && (
            <div className="top-index-quote">
              <span className="top-index-name">{shIndexQuote.name}</span>
              <span className="top-index-price">
                {shIndexQuote.price != null ? Number(shIndexQuote.price).toFixed(2) : "--"}
              </span>
              <span
                className="top-index-change"
                style={{
                  color:
                    (shIndexQuote.change_pct ?? 0) > 0
                      ? "#ef5350"
                      : (shIndexQuote.change_pct ?? 0) < 0
                      ? "#26a69a"
                      : "#d1d4dc",
                }}
              >
                {(shIndexQuote.change_pct ?? 0) > 0 ? "+" : ""}
                {(shIndexQuote.change_pct ?? 0).toFixed(2)}%
              </span>
            </div>
          )}
          <button
            className="vip-header-btn"
            onClick={() => openLoginModal(authUser ? "" : "请先登录或一键注册后开通 VIP", "vip")}
            type="button"
          >
            {authRole === "vip" || authRole === "admin" ? "续费" : "开通 VIP"}
          </button>
          {authUser ? (
            <div className="user-menu-wrap">
              <button
                className={`login-header-btn logged-in role-${authRole}`}
                onClick={() => setShowUserMenu((value) => !value)}
                type="button"
              >
                <span className="login-username">{authUser.username}{authExpiryLabel}</span>
              </button>
              {showUserMenu && (
                <div className="user-menu">
                  <button
                    type="button"
                    onClick={() => {
                      setShowUserMenu(false);
                      openLoginModal("", "billing");
                    }}
                  >
                    账单
                  </button>
                  <button type="button" onClick={handleLogout}>
                    登出
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button className="login-header-btn" onClick={() => openLoginModal()} type="button">
              登录
            </button>
          )}
        </div>
      </header>

      {activeReminder && (
        <div
          style={{
            position: "fixed",
            top: 64,
            right: 18,
            zIndex: 1000,
            minWidth: 320,
            maxWidth: 520,
            background: "#111827",
            border: "1px solid #2a2a3e",
            borderLeft: `4px solid ${activeReminder.direction === "buy" ? "#ef5350" : "#26a69a"}`,
            borderRadius: 10,
            padding: "10px 12px",
            boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <strong>
              自动提醒: {activeReminder.name} ({activeReminder.code})
            </strong>
            <button className="toggle-btn" onClick={() => setActiveReminder(null)}>关闭</button>
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>
            {formatSignalPeriodLabel(activeReminder.period)}
            {activeReminder.direction === "buy" ? "买点" : "卖点"} | {activeReminder.signal_time}
          </div>
          <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5 }}>{activeReminder.reason}</div>
        </div>
      )}

      {arbReminder && (
        <div
          style={{
            position: "fixed",
            top: activeReminder ? 160 : 64,
            right: 18,
            zIndex: 1000,
            minWidth: 320,
            maxWidth: 520,
            background: "#111827",
            border: "1px solid #2a2a3e",
            borderLeft: `4px solid ${arbReminder.direction.includes("buy") ? "#ef5350" : "#26a69a"}`,
            borderRadius: 10,
            padding: "10px 12px",
            boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <strong>
              套利提示:{" "}
              {arbNamesHidden
                ? maskArbStockLabel(arbReminder.stock_code)
                : `${arbReminder.stock_name} (${arbReminder.stock_code})`}
            </strong>
            <button className="toggle-btn" onClick={() => setArbReminder(null)}>关闭</button>
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>
            {arbReminder.direction === "buy"
              ? "滞涨买点"
              : arbReminder.direction === "sell"
              ? "抗跌卖点"
              : arbReminder.direction === "preopen_buy"
              ? "盘前偏多"
              : "盘前偏空"}{" "}
            | 基准 {arbReminder.bench_label} | {arbReminder.signal_time}
          </div>
          <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5 }}>{arbReminder.reason}</div>
        </div>
      )}

      {(signalDiagnosisLoading ||
        signalDiagnosisResult ||
        signalDiagnosisError ||
        fractalDiagnosisResult ||
        segmentFeatureDiagnosisResult ||
        autoDrawDiagnosisError) && (
        <div className="signal-diagnosis-drawer">
          <div className="signal-diagnosis-drawer-header">
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div className="signal-diagnosis-title">
                {autoDrawEnabled
                  ? autoDrawDiagnosisMode === "fractal"
                    ? "顶底分型诊断"
                    : "线段端点诊断"
                  : "K线买卖点诊断"}
              </div>
              <div className="signal-diagnosis-meta">
                {selectedName} ({selectedCode}) | {autoDrawEnabled ? autoDrawDiagnosisBarTime || "--" : signalDiagnosisResult?.bar_time || signalDiagnosisBarTime || "--"}
              </div>
            </div>
            <button className="modal-close-btn" onClick={closeAllDiagnosisModals}>
              关闭
            </button>
          </div>

          {autoDrawEnabled && (
            <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className={`toggle-btn ${autoDrawDiagnosisMode === "fractal" ? "active" : ""}`}
                onClick={() => handleSelectAutoDrawDiagnosisMode("fractal")}
              >
                诊断顶底分型
              </button>
              <button
                type="button"
                className={`toggle-btn ${autoDrawDiagnosisMode === "segment_feature" ? "active" : ""}`}
                onClick={() => handleSelectAutoDrawDiagnosisMode("segment_feature")}
              >
                诊断线段端点
              </button>
            </div>
          )}

          {!autoDrawEnabled && signalDiagnosisLoading && (
            <div className="signal-diagnosis-loading">正在分析这根K线为什么不是买卖点...</div>
          )}

          {!autoDrawEnabled && !signalDiagnosisLoading && signalDiagnosisError && (
            <div className="signal-diagnosis-error">{signalDiagnosisError}</div>
          )}

          {autoDrawEnabled && autoDrawDiagnosisError && (
            <div className="signal-diagnosis-error">{autoDrawDiagnosisError}</div>
          )}

          {autoDrawEnabled && autoDrawDiagnosisMode === "fractal" && fractalDiagnosisResult && (
            <div className="signal-diagnosis-body">
              <div className="signal-diagnosis-card">
                <div className="signal-diagnosis-card-header">
                  <span className={`signal-diagnosis-tag ${
                    fractalDiagnosisResult.type === "top"
                      ? "sell"
                      : fractalDiagnosisResult.type === "bottom"
                      ? "buy"
                      : ""
                  }`}>
                    {fractalDiagnosisResult.type === "top"
                      ? "顶分型"
                      : fractalDiagnosisResult.type === "bottom"
                      ? "底分型"
                      : "非分型"}
                  </span>
                  {fractalDiagnosisResult.elementRole && (
                    <span className="signal-diagnosis-point-key">
                      {fractalDiagnosisResult.elementRole === "first"
                        ? "第一元素"
                        : fractalDiagnosisResult.elementRole === "second"
                        ? `第二元素${fractalDiagnosisResult.isExtreme ? `（真正${fractalDiagnosisResult.type === "top" ? "最高" : "最低"}点）` : ""}`
                        : "第三元素"}
                    </span>
                  )}
                </div>
                <div className="signal-diagnosis-reason">
                  <span className="signal-diagnosis-label">说明</span>
                  <div>{fractalDiagnosisResult.explanation}</div>
                </div>
                {fractalDiagnosisResult.type !== "none" && (
                  <div className="signal-diagnosis-reason">
                    <span className="signal-diagnosis-label">判定规则</span>
                    <div>
                      顶分型要求三根去包含K线中第二根同时高点最高、低点也最高；底分型要求第二根同时低点最低、高点也最低。若后面出现更强同类分型或只是中继结构，原候选分型会被作废。
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {autoDrawEnabled && autoDrawDiagnosisMode === "segment_feature" && segmentFeatureDiagnosisResult && (
            <div className="signal-diagnosis-body">
              <div className="signal-diagnosis-card">
                <div className="signal-diagnosis-card-header">
                  <span className={`signal-diagnosis-tag ${
                    segmentFeatureDiagnosisResult.isEndpoint
                      ? segmentFeatureDiagnosisResult.segmentDirection === "up"
                        ? "sell"
                        : "buy"
                      : "neutral"
                  }`}>
                    {segmentFeatureDiagnosisResult.isEndpoint ? "线段端点" : "非端点"}
                  </span>
                  {segmentFeatureDiagnosisResult.penIndex != null && (
                    <span className="signal-diagnosis-point-key">
                      第{segmentFeatureDiagnosisResult.penIndex + 1}笔
                      {segmentFeatureDiagnosisResult.finishMode
                        ? ` · ${segmentFeatureDiagnosisResult.finishMode === "case1" ? "第一种情况" : "第二种情况"}`
                        : ""}
                    </span>
                  )}
                </div>
                <div className="signal-diagnosis-reason">
                  <span className="signal-diagnosis-label">说明</span>
                  <div>{segmentFeatureDiagnosisResult.explanation}</div>
                </div>
                {segmentFeatureDiagnosisResult.penIndex != null && (
                  <div className="signal-diagnosis-reason">
                    <span className="signal-diagnosis-label">判定规则</span>
                    <div>
                      线段端点要先满足线段结束的基本候选条件，再把该位置假定位端点继续检查。端点左右两边用于判定的前两个特征序列本身不做包含处理；只有从后续相邻特征序列开始，才继续按包含关系归并。若左侧第一特征序列不能形成所需顶底分型，则该候选端点无效；若左侧分型有缺口，还必须继续检查右侧第二特征序列是否形成对应分型。
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {!autoDrawEnabled && !signalDiagnosisLoading && signalDiagnosisResult && (
            <div className="signal-diagnosis-body">
              {signalDiagnosisResult.evaluations.map((item, idx) => (
                <div key={`${item.direction}-${item.point_key}-${idx}`} className="signal-diagnosis-card">
                  <div className="signal-diagnosis-card-header">
                    <span className={`signal-diagnosis-tag ${item.direction === "buy" ? "buy" : "sell"}`}>
                      {item.direction === "buy" ? "买点" : "卖点"} · {item.point_name}
                    </span>
                    <span className={`signal-diagnosis-status status-${item.status}`}>
                      {item.status === "matched"
                        ? "已触发"
                        : item.status === "out_of_range"
                        ? "超出回测范围"
                        : "不符合"}
                    </span>
                  </div>
                  <div className="signal-diagnosis-reason">
                    {item.status === "matched"
                      ? <>已触发，原因：{renderDiagnosisReason(item.reason)}</>
                      : <>不符合，原因：{renderDiagnosisReason(item.reason)}</>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showScanSettings && (
        <AutoScanPanel
          status={scanStatus}
          onSave={handleSaveScanSettings}
          onRunNow={handleRunScanNow}
          onClose={() => setShowScanSettings(false)}
          authUser={authUser}
          defaultStrategy={defaultStrategy}
          onRequireLogin={openLoginModal}
        />
      )}

      {showArbMonitor && (
        <ArbMonitorPanel
          onClose={() => {
            setShowArbMonitor(false);
            // 关面板=提醒已送达: 清角标并把告警全部标已读
            if (arbUnread > 0) {
              setArbUnread(0);
              markArbAlertsRead("all").catch(() => {});
            }
          }}
          onRequireLogin={openLoginModal}
        />
      )}

      {showDataDownload && (
        <DataDownloadModal
          status={historyDownloadStatus}
          onStart={handleStartHistoryDownload}
          onClose={() => setShowDataDownload(false)}
          autoDownloadEnabled={scanStatus?.auto_download_enabled ?? true}
          autoDownloadHour={scanStatus?.auto_download_hour ?? 15}
          klineForceRefresh={scanStatus?.kline_force_refresh ?? false}
          onAutoDownloadChange={(enabled, hour) => handleSaveScanSettings({ auto_download_enabled: enabled, auto_download_hour: hour })}
          onKlineForceRefreshChange={(enabled) => handleSaveScanSettings({ kline_force_refresh: enabled })}
        />
      )}

      {showUserManagement && (
        <UserManagementModal onClose={() => setShowUserManagement(false)} />
      )}

      {showLoginModal && (
        <LoginModal
          authUser={authUser}
          isGateway={gatewayMode}
          initialView={loginInitialView}
          reason={loginReason}
          onLogin={handleLoginSuccess}
          onRequireLogin={(message) => openLoginModal(message, "login")}
          onClose={() => setShowLoginModal(false)}
        />
      )}

      {pushResultDialog.visible && (
        <div className="modal-backdrop" onClick={() => setPushResultDialog((p) => ({ ...p, visible: false }))}>
          <div className="push-result-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="push-result-icon">{pushResultDialog.success ? "✓" : "✕"}</div>
            <div className="push-result-title">{pushResultDialog.success ? "推送成功" : "推送失败"}</div>
            {pushResultDialog.success ? (
              <div className="push-result-desc">已推送 <strong>{pushResultDialog.count}</strong> 只股票到大盘云图</div>
            ) : (
              <div className="push-result-desc push-result-error">{pushResultDialog.error}</div>
            )}
            <div className="push-result-actions">
              {pushResultDialog.success && pushResultDialog.url && (
                <button
                  className="push-result-jump-btn"
                  onClick={() => {
                    window.open(pushResultDialog.url, "_blank");
                    setPushResultDialog((p) => ({ ...p, visible: false }));
                  }}
                >
                  前往大盘云图
                </button>
              )}
              <button className="push-result-close-btn" onClick={() => setPushResultDialog((p) => ({ ...p, visible: false }))}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {settlementModal.visible && (
        <div className="modal-backdrop" onClick={() => setSettlementModal((prev) => ({ ...prev, visible: false }))}>
          <div className="scan-settings-modal settlement-modal" onClick={(e) => e.stopPropagation()}>
            <div className="panel-header settlement-modal-header">
              <div>
                <div className="panel-title">结算完成</div>
                <div className="panel-subtitle">
                  {settlementModal.name || settlementModal.code}
                  {settlementModal.code ? `（${settlementModal.code}）` : ""}
                </div>
              </div>
              <button className="modal-close-btn" onClick={() => setSettlementModal((prev) => ({ ...prev, visible: false }))}>
                关闭
              </button>
            </div>
            <div className="settlement-modal-body">
              {settlementModal.items.map((item, idx) => (
                <div key={`${item.tracked_id}-${idx}`} className="settlement-card">
                  <div className="settlement-card-row">
                    <span>跟踪时间</span>
                    <strong>{item.signal_time}</strong>
                  </div>
                  <div className="settlement-card-row">
                    <span>结算时间</span>
                    <strong>{item.exit_time}</strong>
                  </div>
                  <div className="settlement-card-row">
                    <span>买入价</span>
                    <strong>{item.signal_price.toFixed(3)}</strong>
                  </div>
                  <div className="settlement-card-row">
                    <span>卖出价</span>
                    <strong>{item.exit_price.toFixed(3)}</strong>
                  </div>
                  <div className="settlement-card-row">
                    <span>收益率</span>
                    <strong className={item.return_pct > 0 ? "settlement-up" : item.return_pct < 0 ? "settlement-down" : "settlement-flat"}>
                      {item.return_pct > 0 ? "+" : ""}{item.return_pct.toFixed(2)}%
                    </strong>
                  </div>
                </div>
              ))}
              {settlementModal.removedFromWatchlist && (
                <div className="settlement-watchlist-tip">该股票已同步移出自选。</div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="app-body" ref={appBodyRef}>
        <Sidebar
          watchlist={watchlist}
          selectedCode={selectedCode}
          onSelect={handleSelectWatchlistSecurity}
          realtimeMap={realtimeMap}
          onListChange={loadWatchlist}
          scanAlerts={scanAlerts}
          scanRuns={scanStatus?.recent_runs || []}
          scanStatus={scanStatus}
          onSelectSignal={handleSelectScanSignal}
          onMarkRead={handleMarkScanRead}
          onDeleteScanRun={handleDeleteScanRun}
          onPushScanRun={handlePushScanRun}
          onOpenScanSettings={() => setShowScanSettings(true)}
          activeTab={sidebarTab}
          onTabChange={setSidebarTab}
          authUser={authUser}
          onRequireLogin={openLoginModal}
          trackedSignals={trackedSignals}
          onTrackSignal={handleTrackSignal}
          onUntrackSignal={handleUntrackSignal}
          settledSignals={settledSignals}
          onSelectSettledSignal={handleSelectSettledSignal}
        />

        <div className="main-content">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <PeriodSelector
              selectedPeriod={period}
              onSelect={handleSelectPeriod}
              showDrawPanel={showDrawPanel}
              onToggleDrawPanel={() => setShowDrawPanel((value) => !value)}
            />
            {period === "intraday" && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                <span style={{ color: "var(--text-muted)" }}>叠加基准</span>
                <select
                  value={benchChoice}
                  onChange={(e) => setBenchChoice(e.target.value)}
                  style={{
                    background: "#161b26",
                    color: "#d1d4dc",
                    border: "1px solid #2a2a3e",
                    borderRadius: 6,
                    padding: "3px 6px",
                    fontSize: 12,
                  }}
                  title="个股分时与基准同图按涨跌幅%叠加"
                >
                  {BENCH_PRESETS.map((preset) => (
                    <option key={preset.key} value={preset.key}>
                      {preset.label}
                    </option>
                  ))}
                </select>
                {benchTrends && (
                  <span
                    style={{
                      color: benchTrends.stale ? "#f0b90b" : "#4f9dff",
                      fontSize: 11,
                    }}
                    title={`数据源 ${benchTrends.source}${benchTrends.stale ? "(缓存)" : ""}`}
                  >
                    {benchTrends.stale ? "缓存" : "实时"}
                  </span>
                )}
                {benchError && (
                  <span style={{ color: "#f23645", fontSize: 11 }} title={benchError}>
                    基准不可用
                  </span>
                )}
              </span>
            )}
          </div>
          <div className="chart-area workspace-chart-area">
            {loading ? (
              <div className="chart-loading">加载中...</div>
            ) : klineData.length > 0 ? (
              <KlineChart
                data={klineData}
                maData={maData}
                macdData={macdData}
                bollData={bollData}
                signals={backtestSignals}
                showMA={showMA}
                showMACD={showMACD}
                showBOLL={showBOLL}
                showVolume={showVolume}
                period={period}
                securityKind={isIndexCode(selectedCode, selectedName) ? "index" : "security"}
                resetKey={selectedCode}
                highlightedSignal={highlightedTrade}
                onRequestMoreHistory={loadMoreMinuteHistory}
                historyLoadInfo={historyLoadInfo}
                onCandleDoubleClick={handleDiagnoseSignalBar}
                autoDrawLines={autoDrawLines}
                showAutoDraw={autoDrawEnabled && autoDrawVisible && period === "5"}
                autoDrawColor={autoDrawColor}
                autoDrawWidthLevel={autoDrawWidthLevel}
                benchmark={
                  period === "intraday" && benchTrends && benchResolved
                    ? { label: benchResolved.label, points: benchTrends.points }
                    : null
                }
                stockPctBase={period === "intraday" ? stockPctBase : null}
              />
            ) : (
              <div className="chart-loading">暂无数据</div>
            )}
            {showDrawPanel && (
              <div
                className={`chart-draw-sidebar ${isDraggingDrawPanel ? "dragging" : ""}`}
                style={{ left: drawPanelPosition.left, top: drawPanelPosition.top }}
              >
                <div
                  className="chart-draw-sidebar-header"
                  onMouseDown={handleDrawPanelHeaderMouseDown}
                >
                  <span className="chart-draw-sidebar-title">画线</span>
                  <div className="chart-draw-sidebar-actions">
                    <button
                      type="button"
                      className={`period-eye-btn ${autoDrawVisible ? "active" : ""}`}
                      onClick={() => setAutoDrawVisible((value) => !value)}
                      title={autoDrawVisible ? "隐藏自动画线" : "显示自动画线"}
                      aria-label={autoDrawVisible ? "隐藏自动画线" : "显示自动画线"}
                    >
                      👁
                    </button>
                    <button
                      type="button"
                      className="modal-close-btn"
                      onClick={() => setShowDrawPanel(false)}
                    >
                      关闭
                    </button>
                  </div>
                </div>
                <div className="chart-draw-sidebar-body">
                  <div className="draw-toolbar-body">
                    <button
                      type="button"
                      className={`toggle-btn ${autoDrawEnabled ? "active" : ""}`}
                      onClick={handleToggleAutoDraw}
                      title="仅在 5 分钟周期自动生成缠论笔和线段"
                    >
                      自动划线
                    </button>
                    <button
                      type="button"
                      className={`toggle-btn ${showAutoSegments ? "active" : ""}`}
                      onClick={() => setShowAutoSegments((value) => !value)}
                    >
                      线段
                    </button>
                    <button
                      type="button"
                      className={`toggle-btn ${showAutoPens ? "active" : ""}`}
                      onClick={() => setShowAutoPens((value) => !value)}
                    >
                      笔
                    </button>
                  </div>
                  <div className="draw-toolbar-date-row">
                    <span className="draw-toolbar-label">起始日期</span>
                    <input
                      type="date"
                      className="draw-toolbar-date-input"
                      value={autoDrawStartDate}
                      max={autoDrawMaxDate}
                      onChange={(e) => setAutoDrawStartDate(e.target.value)}
                    />
                    <button
                      type="button"
                      className="toggle-btn"
                      onClick={() => setAutoDrawStartDate("")}
                    >
                      清空
                    </button>
                  </div>
                  <div className="draw-toolbar-style-row">
                    <label className="draw-toolbar-color-picker">
                      <span className="draw-toolbar-label">颜色</span>
                      <input
                        type="color"
                        value={autoDrawColor}
                        onChange={(e) => setAutoDrawColor(e.target.value)}
                      />
                    </label>
                    <div className="draw-toolbar-width-group">
                      <span className="draw-toolbar-label">线宽</span>
                      {[1, 2, 3, 4].map((level) => (
                        <button
                          key={level}
                          type="button"
                          className={`toggle-btn ${autoDrawWidthLevel === level ? "active" : ""}`}
                          onClick={() => setAutoDrawWidthLevel(level as 1 | 2 | 3 | 4)}
                        >
                          {level}档
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="draw-toolbar-hint">
                    仅 5 分钟周期生效。选择起始日期后，系统会自动补加载从该日期到最新K线所需的 5 分钟历史。
                    当前已加载区间：{autoDrawMinDate || "--"} ~ {autoDrawMaxDate || "--"}。
                  </div>
                  {autoDrawHistoryLoading && (
                    <div className="draw-toolbar-hint">正在自动加载起始日期到最新K线之间的 5 分钟历史...</div>
                  )}
                  {autoDrawHistoryError && (
                    <div className="signal-diagnosis-error" style={{ marginTop: 0 }}>
                      {autoDrawHistoryError}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="indicator-bar">
            <button className={`toggle-btn ${showMA ? "active" : ""}`} onClick={() => setShowMA(!showMA)}>MA</button>
            <button className={`toggle-btn ${showMACD ? "active" : ""}`} onClick={() => setShowMACD(!showMACD)}>MACD</button>
            <button className={`toggle-btn ${showBOLL ? "active" : ""}`} onClick={() => setShowBOLL(!showBOLL)}>BOLL</button>
            <button className={`toggle-btn ${showVolume ? "active" : ""}`} onClick={() => setShowVolume(!showVolume)}>VOL</button>
            <span style={{ flex: 1 }} />
          </div>
        </div>

        <div
          className="workspace-resizer"
          onMouseDown={() => setIsResizingLayout(true)}
          title="拖拽调整主图和右侧宽度"
        />

        <div
          className="right-panel backtest-mode"
          style={{ width: rightPanelWidth }}
        >
          <div className="right-workspace">
            <BacktestPanel 
              code={selectedCode} 
              name={selectedName} 
              selectedPeriod={period}
              onRunComplete={handleBacktestComplete}
              onClearSignals={handleClearBacktestSignals}
              onSelectTrade={handleSelectBacktestTrade}
              onInspectBatchDetail={handleInspectBatchDetail}
              selectedTrade={highlightedTrade}
              authUser={authUser}
              defaultStrategy={defaultStrategy}
              onRequireLogin={openLoginModal}
            />
          </div>
        </div>
      </div>
      <SystemStatsWidget />
    </div>
  );
}
