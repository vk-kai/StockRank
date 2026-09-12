import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  addArbPair,
  fetchArbStatus,
  markArbAlertsRead,
  removeArbPair,
  searchBenchmarks,
  searchSecurity,
  toggleArbPair,
  updateArbSettings,
} from "../api";
import { isArbSoundEnabled, setArbSoundEnabled, testArbAlertSound } from "../lib/alertSound";
import { isArbNameHidden, maskArbStockLabel, setArbNameHidden } from "../lib/arbPrivacy";
import type { ArbAlert, ArbPairSnapshot, ArbStatus, BenchmarkCandidate } from "../types";

interface Props {
  onClose: () => void;
  onRequireLogin?: (reason?: string) => void;
}

const PHASE_LABELS: Record<string, string> = {
  off: "时段外",
  disabled: "已关闭",
  not_trading_day: "非交易日",
  preopen: "盘前观察",
  session: "盘中监控",
  idle: "午间休市",
};

const STATUS_META: Record<string, { color: string; label: string }> = {
  ok: { color: "#22c55e", label: "吻合跟踪中" },
  preopen: { color: "#4f9dff", label: "盘前观察" },
  warmup: { color: "#f0b90b", label: "预热中" },
  off: { color: "#8b949e", label: "非交易时段(显示最后交易时段状态)" },
  decoupled: { color: "#8b949e", label: "走势脱钩" },
  flat: { color: "#8b949e", label: "波动不足" },
  error: { color: "#f23645", label: "异常" },
};

const DIRECTION_LABELS: Record<string, { label: string; color: string }> = {
  buy: { label: "买点", color: "#ef5350" },
  sell: { label: "卖点", color: "#26a69a" },
  preopen_buy: { label: "盘前偏多", color: "#ef5350" },
  preopen_sell: { label: "盘前偏空", color: "#26a69a" },
};

/** 小眼睛开关图标(线条风格;off=划线眼,表示当前已隐藏) */
function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {off ? (
        <>
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </>
      ) : (
        <>
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  );
}

const QUICK_BENCHES: BenchmarkCandidate[] = [
  { kind: "em_index", code: "000001", label: "上证指数" },
  { kind: "em_index", code: "399001", label: "深证成指" },
  { kind: "em_index", code: "399006", label: "创业板指" },
  { kind: "em_global", code: "KS11", label: "韩国KOSPI" },
];

function statusMeta(status?: string) {
  return STATUS_META[status || "warmup"] || STATUS_META.warmup;
}

function formatPct(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** 卡片右侧迷你分时图:红=个股 蓝=基准,同一坐标系画累计涨跌幅%,虚线=0轴。 */
function PairSparkline({ curve }: { curve?: Array<[string, number, number]> | null }) {
  const points = (curve || []).filter((p) => Number.isFinite(p[1]) && Number.isFinite(p[2]));
  if (points.length < 2) return null;
  const W = 180;
  const H = 56;
  const values = points.flatMap((p) => [p[1], p[2]]);
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (max - min < 0.2) {
    const mid = (max + min) / 2;
    min = mid - 0.1;
    max = mid + 0.1;
  }
  const x = (i: number) => (i / (points.length - 1)) * (W - 2) + 1;
  const y = (v: number) => H - 2 - ((v - min) / (max - min)) * (H - 4);
  const path = (idx: 1 | 2) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p[idx]).toFixed(1)}`).join("");
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      style={{ flexShrink: 0, display: "block" }}
    >
      <title>{`当日分时 ${points[0][0]}-${points[points.length - 1][0]} 红:个股 蓝:基准`}</title>
      <line x1={0} y1={y(0)} x2={W} y2={y(0)} stroke="#2a2a3e" strokeDasharray="3 3" strokeWidth={1} />
      <path d={path(2)} fill="none" stroke="#4f9dff" strokeWidth={1.2} />
      <path d={path(1)} fill="none" stroke="#ef5350" strokeWidth={1.4} />
    </svg>
  );
}

export default function ArbMonitorPanel({ onClose, onRequireLogin }: Props) {
  const [status, setStatus] = useState<ArbStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(isArbSoundEnabled());
  // 小眼睛:隐藏个股名称(截屏/投屏防泄露;告警历史与弹窗横幅同步打码)
  const [hideNames, setHideNames] = useState(isArbNameHidden);

  // 添加配对表单
  const [stockKeyword, setStockKeyword] = useState("");
  const [stockCandidates, setStockCandidates] = useState<Array<{ code: string; name: string }>>([]);
  const [stockPick, setStockPick] = useState<{ code: string; name: string } | null>(null);
  const [benchKeyword, setBenchKeyword] = useState("");
  const [benchCandidates, setBenchCandidates] = useState<BenchmarkCandidate[]>([]);
  const [benchPick, setBenchPick] = useState<BenchmarkCandidate | null>(null);
  // 基准下拉只在输入框聚焦时弹出(点击候选后延迟失焦,保证 click 先于隐藏)
  const [benchFocused, setBenchFocused] = useState(false);
  const [preopenEnabled, setPreopenEnabled] = useState(true);
  const [adding, setAdding] = useState(false);
  const stockSearchTimer = useRef<number | null>(null);
  const benchSearchTimer = useRef<number | null>(null);
  const benchInputRef = useRef<HTMLInputElement | null>(null);

  const handleApiError = useCallback(
    (message: string) => {
      if (/登录|临时账号|VIP/i.test(message)) {
        onRequireLogin?.(message);
      } else {
        setActionError(message);
      }
    },
    [onRequireLogin]
  );

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetchArbStatus();
      if (res.success && res.data) {
        setStatus(res.data);
        setLoadError(null);
      } else {
        setLoadError(res.message || "状态获取失败");
      }
    } catch {
      setLoadError("状态请求失败");
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const timer = window.setInterval(loadStatus, 30000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  // 个股搜索(防抖自动完成)
  useEffect(() => {
    if (stockSearchTimer.current != null) window.clearTimeout(stockSearchTimer.current);
    if (!stockKeyword.trim() || stockPick) {
      setStockCandidates([]);
      return;
    }
    stockSearchTimer.current = window.setTimeout(async () => {
      try {
        const res = await searchSecurity(stockKeyword.trim(), 8);
        setStockCandidates((res.data || []).map((item) => ({ code: item.code, name: item.name })));
      } catch {
        setStockCandidates([]);
      }
    }, 300);
    return () => {
      if (stockSearchTimer.current != null) window.clearTimeout(stockSearchTimer.current);
    };
  }, [stockKeyword, stockPick]);

  // 基准搜索(防抖;空关键词时展示快捷项)
  useEffect(() => {
    if (benchSearchTimer.current != null) window.clearTimeout(benchSearchTimer.current);
    const keyword = benchKeyword.trim();
    if (!keyword || benchPick) {
      setBenchCandidates(keyword ? [] : QUICK_BENCHES);
      return;
    }
    benchSearchTimer.current = window.setTimeout(async () => {
      try {
        const res = await searchBenchmarks(keyword);
        const remote = res.data || [];
        setBenchCandidates([...remote, ...QUICK_BENCHES.filter((q) => !remote.some((r) => r.code === q.code && r.kind === q.kind))]);
      } catch {
        setBenchCandidates(QUICK_BENCHES);
      }
    }, 350);
    return () => {
      if (benchSearchTimer.current != null) window.clearTimeout(benchSearchTimer.current);
    };
  }, [benchKeyword, benchPick]);

  const handleToggleMaster = async () => {
    const next = !(status?.settings.enabled ?? false);
    setActionError(null);
    const res = await updateArbSettings(next);
    if (res.success) {
      setStatus((prev) => (prev ? { ...prev, settings: { ...prev.settings, enabled: next } } : prev));
      loadStatus();
    } else {
      handleApiError(res.message || "保存失败");
    }
  };

  const handleAddPair = async () => {
    if (!stockPick || !benchPick) {
      setActionError("请先选择个股和基准");
      return;
    }
    setAdding(true);
    setActionError(null);
    try {
      const res = await addArbPair({
        stock_code: stockPick.code,
        stock_name: stockPick.name,
        bench_kind: benchPick.kind,
        bench_code: benchPick.code,
        bench_label: benchPick.label,
        preopen_enabled: preopenEnabled,
      });
      if (res.success) {
        setStockKeyword("");
        setStockPick(null);
        setBenchKeyword("");
        setBenchPick(null);
        loadStatus();
      } else {
        handleApiError(res.message || "添加失败");
      }
    } finally {
      setAdding(false);
    }
  };

  const handleTogglePair = async (pairId: number, enabled: boolean) => {
    setActionError(null);
    const res = await toggleArbPair(pairId, enabled);
    if (res.success) {
      loadStatus();
    } else {
      handleApiError(res.message || "操作失败");
    }
  };

  const handleRemovePair = async (pairId: number) => {
    setActionError(null);
    const res = await removeArbPair(pairId);
    if (res.success) {
      loadStatus();
    } else {
      handleApiError(res.message || "删除失败");
    }
  };

  const handleMarkAllRead = async () => {
    const res = await markArbAlertsRead("all");
    if (res.success) {
      loadStatus();
    } else {
      handleApiError(res.message || "标记失败");
    }
  };

  // 小眼睛:持久化 + 广播,App 层的弹窗横幅实时跟着打码/还原
  const handleToggleHideNames = () => {
    const next = !hideNames;
    setHideNames(next);
    setArbNameHidden(next);
  };

  const runtime = status?.runtime;
  const snapshots: ArbPairSnapshot[] = runtime?.pairs || [];
  const alerts: ArbAlert[] = status?.alerts || [];
  const masterEnabled = status?.settings.enabled ?? false;

  const inputStyle: CSSProperties = {
    background: "#161b26",
    color: "#d1d4dc",
    border: "1px solid #2a2a3e",
    borderRadius: 6,
    padding: "5px 8px",
    fontSize: 12,
    width: "100%",
    boxSizing: "border-box",
  };

  const chipStyle: CSSProperties = {
    display: "inline-block",
    padding: "1px 7px",
    borderRadius: 999,
    fontSize: 11,
    background: "#1c2333",
    border: "1px solid #2a2a3e",
    color: "#9fb3c8",
    whiteSpace: "nowrap",
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>套利背离监控</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="panel-card-meta">
              {masterEnabled
                ? `${PHASE_LABELS[runtime?.phase || "off"] || runtime?.phase} · ${runtime?.interval_seconds ?? 15}s/tick`
                : "未开启"}
              {runtime?.kospi_pct != null ? ` · KOSPI ${formatPct(runtime.kospi_pct)}` : ""}
            </span>
            <button className="modal-close-btn" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>

        {loadError && (
          <div style={{ color: "#f23645", fontSize: 12, marginBottom: 8 }}>{loadError}</div>
        )}
        {actionError && (
          <div style={{ color: "#f23645", fontSize: 12, marginBottom: 8 }}>{actionError}</div>
        )}

        <div style={{ display: "grid", gap: 14 }}>
          {/* 总开关 + 声音 */}
          <div className="scan-setting-card" style={{ padding: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button
              className={`setting-toggle-btn ${masterEnabled ? "active" : ""}`}
              onClick={handleToggleMaster}
            >
              {masterEnabled ? "监控已开启" : "监控已关闭"}
            </button>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              个股与基准走势吻合时,基准异动而个股滞涨/抗跌 → 盘中提示;KOSPI 早盘大幅波动 → 盘前提示
            </span>
            <span style={{ flex: 1 }} />
            <label style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={soundEnabled}
                onChange={(e) => {
                  setSoundEnabled(e.target.checked);
                  setArbSoundEnabled(e.target.checked);
                }}
              />
              提示音
            </label>
            <button className="toggle-btn" onClick={() => testArbAlertSound()} type="button">
              测试提示音
            </button>
            {runtime?.last_tick && (
              <span style={{ fontSize: 11, color: "#8b949e" }}>最近tick {runtime.last_tick.slice(11)}</span>
            )}
          </div>

          {/* 配对列表 */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{ fontWeight: 600 }}>监控配对({snapshots.length})</div>
              <button
                className="toggle-btn"
                type="button"
                onClick={handleToggleHideNames}
                title={hideNames ? "显示个股名称" : "隐藏个股名称(截屏/投屏防泄露;告警历史与弹窗提示同步隐藏)"}
                style={{ padding: "3px 7px", display: "inline-flex", alignItems: "center" }}
              >
                <EyeIcon off={hideNames} />
              </button>
            </div>
            {snapshots.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "8px 0" }}>
                暂无配对,用下方表单添加(如 长电科技 × 国家大基金持股)
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {snapshots.map((snap) => {
                  const meta = statusMeta(snap.status);
                  const isBuy = snap.signal?.includes("buy");
                  return (
                    <div
                      key={snap.pair_id}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 8,
                        border: `1px solid ${snap.signal ? (isBuy ? "#ef5350" : "#26a69a") : "#2a2a3e"}`,
                        background: "#141a26",
                        display: "flex",
                        gap: 10,
                        alignItems: "center",
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span
                            style={{
                              width: 8,
                              height: 8,
                              borderRadius: "50%",
                              background: meta.color,
                              display: "inline-block",
                              flexShrink: 0,
                            }}
                            title={meta.label}
                          />
                          <strong style={{ fontSize: 13 }}>
                            {hideNames ? maskArbStockLabel(snap.stock_code) : `${snap.stock_name}(${snap.stock_code})`}
                          </strong>
                          <span style={{ color: "#4f9dff", fontSize: 12 }}>× {snap.bench_label}</span>
                          <span
                            style={{
                              fontSize: 12,
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                              color: snap.stock_pct != null && snap.stock_pct >= 0 ? "#ef5350" : "#26a69a",
                            }}
                          >
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#ef5350", display: "inline-block", flexShrink: 0 }} />
                            个股 {formatPct(snap.stock_pct)}
                          </span>
                          <span
                            style={{
                              fontSize: 12,
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                              color: snap.bench_pct != null && snap.bench_pct >= 0 ? "#ef5350" : "#26a69a",
                            }}
                          >
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#4f9dff", display: "inline-block", flexShrink: 0 }} />
                            基准 {formatPct(snap.bench_pct)}
                          </span>
                          <span style={{ flex: 1 }} />
                          {!snap.enabled && <span style={{ ...chipStyle, color: "#8b949e" }}>已停用</span>}
                          <button className="toggle-btn" onClick={() => handleTogglePair(snap.pair_id, !snap.enabled)}>
                            {snap.enabled ? "停用" : "启用"}
                          </button>
                          <button className="toggle-btn" onClick={() => handleRemovePair(snap.pair_id)}>
                            删除
                          </button>
                        </div>
                        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
                          {snap.bench_stale && <span style={{ ...chipStyle, color: "#f0b90b" }}>基准数据延迟</span>}
                          <span style={{ fontSize: 12, lineHeight: 1.5, color: snap.status === "error" ? "#f23645" : "#8b949e" }}>
                            {snap.reason || meta.label}
                          </span>
                        </div>
                      </div>
                      <PairSparkline curve={snap.curve} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 添加配对 */}
          <div className="scan-setting-card" style={{ padding: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>添加配对</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto auto", gap: 8, alignItems: "start" }}>
              <div style={{ position: "relative" }}>
                <input
                  style={inputStyle}
                  placeholder={stockPick ? `${stockPick.name}(${stockPick.code})` : "个股代码/名称"}
                  value={stockPick ? "" : stockKeyword}
                  onChange={(e) => setStockKeyword(e.target.value)}
                  disabled={adding}
                />
                {stockPick && (
                  <button
                    className="toggle-btn"
                    style={{ position: "absolute", right: 4, top: 4 }}
                    onClick={() => {
                      setStockPick(null);
                      setStockKeyword("");
                    }}
                  >
                    换
                  </button>
                )}
                {!stockPick && stockCandidates.length > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      top: "100%",
                      left: 0,
                      right: 0,
                      zIndex: 30,
                      background: "#111827",
                      border: "1px solid #2a2a3e",
                      borderRadius: 6,
                      marginTop: 2,
                      maxHeight: 180,
                      overflowY: "auto",
                    }}
                  >
                    {stockCandidates.map((item) => (
                      <div
                        key={item.code}
                        style={{ padding: "5px 8px", fontSize: 12, cursor: "pointer" }}
                        onClick={() => {
                          setStockPick(item);
                          setStockCandidates([]);
                        }}
                      >
                        {item.name}({item.code})
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ position: "relative" }}>
                <input
                  ref={benchInputRef}
                  style={inputStyle}
                  placeholder={benchPick ? `${benchPick.label}(${benchPick.code})` : "基准: 板块/指数/KOSPI"}
                  value={benchPick ? "" : benchKeyword}
                  onChange={(e) => setBenchKeyword(e.target.value)}
                  onFocus={() => setBenchFocused(true)}
                  onBlur={() => window.setTimeout(() => setBenchFocused(false), 150)}
                  disabled={adding}
                />
                {benchPick && (
                  <button
                    className="toggle-btn"
                    style={{ position: "absolute", right: 4, top: 4 }}
                    onClick={() => {
                      setBenchPick(null);
                      setBenchKeyword("");
                      benchInputRef.current?.focus(); // 点"换"=要重选,聚焦输入框自然展开候选
                    }}
                  >
                    换
                  </button>
                )}
                {!benchPick && benchFocused && benchCandidates.length > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      top: "100%",
                      left: 0,
                      right: 0,
                      zIndex: 30,
                      background: "#111827",
                      border: "1px solid #2a2a3e",
                      borderRadius: 6,
                      marginTop: 2,
                      maxHeight: 180,
                      overflowY: "auto",
                    }}
                  >
                    {benchCandidates.map((item) => (
                      <div
                        key={`${item.kind}-${item.code}`}
                        style={{ padding: "5px 8px", fontSize: 12, cursor: "pointer" }}
                        onClick={() => {
                          setBenchPick(item);
                          setBenchCandidates([]);
                        }}
                      >
                        {item.label}({item.code})
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <label style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", paddingTop: 6 }}>
                <input
                  type="checkbox"
                  checked={preopenEnabled}
                  onChange={(e) => setPreopenEnabled(e.target.checked)}
                />
                盘前提示
              </label>
              <button
                className="toggle-btn active"
                onClick={handleAddPair}
                disabled={adding || !stockPick || !benchPick}
                style={{ marginTop: 2 }}
              >
                {adding ? "添加中..." : "添加"}
              </button>
            </div>
          </div>

          {/* 告警历史 */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{ fontWeight: 600 }}>告警历史({alerts.length})</div>
              <span style={{ flex: 1 }} />
              {alerts.some((item) => !item.is_read) && (
                <button className="toggle-btn" onClick={handleMarkAllRead}>
                  全部已读
                </button>
              )}
            </div>
            {alerts.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 0" }}>
                暂无告警;出现"基准异动而个股滞涨/抗跌"时会在这里并弹提示
              </div>
            ) : (
              <div style={{ display: "grid", gap: 6, maxHeight: 260, overflowY: "auto", paddingRight: 4 }}>
                {alerts.map((alert) => {
                  const dir = DIRECTION_LABELS[alert.direction] || { label: alert.direction, color: "#8b949e" };
                  return (
                    <div
                      key={alert.id}
                      style={{
                        padding: "6px 9px",
                        borderRadius: 6,
                        border: "1px solid #2a2a3e",
                        borderLeft: `3px solid ${dir.color}`,
                        background: alert.is_read ? "transparent" : "#141a26",
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <strong style={{ color: dir.color }}>{dir.label}</strong>
                        <span>
                          {hideNames ? maskArbStockLabel(alert.stock_code) : `${alert.stock_name}(${alert.stock_code})`}
                        </span>
                        <span style={{ color: "#4f9dff" }}>基准 {alert.bench_label}</span>
                        <span style={{ color: "#8b949e" }}>
                          {alert.trade_date} {alert.signal_time}
                        </span>
                        {/* 已读=已被看过/已闭环(StockRank 拉走并推完微信),只是标签,历史永不清理 */}
                        {alert.is_read && <span style={{ ...chipStyle, color: "#8b949e" }}>已读</span>}
                      </div>
                      <div style={{ marginTop: 3, color: "var(--text-muted)", lineHeight: 1.5 }}>{alert.reason}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
