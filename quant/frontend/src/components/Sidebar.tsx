import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { addWatchlistSecurity, removeWatchlistSecurity, searchSecurity } from "../api";
import type { AuthUser } from "../api/auth";
import type { WatchlistSecurityInfo, ScanRunInfo, ScanSignal, ScanStatus, TrackedSignal, SettledSignal } from "../types";

interface Props {
  watchlist: WatchlistSecurityInfo[];
  selectedCode: string;
  onSelect: (code: string) => void;
  realtimeMap: Record<string, any>;
  onListChange: () => void;
  scanAlerts: ScanSignal[];
  scanRuns: ScanRunInfo[];
  scanStatus?: ScanStatus | null;
  onSelectSignal: (signal: ScanSignal) => void;
  onMarkRead: (ids: number[]) => Promise<void>;
  onDeleteScanRun: (runId: number) => Promise<void>;
  onPushScanRun: (runId: number) => Promise<void>;
  onOpenScanSettings?: () => void;
  activeTab?: "watchlist" | "scan";
  onTabChange?: (tab: "watchlist" | "scan") => void;
  authUser?: AuthUser | null;
  onRequireLogin?: (reason?: string) => void;
  trackedSignals: TrackedSignal[];
  onTrackSignal: (signal: ScanSignal) => void;
  onUntrackSignal: (trackedIds: number[], removeFromWatchlist: boolean) => Promise<void>;
  settledSignals: SettledSignal[];
  onSelectSettledSignal: (settled: SettledSignal) => void;
}

interface SearchResult {
  code: string;
  name: string;
  market?: number;
  price?: number;
  change_pct?: number;
  premium_rate?: number;
}

type GroupedSignals = {
  code: string;
  name: string;
  signals: ScanSignal[];
};

type ScanRunGroup = {
  key: string;
  run?: ScanRunInfo;
  signals: ScanSignal[];
  stocks: GroupedSignals[];
};

const SCAN_RUN_PAGE_SIZE = 5;

function getDirectionText(direction: string) {
  return direction === "buy" ? "买" : "卖";
}

function formatRunTrigger(trigger?: string) {
  return trigger === "manual" ? "手动" : "自动";
}

function getScanPeriodLabel(period?: string) {
  const normalized = ({
    "1": "1min",
    "5": "5min",
    "15": "15min",
    "30": "30min",
    "60": "60min",
  } as Record<string, string>)[period || ""] || period;
  return ({
    "1min": "1分钟",
    "5min": "5分钟",
    "15min": "15分钟",
    "30min": "30分钟",
    "60min": "60分钟",
    daily: "日K",
    weekly: "周K",
    monthly: "月K",
  } as Record<string, string>)[normalized || ""] || normalized || "";
}

function buildStockGroups(signals: ScanSignal[]) {
  const map = new Map<string, GroupedSignals>();
  for (const sig of signals) {
    if (!map.has(sig.code)) {
      map.set(sig.code, { code: sig.code, name: sig.name, signals: [] });
    }
    map.get(sig.code)!.signals.push(sig);
  }
  return Array.from(map.values());
}

function getDatePart(value?: string | null) {
  if (!value) return "";
  const match = String(value).match(/^(\d{4}-\d{2}-\d{2})/);
  return match?.[1] || "";
}

function getTodayDatePart() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateLabel(datePart: string) {
  // "2026-06-20" -> "6月20日"；含同年时省略年份，跨年时带年份
  const match = datePart.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return datePart;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const thisYear = new Date().getFullYear();
  return year === thisYear ? `${month}月${day}日` : `${year}年${month}月${day}日`;
}

function getTimePart(value?: string | null) {
  // "2026-09-06 14:35:02" / ISO -> "14:35"（只取时分）
  if (!value) return "";
  const match = String(value).match(/(\d{2}:\d{2})/);
  return match?.[1] || "";
}

type SettledGroup = { datePart: string; items: SettledSignal[] };

function groupSettledByDay(settled: SettledSignal[]): SettledGroup[] {
  const map = new Map<string, SettledSignal[]>();
  for (const item of settled) {
    const key = getDatePart(item.settled_at) || "未知日期";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(item);
  }
  // 后端已按 settled_at DESC 返回；同一天内保持原顺序
  return Array.from(map.entries()).map(([datePart, items]) => ({ datePart, items }));
}

function filterStockGroupsByDate(stocks: GroupedSignals[], datePart: string) {
  if (!datePart) return stocks;
  return stocks
    .map((stock) => ({
      ...stock,
      signals: stock.signals.filter((sig) => getDatePart(sig.signal_time) === datePart),
    }))
    .filter((stock) => stock.signals.length > 0);
}

// 扫描轮次按「扫描日期」过滤：9月6号扫描的轮次只展示9月6号当天的信号/买卖点，
// 不再掺入窗口内其它日期的信号。仅旧数据（无 run 信息、拿不到扫描日期）用最新信号日兜底。
function latestSignalDatePart(stocks: GroupedSignals[]) {
  let latest = "";
  for (const stock of stocks) {
    for (const sig of stock.signals) {
      const datePart = getDatePart(sig.signal_time);
      if (datePart > latest) latest = datePart;
    }
  }
  return latest;
}

export default function Sidebar({
  watchlist,
  selectedCode,
  onSelect,
  realtimeMap,
  onListChange,
  scanAlerts,
  scanRuns,
  scanStatus,
  onSelectSignal,
  onMarkRead,
  onDeleteScanRun,
  onPushScanRun,
  onOpenScanSettings,
  activeTab: controlledTab,
  onTabChange,
  authUser,
  onRequireLogin,
  trackedSignals,
  onTrackSignal,
  onUntrackSignal,
  settledSignals,
  onSelectSettledSignal,
}: Props) {
  const [internalTab, setInternalTab] = useState<"watchlist" | "scan">("watchlist");
  const activeTab = controlledTab ?? internalTab;
  const setActiveTab = onTabChange ?? setInternalTab;
  const [showHistory, setShowHistory] = useState(false);
  // 历史跟踪：默认只展开最近一次日期，其余折叠；key 为 datePart
  const [collapsedHistoryDates, setCollapsedHistoryDates] = useState<Set<string>>(new Set());

  const historyGroups = useMemo(() => groupSettledByDay(settledSignals), [settledSignals]);

  // settledSignals 变化时（如刚结算、首次加载），默认只展开最近一次日期，其余折叠
  useEffect(() => {
    const keys = historyGroups.map((g) => g.datePart);
    if (keys.length === 0) {
      setCollapsedHistoryDates(new Set());
      return;
    }
    const latest = keys[0];
    setCollapsedHistoryDates(new Set(keys.filter((k) => k !== latest)));
  }, [historyGroups]);

  const toggleHistoryDate = (datePart: string) => {
    setCollapsedHistoryDates((prev) => {
      const next = new Set(prev);
      if (next.has(datePart)) next.delete(datePart);
      else next.add(datePart);
      return next;
    });
  };

  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [addMsg, setAddMsg] = useState("");
  const [adding, setAdding] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const addFormRef = useRef<HTMLDivElement>(null);

  const [longPressCode, setLongPressCode] = useState<string | null>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scanRunLongPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suppressRunToggleRef = useRef(false);
  const latestRunKeyRef = useRef<string | null>(null);

  const [expandedRunKeys, setExpandedRunKeys] = useState<Set<string>>(new Set());
  const [scanRunPage, setScanRunPage] = useState(1);
  const [longPressRunId, setLongPressRunId] = useState<number | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<number | null>(null);
  const [pushingRunId, setPushingRunId] = useState<number | null>(null);
  const [untrackDialogCode, setUntrackDialogCode] = useState<string | null>(null);

  const trackedCodeSet = useMemo(() => new Set(trackedSignals.map((t) => t.code)), [trackedSignals]);
  const focusedScanCodes = useMemo(
    () => (scanStatus?.scan_scope_type === "selected" ? [] : (scanStatus?.scan_focus_codes || [])),
    [scanStatus?.scan_focus_codes, scanStatus?.scan_scope_type]
  );
  const focusedScanCodeSet = useMemo(() => new Set(focusedScanCodes), [focusedScanCodes]);
  const configuredScanPeriodLabel = scanStatus?.scan_period_label || getScanPeriodLabel(scanStatus?.scan_period);

  const scanRunGroups = useMemo<ScanRunGroup[]>(() => {
    const signalsByRunId = new Map<number, ScanSignal[]>();
    const orphanSignals: ScanSignal[] = [];
    for (const sig of scanAlerts) {
      if (typeof sig.run_id === "number") {
        if (!signalsByRunId.has(sig.run_id)) signalsByRunId.set(sig.run_id, []);
        signalsByRunId.get(sig.run_id)!.push(sig);
      } else {
        orphanSignals.push(sig);
      }
    }

    const groups: ScanRunGroup[] = scanRuns.map((run) => {
      const signals = signalsByRunId.get(run.id) || [];
      signalsByRunId.delete(run.id);
      return {
        key: `run-${run.id}`,
        run,
        signals,
        stocks: buildStockGroups(signals),
      };
    });

    const leftovers = [
      ...orphanSignals,
      ...Array.from(signalsByRunId.values()).flat(),
    ];
    if (leftovers.length > 0) {
      groups.push({
        key: "legacy",
        signals: leftovers,
        stocks: buildStockGroups(leftovers),
      });
    }
    return groups;
  }, [scanAlerts, scanRuns]);

  const scanRunPageCount = Math.max(1, Math.ceil(scanRunGroups.length / SCAN_RUN_PAGE_SIZE));
  const pagedScanRunGroups = useMemo(() => {
    const safePage = Math.min(Math.max(scanRunPage, 1), scanRunPageCount);
    const start = (safePage - 1) * SCAN_RUN_PAGE_SIZE;
    return scanRunGroups.slice(start, start + SCAN_RUN_PAGE_SIZE);
  }, [scanRunGroups, scanRunPage, scanRunPageCount]);

  const unreadCount = useMemo(() => {
    return scanAlerts.length;
  }, [scanAlerts]);

  const highlightedHitCount = useMemo(() => {
    if (focusedScanCodeSet.size === 0) return 0;
    return new Set(scanAlerts.filter((item) => focusedScanCodeSet.has(item.code)).map((item) => item.code)).size;
  }, [scanAlerts, focusedScanCodeSet]);

  const filtered = watchlist.filter(
    (item) =>
      item.code.includes(search) ||
      item.name.toLowerCase().includes(search.toLowerCase())
  );

  const handleSearchInput = useCallback((value: string) => {
    setAddInput(value);
    setAddMsg("");
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!value.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      const res = await searchSecurity(value.trim(), 15);
      setSearching(false);
      if (res.success) {
        setSearchResults(res.data);
      } else {
        setSearchResults([]);
      }
    }, 300);
  }, [watchlist]);

  const handleSelectResult = async (item: SearchResult) => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再修改自选列表");
      return;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能修改自选列表，请先开通 VIP 后再操作");
      return;
    }
    const exists = watchlist.some((security) => security.code === item.code);
    if (exists) {
      onSelect(item.code);
      setShowAdd(false);
      setSearchResults([]);
      setAddInput("");
      return;
    }

    setAdding(true);
    setAddMsg("");
    setSearchResults([]);
    const res = await addWatchlistSecurity(item.code, item.name, item.market);
    setAdding(false);
    if (res.success) {
      setAddInput("");
      setAddMsg("");
      setShowAdd(false);
      onListChange();
    } else {
      setAddMsg(res.message || "添加失败");
    }
  };

  const handleManualAdd = async () => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再修改自选列表");
      return;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能修改自选列表，请先开通 VIP 后再操作");
      return;
    }
    if (!addInput.trim()) {
      setAddMsg("请输入代码或名称");
      return;
    }
    if (searchResults.length > 0) return;
    setAdding(true);
    setAddMsg("");
    const res = await addWatchlistSecurity(addInput.trim());
    setAdding(false);
    if (res.success) {
      setAddInput("");
      setAddMsg("");
      setShowAdd(false);
      onListChange();
    } else {
      setAddMsg(res.message || "添加失败");
    }
  };

  const handleRemove = useCallback(async (code: string, e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setLongPressCode(null);
    if (!authUser) {
      onRequireLogin?.("请先登录后再修改自选列表");
      return;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能修改自选列表，请先开通 VIP 后再操作");
      return;
    }
    try {
      const res = await removeWatchlistSecurity(code);
      if (res.success) {
        onListChange();
      } else if ((res as any).status === 401 || (res as any).status === 403) {
        onRequireLogin?.((res as any).message || "请先登录后再修改自选列表");
      } else {
        alert(res.message || "删除失败");
      }
    } catch {
      alert("删除失败，请重试");
    }
  }, [authUser, onListChange, onRequireLogin]);

  const handleMarkSignalsRead = useCallback(async (signals: ScanSignal[]) => {
    const ids = signals.filter((s) => s.id).map((s) => Number(s.id));
    if (ids.length === 0) return;
    await onMarkRead(ids);
  }, [onMarkRead]);

  const handleToggleRun = useCallback((key: string) => {
    setExpandedRunKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const clearScanRunLongPressTimer = useCallback(() => {
    if (scanRunLongPressTimer.current) {
      clearTimeout(scanRunLongPressTimer.current);
      scanRunLongPressTimer.current = null;
    }
  }, []);

  const handleScanRunPointerDown = useCallback((runGroup: ScanRunGroup) => {
    if (!runGroup.run || deletingRunId === runGroup.run.id) return;
    clearScanRunLongPressTimer();
    suppressRunToggleRef.current = false;
    scanRunLongPressTimer.current = setTimeout(() => {
      scanRunLongPressTimer.current = null;
      suppressRunToggleRef.current = true;
      setLongPressRunId(runGroup.run!.id);
    }, 600);
  }, [clearScanRunLongPressTimer, deletingRunId]);

  const handleScanRunPointerEnd = useCallback(() => {
    clearScanRunLongPressTimer();
  }, [clearScanRunLongPressTimer]);

  const handleRunHeaderClick = useCallback((key: string, runId?: number) => {
    if (suppressRunToggleRef.current) {
      suppressRunToggleRef.current = false;
      return;
    }
    if (runId && longPressRunId === runId) {
      return;
    }
    handleToggleRun(key);
  }, [handleToggleRun, longPressRunId]);

  const handleDeleteScanRun = useCallback(async (runId: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    clearScanRunLongPressTimer();
    setLongPressRunId(null);
    setDeletingRunId(runId);
    try {
      await onDeleteScanRun(runId);
    } catch {
      alert("删除扫描结果失败，请重试");
    } finally {
      setDeletingRunId(null);
      suppressRunToggleRef.current = false;
    }
  }, [clearScanRunLongPressTimer, onDeleteScanRun]);

  const handlePushScanRun = useCallback(async (runId: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (pushingRunId === runId) return;
    setPushingRunId(runId);
    try {
      await onPushScanRun(runId);
    } catch {
      /* error dialog handled by App */
    } finally {
      setPushingRunId(null);
    }
  }, [onPushScanRun, pushingRunId]);

  const handleItemMouseDown = (code: string) => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    longPressTimer.current = setTimeout(() => {
      setLongPressCode(code);
    }, 500);
  };

  const handleItemMouseUp = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (addFormRef.current && !addFormRef.current.contains(e.target as Node)) {
        setSearchResults([]);
      }
      if (longPressCode) {
        const target = e.target as HTMLElement;
        if (!target.closest(".etf-delete-popup")) {
          setLongPressCode(null);
        }
      }
      if (longPressRunId) {
        const target = e.target as HTMLElement;
        if (!target.closest(".scan-run-delete-popup")) {
          setLongPressRunId(null);
          suppressRunToggleRef.current = false;
        }
      }
      if (untrackDialogCode) {
        const target = e.target as HTMLElement;
        if (!target.closest(".untrack-dialog") && !target.closest(".track-badge")) {
          setUntrackDialogCode(null);
        }
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [longPressCode, longPressRunId, untrackDialogCode]);

  useEffect(() => {
    return () => {
      if (longPressTimer.current) clearTimeout(longPressTimer.current);
      if (scanRunLongPressTimer.current) clearTimeout(scanRunLongPressTimer.current);
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, []);

  useEffect(() => {
    const latestKey = scanRunGroups[0]?.key;
    if (!latestKey || latestRunKeyRef.current === latestKey) return;
    latestRunKeyRef.current = latestKey;
    setScanRunPage(1);
    setExpandedRunKeys((prev) => {
      const next = new Set(prev);
      next.add(latestKey);
      return next;
    });
  }, [scanRunGroups]);

  useEffect(() => {
    if (scanRunPage <= scanRunPageCount) return;
    setScanRunPage(scanRunPageCount);
  }, [scanRunPage, scanRunPageCount]);

  return (
    <div className="sidebar">
      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${activeTab === "watchlist" ? "active" : ""}`}
          onClick={() => setActiveTab("watchlist")}
        >
          自选股
        </button>
        <button
          className={`sidebar-tab ${activeTab === "scan" ? "active" : ""}`}
          onClick={() => setActiveTab("scan")}
        >
          扫描结果{unreadCount > 0 ? ` (${unreadCount})` : ""}
        </button>
      </div>

      {activeTab === "watchlist" && (
        <>
          {showHistory ? (
            <div className="history-track-panel">
              <div className="history-track-toolbar">
                <span className="history-track-title">历史跟踪</span>
                <button
                  className="history-track-back"
                  onClick={() => setShowHistory(false)}
                  title="返回自选列表"
                >
                  ✕
                </button>
              </div>
              <div className="history-track-list">
                {historyGroups.length === 0 ? (
                  <div className="history-track-empty">暂无历史跟踪记录</div>
                ) : (
                  historyGroups.map((group) => {
                    const collapsed = collapsedHistoryDates.has(group.datePart);
                    return (
                      <div className="history-track-group" key={group.datePart}>
                        <div
                          className={`history-track-date${collapsed ? " collapsed" : ""}`}
                          onClick={() => toggleHistoryDate(group.datePart)}
                          title={collapsed ? "点击展开" : "点击折叠"}
                        >
                          <span className={`history-track-arrow${collapsed ? " collapsed" : ""}`}>▶</span>
                          {formatDateLabel(group.datePart)}
                          {group.datePart === getTodayDatePart() && "（今天）"}
                          <span className="history-track-count">{group.items.length}</span>
                        </div>
                        {!collapsed && group.items.map((item) => {
                          const isSelectedHistory = selectedCode === item.code;
                          return (
                            <div
                              key={`${item.id}`}
                              className={`history-track-item${isSelectedHistory ? " selected" : ""}`}
                              onClick={() => onSelectSettledSignal(item)}
                              title={`${item.name}（${item.code}）\n跟踪：${item.signal_time}\n结束：${item.settled_at}\n收益率：${item.return_pct > 0 ? "+" : ""}${item.return_pct.toFixed(2)}%`}
                            >
                              <div className="history-track-item-main">
                                <span className="history-track-name">
                                  {item.name}（{item.code}）
                                </span>
                                <span className="history-track-range">
                                  {getDatePart(item.signal_time)} ～ {getDatePart(item.exit_time)}
                                </span>
                              </div>
                              <div className="history-track-item-meta">
                                <span
                                  className="history-track-return"
                                  style={{
                                    color: item.return_pct > 0 ? "#ef5350" : item.return_pct < 0 ? "#26a69a" : "#d1d4dc",
                                  }}
                                >
                                  {item.return_pct > 0 ? "+" : ""}
                                  {item.return_pct.toFixed(2)}%
                                </span>
                                <span className="history-track-prices">
                                  {item.signal_price.toFixed(2)} → {item.exit_price.toFixed(2)}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          ) : (
            <>
          <div className="sidebar-header">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h3>自选列表</h3>
                <button
                  className={`history-track-btn${showHistory ? " active" : ""}`}
                  onClick={() => setShowHistory((v) => !v)}
                  title="历史跟踪"
                  aria-label="历史跟踪"
                >
                  {/* 历史时钟图标 */}
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 3v5h5" />
                    <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
                    <path d="M12 7v5l4 2" />
                  </svg>
                </button>
              </div>
              <button
                className="etf-add-btn"
                onClick={() => {
                  if (!authUser) {
                    onRequireLogin?.("请先登录后再修改自选列表");
                    return;
                  }
                  if ((authUser.role || "").toLowerCase() === "trial") {
                    onRequireLogin?.("临时账号不能修改自选列表，请先开通 VIP 后再操作");
                    return;
                  }
                  setShowAdd(!showAdd);
                  setAddMsg("");
                  setAddInput("");
                  setSearchResults([]);
                }}
                title="添加标的"
              >
                {showAdd ? "✕" : "+"}
              </button>
            </div>
            <input
              type="text"
              placeholder="搜索自选代码/名称"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="search-input"
            />
            {showAdd && (
              <div className="etf-add-form" ref={addFormRef} style={{ position: "relative" }}>
                <input
                  type="text"
                  placeholder="实时搜索A股/ETF代码或名称"
                  value={addInput}
                  onChange={(e) => handleSearchInput(e.target.value)}
                  className="search-input"
                  style={{ marginBottom: 4 }}
                  onKeyDown={(e) => { if (e.key === "Enter" && searchResults.length === 0) handleManualAdd(); }}
                  autoFocus
                />
                {searching && <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>搜索中...</div>}
                {searchResults.length > 0 && (
                  <div style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    right: 0,
                    background: "#1e1e36",
                    border: "1px solid #2a2a3e",
                    borderRadius: 4,
                    maxHeight: 200,
                    overflowY: "auto",
                    zIndex: 100,
                  }}>
                    {searchResults.map((item) => {
                      const exists = watchlist.some((security) => security.code === item.code);
                      const displayName = item.name && item.name !== item.code ? item.name : "名称获取中";
                      return (
                        <div
                          key={item.code}
                          onClick={() => handleSelectResult(item)}
                          style={{
                            padding: "6px 10px",
                            cursor: "pointer",
                            fontSize: 12,
                            color: "#d1d4dc",
                            borderBottom: "1px solid #2a2a3e",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: 8,
                          }}
                          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#2a2a3e"; }}
                          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = ""; }}
                        >
                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            <span>{displayName}</span>
                            <span style={{ color: "#8b949e", fontSize: 11 }}>{item.code}</span>
                          </div>
                          <span style={{ color: exists ? "#8b949e" : "#45b7d1", fontSize: 11, whiteSpace: "nowrap" }}>
                            {exists ? "已在列表" : "可添加"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
                {searchResults.length === 0 && addInput.trim() && !searching && (
                  <button className="etf-add-confirm-btn" onClick={handleManualAdd} disabled={adding}>
                    {adding ? "添加中..." : "添加"}
                  </button>
                )}
                {addMsg && <div className="add-msg">{addMsg}</div>}
              </div>
            )}
          </div>
          <div className="etf-list">
            {filtered.map((etf) => {
              const rt = realtimeMap[etf.code];
              const price = rt?.price || etf.price || 0;
              const changePct = rt?.change_pct ?? etf.change_pct ?? 0;
              const isSelected = etf.code === selectedCode;
              const showDelete = longPressCode === etf.code;
              const isTracked = (etf.tracked_signal_count ?? 0) > 0;
              const trackedReturnPct = etf.tracked_return_pct ?? null;
              const showUntrackDialog = untrackDialogCode === etf.code;

              return (
                <div
                  key={etf.code}
                  className={`etf-item ${isSelected ? "selected" : ""}`}
                  onClick={() => {
                    if (!showDelete && !showUntrackDialog) onSelect(etf.code);
                  }}
                  onMouseDown={() => handleItemMouseDown(etf.code)}
                  onMouseUp={handleItemMouseUp}
                  onMouseLeave={handleItemMouseUp}
                  onTouchStart={() => handleItemMouseDown(etf.code)}
                  onTouchEnd={handleItemMouseUp}
                  style={{ position: "relative" }}
                >
                  <div className="etf-info">
                    <span className="etf-name">
                      {etf.t0 && <span className="t0-badge">T+0</span>}
                      {isTracked && (
                        <span
                          className="track-badge"
                          onClick={(e) => {
                            e.stopPropagation();
                            setUntrackDialogCode(etf.code);
                          }}
                          title="已跟踪扫描信号，点击取消跟踪"
                        >
                          跟踪
                        </span>
                      )}
                      {etf.name}（{etf.code}）
                    </span>
                  </div>
                  <div className="etf-price-info">
                    <span
                      className="etf-price"
                      style={{
                        color: changePct > 0 ? "#ef5350" : changePct < 0 ? "#26a69a" : "#d1d4dc",
                      }}
                    >
                      {price ? price.toFixed(3) : "--"}
                    </span>
                    <span
                      className="etf-change"
                      style={{
                        color: changePct > 0 ? "#ef5350" : changePct < 0 ? "#26a69a" : "#d1d4dc",
                      }}
                    >
                      {changePct > 0 ? "+" : ""}
                      {changePct.toFixed(2)}%
                    </span>
                    {trackedReturnPct != null && (
                      <span
                        className="etf-track-return"
                        style={{
                          color: trackedReturnPct > 0 ? "#ef5350" : trackedReturnPct < 0 ? "#26a69a" : "#d1d4dc",
                        }}
                      >
                        跟踪 {trackedReturnPct > 0 ? "+" : ""}{trackedReturnPct.toFixed(2)}%
                      </span>
                    )}
                  </div>
                  {showDelete && !showUntrackDialog && (
                    <button
                      className="etf-delete-popup"
                      onMouseDown={(e) => { e.stopPropagation(); }}
                      onClick={(e) => { e.stopPropagation(); e.preventDefault(); handleRemove(etf.code, e); }}
                    >
                      删除
                    </button>
                  )}
                  {showUntrackDialog && (
                    <div className="untrack-dialog" onClick={(e) => e.stopPropagation()}>
                      <div className="untrack-dialog-text">取消跟踪此股票的扫描信号？</div>
                      <div className="untrack-dialog-actions">
                        <button
                          className="untrack-dialog-btn"
                          onClick={() => {
                            const codeTracked = trackedSignals.filter((t) => t.code === etf.code);
                            void onUntrackSignal(codeTracked.map((t) => t.id), false);
                            setUntrackDialogCode(null);
                          }}
                        >
                          结算并取消跟踪
                        </button>
                        <button
                          className="untrack-dialog-btn danger"
                          onClick={() => {
                            const codeTracked = trackedSignals.filter((t) => t.code === etf.code);
                            void onUntrackSignal(codeTracked.map((t) => t.id), true);
                            setUntrackDialogCode(null);
                          }}
                        >
                          结算并移出自选
                        </button>
                        <button
                          className="untrack-dialog-btn"
                          onClick={() => setUntrackDialogCode(null)}
                        >
                          返回
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
              </>
            )}
        </>
      )}

      {activeTab === "scan" && (
        <div className="scan-results-sidebar">
          <div className="scan-setting-summary" style={{ margin: "8px 8px 12px" }}>
            <div>
              当前扫描周期：{configuredScanPeriodLabel || "未设置"}
            </div>
            {focusedScanCodes.length === 0 ? (
              <div>特别关注：未设置，当前按默认顺序展示扫描结果。</div>
            ) : highlightedHitCount > 0 ? (
              <div>特别关注：已设置 {focusedScanCodes.length} 只，最近结果命中 {highlightedHitCount} 只，已优先高亮展示。</div>
            ) : (
              <div>特别关注：已设置 {focusedScanCodes.length} 只，但最近结果没有扫到。</div>
            )}
          </div>
          {scanRunGroups.length === 0 ? (
            <div className="scan-empty-state">
              <div className="scan-empty-kicker">还没有扫描结果</div>
              <div className="scan-empty-title">
                {authUser ? "点「扫描设置」开始第一轮扫描" : "登录后即可开始扫描"}
              </div>
              <div className="scan-empty-desc">
                {authUser
                  ? "设置扫描范围、周期和策略后，点击立即扫描，命中的买卖点会出现在这里。"
                  : "登录账号后进入扫描设置，选择范围和策略，再执行立即扫描。"}
              </div>
              <button
                className="scan-empty-action"
                type="button"
                onClick={() => {
                  if (authUser) {
                    onOpenScanSettings?.();
                  } else {
                    onRequireLogin?.("请先登录后再开始扫描");
                  }
                }}
              >
                {authUser ? "打开扫描设置" : "去登录"}
              </button>
            </div>
          ) : (
            <>
              {pagedScanRunGroups.map((runGroup) => {
                const expanded = expandedRunKeys.has(runGroup.key);
                const isDeletingRun = deletingRunId === runGroup.run?.id;
                const showRunDelete = !!runGroup.run && longPressRunId === runGroup.run.id;
                // 过滤口径 = 该轮的扫描日期(started_at 的日期部分)；
                // 旧数据没有 run 信息时退回该轮内最新信号日
                const filterDate = runGroup.run
                  ? getDatePart(runGroup.run.started_at)
                  : latestSignalDatePart(runGroup.stocks);
                const scanTimePart = getTimePart(runGroup.run?.started_at);
                const scanDateText = filterDate
                  ? `${formatDateLabel(filterDate)}${scanTimePart ? ` ${scanTimePart}` : ""}`
                  : "无";
                const visibleStocks = filterStockGroupsByDate(runGroup.stocks, filterDate);
                const visibleSignalCount = visibleStocks.reduce((sum, stock) => sum + stock.signals.length, 0);
                // 命中总数(近8根K线窗口口径，不限日期) vs 当天可见数：两者不一致时
                // 同时展示，避免"扫描说命中18条、列表却0条"被误读成统计丢了。
                const totalSignalCount = runGroup.stocks.reduce((sum, stock) => sum + stock.signals.length, 0);
                const signalCountText = visibleSignalCount === totalSignalCount
                  ? `${visibleSignalCount}条`
                  : `当天${visibleSignalCount}条/共${totalSignalCount}条`;
                return (
                  <div key={runGroup.key} className="scan-run-item">
                    <div
                      role="button"
                      tabIndex={isDeletingRun ? -1 : 0}
                      aria-disabled={isDeletingRun}
                      className={`scan-run-header ${isDeletingRun ? "deleting" : ""}`}
                      onClick={() => handleRunHeaderClick(runGroup.key, runGroup.run?.id)}
                      onKeyDown={(e) => {
                        if (isDeletingRun) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          handleRunHeaderClick(runGroup.key, runGroup.run?.id);
                        }
                      }}
                      onPointerDown={() => handleScanRunPointerDown(runGroup)}
                      onPointerUp={handleScanRunPointerEnd}
                      onPointerLeave={handleScanRunPointerEnd}
                      onPointerCancel={handleScanRunPointerEnd}
                      onContextMenu={(e) => {
                        if (runGroup.run) e.preventDefault();
                      }}
                      title={runGroup.run?.message || `${runGroup.run ? `${scanDateText}（${formatRunTrigger(runGroup.run.trigger_type)}扫描，${signalCountText}）` : "历史扫描结果"}，长按显示删除按钮`}
                    >
                      <span className="scan-run-caret">{expanded ? "▾" : "▸"}</span>
                      <span className="scan-run-title">
                        {runGroup.run ? scanDateText : "历史扫描结果"}
                      </span>
                      <span className="scan-run-meta">
                        {isDeletingRun
                          ? "删除中..."
                          : `${runGroup.run ? `${formatRunTrigger(runGroup.run.trigger_type)}扫描` : scanDateText} · ${signalCountText}`}
                      </span>
                      {runGroup.run && (
                        <button
                          className={`scan-run-push-btn ${pushingRunId === runGroup.run.id ? "pushing" : ""}`}
                          onClick={(e) => handlePushScanRun(runGroup.run!.id, e)}
                          disabled={pushingRunId === runGroup.run.id || isDeletingRun}
                          title="将本轮扫描结果推送到大盘云图"
                        >
                          {pushingRunId === runGroup.run.id ? "推送中..." : "推送云图"}
                        </button>
                      )}
                    </div>
                    {showRunDelete && (
                      <button
                        className="scan-run-delete-popup"
                        onPointerDown={(e) => { e.stopPropagation(); }}
                        onMouseDown={(e) => { e.stopPropagation(); }}
                        onClick={(e) => handleDeleteScanRun(runGroup.run!.id, e)}
                      >
                        删除
                      </button>
                    )}

                    {expanded && (
                      <div className="scan-run-body">
                        {visibleStocks.length === 0 ? (
                          <div className="scan-run-empty">
                            {totalSignalCount > 0
                              ? `本轮命中${totalSignalCount}条都不在扫描当日，已按当天日期过滤隐藏`
                              : "本轮暂无命中"}
                          </div>
                        ) : (
                          [...visibleStocks]
                            .sort((a, b) => Number(focusedScanCodeSet.has(b.code)) - Number(focusedScanCodeSet.has(a.code)))
                            .map((stock) => (
                            <div
                              key={`${runGroup.key}-${stock.code}`}
                              className={`scan-group-item ${focusedScanCodeSet.has(stock.code) ? "scan-group-item-highlighted" : ""}`}
                            >
                              <div className="scan-group-header">
                                <span
                                  className="scan-group-name"
                                  onClick={() => {
                                    if (stock.signals.length > 0) {
                                      onSelectSignal(stock.signals[0]);
                                    }
                                  }}
                                  title={`${stock.name}（${stock.code}）`}
                                >
                                  {stock.name}（{stock.code}）
                                </span>
                                {focusedScanCodeSet.has(stock.code) && (
                                  <span className="scan-focus-badge">关注</span>
                                )}
                                <button
                                  className={`scan-track-btn ${trackedCodeSet.has(stock.code) ? "tracked" : ""}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (trackedCodeSet.has(stock.code)) return;
                                    const firstSignalWithId = stock.signals.find((s) => s.id);
                                    if (firstSignalWithId) {
                                      onTrackSignal(firstSignalWithId);
                                    }
                                  }}
                                  title={trackedCodeSet.has(stock.code) ? "已跟踪" : "跟踪此股票的扫描信号"}
                                  disabled={trackedCodeSet.has(stock.code)}
                                >
                                  {trackedCodeSet.has(stock.code) ? "已跟踪" : "跟踪"}
                                </button>
                                <button
                                  className="scan-mark-read-btn"
                                  onClick={() => handleMarkSignalsRead(stock.signals)}
                                  title="删除这只股票的扫描结果"
                                >
                                  已读
                                </button>
                              </div>
                              <div className="scan-group-signals">
                                {stock.signals.map((sig) => (
                                  <div
                                    key={`${sig.id ?? ""}-${sig.signal_time}-${sig.direction}`}
                                    className="scan-signal-item"
                                    title={`${stock.name}（${stock.code}）\n${getDirectionText(sig.direction)} ${sig.signal_time}\n价格：${sig.price?.toFixed(3)}\n原因：${sig.reason}`}
                                    onClick={() => onSelectSignal(sig)}
                                  >
                                    <span className={`scan-signal-direction ${sig.direction}`}>
                                      {getDirectionText(sig.direction)}
                                    </span>
                                    <span className="scan-signal-time">{sig.signal_time}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {scanRunPageCount > 1 && (
                <div className="scan-run-pagination">
                  <button
                    className="scan-page-btn"
                    onClick={() => setScanRunPage((page) => Math.max(1, page - 1))}
                    disabled={scanRunPage <= 1}
                  >
                    上一页
                  </button>
                  <span>{Math.min(scanRunPage, scanRunPageCount)}/{scanRunPageCount}</span>
                  <button
                    className="scan-page-btn"
                    onClick={() => setScanRunPage((page) => Math.min(scanRunPageCount, page + 1))}
                    disabled={scanRunPage >= scanRunPageCount}
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
