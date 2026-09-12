import { useEffect, useMemo, useState } from "react";
import { fetchScanCandidates, fetchScanStrategies } from "../api";
import type { AuthUser } from "../api/auth";
import type { ScanRunIndustryInfo, ScanScopeCandidate, ScanStatus, StrategyInfo } from "../types";


interface Props {
  status: ScanStatus | null;
  onSave: (params: {
    enabled?: boolean;
    strategy_name?: string;
    interval_minutes?: number;
    scan_scope_type?: string;
    scan_scope_codes?: string[];
    scan_focus_codes?: string[];
    scan_period?: string;
  }) => Promise<void>;
  onRunNow: () => Promise<void>;
  onClose: () => void;
  authUser?: AuthUser | null;
  defaultStrategy?: string;
  onRequireLogin?: (reason?: string) => void;
}

const SCAN_PERIOD_OPTIONS = [
  { value: "1min", label: "1分钟" },
  { value: "5min", label: "5分钟" },
  { value: "15min", label: "15分钟" },
  { value: "30min", label: "30分钟" },
  { value: "60min", label: "60分钟" },
  { value: "daily", label: "日K" },
  { value: "weekly", label: "周K" },
  { value: "monthly", label: "月K" },
];

function getPeriodLabel(period?: string) {
  const normalized = ({
    "1": "1min",
    "5": "5min",
    "15": "15min",
    "30": "30min",
    "60": "60min",
  } as Record<string, string>)[period || ""] || period;
  return SCAN_PERIOD_OPTIONS.find((item) => item.value === normalized)?.label || period || "30分钟";
}

function getRequiredPeriodText(periods?: string[]) {
  const labels = Array.from(new Set((periods && periods.length > 0 ? periods : ["daily", "30min"]).map(getPeriodLabel)));
  return labels.join("和");
}

function formatBuyIndustrySummary(items?: ScanRunIndustryInfo[]) {
  if (!items || items.length === 0) return "";
  return items
    .filter((item) => item.stock_count > 0)
    .slice(0, 3)
    .map((item) => `${item.industry} ${item.stock_count}只`)
    .join("，");
}

function parseCodeText(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,，;；]+/)
        .map((item) => item.trim())
        .map((item) => item.replace(/\D/g, ""))
        .filter((item) => item.length === 6)
    )
  );
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function ScanRadar({ active, running }: { active: boolean; running: boolean }) {
  return (
    <div className={`scan-radar${active ? " active" : ""}${running ? " running" : ""}`} aria-hidden="true">
      <span className="scan-radar-ring r1" />
      <span className="scan-radar-ring r2" />
      <span className="scan-radar-ring r3" />
      <span className="scan-radar-cross h" />
      <span className="scan-radar-cross v" />
      {(active || running) && (
        <span className="scan-radar-sweep" />
      )}
      <span className="scan-radar-blip b1" />
      <span className="scan-radar-blip b2" />
      <span className="scan-radar-core" />
    </div>
  );
}


export default function AutoScanPanel({
  status,
  onSave,
  onRunNow,
  onClose,
  authUser,
  defaultStrategy = "MACD_Cross",
  onRequireLogin,
}: Props) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [localEnabled, setLocalEnabled] = useState(false);
  const [localStrategy, setLocalStrategy] = useState("MA_BULL_PULLBACK_BOLL");
  const [localScanPeriod, setLocalScanPeriod] = useState("30min");
  const [scanScopeType, setScanScopeType] = useState("all");
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [focusedCodes, setFocusedCodes] = useState<string[]>([]);
  const [focusCodeText, setFocusCodeText] = useState("");
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidateKeyword, setCandidateKeyword] = useState("");
  const [candidateItems, setCandidateItems] = useState<ScanScopeCandidate[]>([]);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [nowTick, setNowTick] = useState(() => Date.now());
  const scanReady = !!status?.scan_ready;
  const scanPeriodLabel = getPeriodLabel(localScanPeriod);
  const requiredPeriodText = getRequiredPeriodText(status?.required_periods);
  const localReadyCount = status?.local_ready_count || 0;
  const scanUniverseCount = status?.scan_universe_count || 0;
  const localReadyGap = Math.max(scanUniverseCount - localReadyCount, 0);
  // 开启意图与"当下数据是否就绪"解耦：收盘下载挂起/盘中等待期也允许先打开开关。
  // 后端只在运行时挂起扫描(executor 不拦"开启"，数据就绪后自动开始)，
  // 这里若按 scan_ready 禁用按钮，一旦关掉就会陷入"下载完成前点不开"的死锁。
  // 仅在股票池为空(全新部署、从未下载过数据)时保留禁用。
  const canEnableAuto = localEnabled || scanReady || scanUniverseCount > 0;
  const canRunNow = scanReady && !running && !status?.running;
  const selectedStrategyInfo = strategies.find((item) => item.name === localStrategy);

  // 下次扫描倒计时：每秒走一拍，仅在有下次扫描时间时启用
  useEffect(() => {
    if (!status?.enabled || !status?.next_scan_at) return;
    const timer = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status?.enabled, status?.next_scan_at]);

  const nextScanInfo = useMemo(() => {
    const text = status?.next_scan_at;
    if (!text) return null;
    const target = new Date(text.replace(/-/g, "/")).getTime();
    if (Number.isNaN(target)) return null;
    const diffSeconds = Math.max(0, Math.floor((target - nowTick) / 1000));
    const hours = Math.floor(diffSeconds / 3600);
    const minutes = Math.floor((diffSeconds % 3600) / 60);
    const seconds = diffSeconds % 60;
    const countdown = hours > 0
      ? `${hours}:${pad2(minutes)}:${pad2(seconds)}`
      : `${pad2(minutes)}:${pad2(seconds)}`;
    return { timeText: text.slice(11, 16), countdown };
  }, [status?.next_scan_at, nowTick]);

  useEffect(() => {
    fetchScanStrategies().then((res) => {
      if (res.success && res.data) {
        setStrategies(res.data);
      }
    });
  }, [authUser?.username]);

  useEffect(() => {
    if (!status) return;
    setLocalEnabled(status.enabled);
    const shouldUseLoginDefault =
      !!authUser && !status.strategy_owner_username && (status.default_strategy || defaultStrategy);
    setLocalStrategy(shouldUseLoginDefault ? (status.default_strategy || defaultStrategy) : status.strategy_name);
    setLocalScanPeriod(status.scan_period || "30min");
    setScanScopeType(status.scan_scope_type || "all");
    setSelectedCodes(status.scan_scope_codes || []);
    setFocusedCodes(status.scan_focus_codes || []);
    setFocusCodeText((status.scan_focus_codes || []).join(", "));
  }, [status, defaultStrategy, authUser]);

  useEffect(() => {
    if (scanScopeType !== "selected") return;
    let disposed = false;
    setLoadingCandidates(true);
    fetchScanCandidates({ page: candidatePage, page_size: 20, keyword: candidateKeyword }).then((res) => {
      if (disposed) return;
      if (res.success) {
        setCandidateItems(res.data.items || []);
        setCandidateTotal(res.data.total || 0);
      }
    }).finally(() => {
      if (!disposed) setLoadingCandidates(false);
    });
    return () => {
      disposed = true;
    };
  }, [scanScopeType, candidatePage, candidateKeyword]);

  const handleSave = async (
    nextEnabled = localEnabled,
    nextStrategy = localStrategy,
    nextScopeType = scanScopeType,
    nextScopeCodes = selectedCodes,
    nextFocusCodes = focusedCodes,
    nextScanPeriod = localScanPeriod,
  ) => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再修改扫描设置");
      return false;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能修改扫描设置，请先开通 VIP 后再操作");
      return false;
    }
    const strategyInfo = strategies.find((item) => item.name === nextStrategy);
    if (strategyInfo?.locked) {
      onRequireLogin?.(strategyInfo.lock_message || "请先登录后使用该策略");
      return false;
    }
    setSaving(true);
    try {
      const effectiveFocusCodes = nextScopeType === "all" ? nextFocusCodes : undefined;
      await onSave({
        enabled: nextEnabled,
        strategy_name: nextStrategy,
        interval_minutes: 30,
        scan_scope_type: nextScopeType,
        scan_scope_codes: nextScopeCodes,
        scan_focus_codes: effectiveFocusCodes,
        scan_period: nextScanPeriod,
      });
      return true;
    } catch {
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleRunNow = async () => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再启动扫描");
      return;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能启动扫描，请先开通 VIP 后再操作");
      return;
    }
    if (selectedStrategyInfo?.locked) {
      onRequireLogin?.(selectedStrategyInfo.lock_message || "请先登录后使用该策略");
      return;
    }
    setRunning(true);
    try {
      const saved = await handleSave(localEnabled, localStrategy, scanScopeType, selectedCodes, focusedCodes, localScanPeriod);
      if (!saved) return;
      await onRunNow();
    } finally {
      setRunning(false);
    }
  };

  const requireSettingsAuth = () => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再修改扫描设置");
      return false;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能修改扫描设置，请先开通 VIP 后再操作");
      return false;
    }
    return true;
  };

  const handleToggleCandidate = (code: string) => {
    if (!requireSettingsAuth()) return;
    setSelectedCodes((prev) => (
      prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]
    ));
  };

  const handleSaveFocusCodes = async () => {
    const parsed = parseCodeText(focusCodeText);
    const saved = await handleSave(localEnabled, localStrategy, scanScopeType, selectedCodes, parsed, localScanPeriod);
    if (saved) {
      setFocusedCodes(parsed);
      setFocusCodeText(parsed.join(", "));
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>扫描设置</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="panel-card-meta">
              {status?.running ? `扫描中 · ${scanPeriodLabel}` : status?.enabled ? `交易时段自动扫描 · ${scanPeriodLabel}` : "未开启"}
            </span>
            <button className="modal-close-btn" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {/* 状态区：自动扫描（雷达 + 下次扫描时间）与手动扫描 */}
          <div className="scan-settings-grid">
            <div className="scan-setting-card scan-auto-card">
              <div className="scan-auto-main">
                <ScanRadar active={localEnabled} running={!!status?.running} />
                <div className="scan-auto-info">
                  <div className="scan-setting-title">自动扫描（{scanPeriodLabel}）</div>
                  <div className="scan-setting-desc">交易日交易时段按设定周期自动扫描，有本地K线数据即可开启</div>
                </div>
                <button
                  className={`setting-toggle-btn ${localEnabled ? "active" : ""}`}
                  onClick={async () => {
                    const nextEnabled = !localEnabled;
                    const saved = await handleSave(nextEnabled, localStrategy, scanScopeType, selectedCodes, focusedCodes, localScanPeriod);
                    if (saved) setLocalEnabled(nextEnabled);
                  }}
                  disabled={saving || !canEnableAuto}
                >
                  {localEnabled ? "已开启" : "已关闭"}
                </button>
              </div>
              {localEnabled && (
                <div className="scan-next-row">
                  {nextScanInfo ? (
                    <>
                      <span className="scan-next-dot" aria-hidden="true" />
                      <span className="scan-next-label">下次扫描</span>
                      <span className="scan-next-time">{nextScanInfo.timeText}</span>
                      <span className="scan-next-countdown">{nextScanInfo.countdown} 后</span>
                    </>
                  ) : (
                    <span className="scan-next-label muted">
                      {status?.is_trading_day === false
                        ? "今日休市 · 下一交易日开盘后自动扫描"
                        : "今日槽位已结束 · 下一交易日继续"}
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="scan-setting-card scan-manual-card">
              <div className="scan-setting-title">手动扫描（{scanPeriodLabel}）</div>
              <div className="scan-setting-desc">立即执行一轮本地历史数据扫描，并叠加当前实时行情判断是否出现买卖点</div>
              <button className="setting-primary-btn" onClick={handleRunNow} disabled={!canRunNow}>
                <span className="btn-text">
                  {running || status?.running ? "扫描中..." : `立即扫描（${localReadyCount}）`}
                </span>
              </button>
            </div>
          </div>

          {/* 扫描运行中：进度实时展示 */}
          {status?.running && (
            <div className="scan-runtime-card">
              <div className="scan-runtime-title">扫描进度</div>
              <div className="scan-runtime-text">{status.current_message || "正在并行扫描股票..."}</div>
              {(() => {
                const secs = status.estimated_remaining_seconds || 0;
                if (secs > 0) {
                  const text = secs < 60 ? `${Math.round(secs)}秒` : secs < 3600 ? `${Math.round(secs / 60)}分钟` : `${Math.floor(secs / 3600)}小时${Math.round((secs % 3600) / 60) > 0 ? `${Math.round((secs % 3600) / 60)}分钟` : ""}`;
                  return <div className="scan-runtime-text">预计剩余时间：{text}</div>;
                }
                return null;
              })()}
              <div className="scan-progress-track">
                <div
                  className="scan-progress-fill"
                  style={{ width: `${status.progress_pct || 0}%` }}
                />
              </div>
              <div className="scan-progress-meta">
                <span>{status.current_index || 0}/{status.total_count || 0}</span>
                <span>进度 {status.progress_pct || 0}%</span>
              </div>
            </div>
          )}

          {/* 参数区：策略 + K线周期 */}
          <div className="scan-setting-card">
            <div className="scan-setting-block">
              <label className="scan-setting-label">扫描策略</label>
              <div className="strategy-select-wrap">
                {strategies.map((item) => (
                  <button
                    key={item.name}
                    className={`strategy-option-btn ${localStrategy === item.name ? "active" : ""}`}
                    onClick={async () => {
                      if (item.locked) {
                        onRequireLogin?.(item.lock_message || "请先登录后使用该策略");
                        return;
                      }
                      const saved = await handleSave(localEnabled, item.name, scanScopeType, selectedCodes, focusedCodes, localScanPeriod);
                      if (saved) setLocalStrategy(item.name);
                    }}
                    disabled={saving}
                    title={item.description || item.name}
                  >
                    {item.description?.split("_")[0] || item.name}
                    {item.locked ? " · 登录" : ""}
                  </button>
                ))}
              </div>
            </div>

            <div className="scan-setting-block">
              <label className="scan-setting-label">K线周期</label>
              <div className="download-mode-tabs">
                {SCAN_PERIOD_OPTIONS.map((item) => (
                  <button
                    key={item.value}
                    className={`toggle-btn ${localScanPeriod === item.value ? "active" : ""}`}
                    onClick={async () => {
                      const saved = await handleSave(localEnabled, localStrategy, scanScopeType, selectedCodes, focusedCodes, item.value);
                      if (saved) setLocalScanPeriod(item.value);
                    }}
                    disabled={saving}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 范围区：范围模式 + 特别关注/指定股票 */}
          <div className="scan-setting-card">
            <div className="scan-scope-head">
              <label className="scan-setting-label">扫描范围</label>
              <div className="download-mode-tabs">
                <button
                  className={`toggle-btn ${scanScopeType === "all" ? "active" : ""}`}
                  onClick={() => {
                    if (!requireSettingsAuth()) return;
                    setScanScopeType("all");
                  }}
                  disabled={saving}
                >
                  全量已下载
                </button>
                <button
                  className={`toggle-btn ${scanScopeType === "selected" ? "active" : ""}`}
                  onClick={() => {
                    if (!requireSettingsAuth()) return;
                    setScanScopeType("selected");
                  }}
                  disabled={saving}
                >
                  指定股票
                </button>
              </div>
            </div>
            <div className="scan-setting-desc">
              全量模式会扫描全部已下载完成的股票；指定模式只扫描你勾选的股票。
            </div>

            {scanScopeType === "all" && (
              <div className="scan-setting-block">
                <label className="scan-setting-label">特别关注代码</label>
                <textarea
                  className="scan-textarea"
                  rows={3}
                  placeholder="输入需要置顶高亮的 6 位代码，支持逗号、空格或换行分隔，例如：600519, 000001"
                  value={focusCodeText}
                  onChange={(e) => setFocusCodeText(e.target.value)}
                  disabled={saving}
                />
                <div className="scan-setting-desc">
                  不影响扫描范围；全量扫描时如果命中特别关注代码，会在扫描结果中优先显示并高亮。
                </div>
                <div className="scan-scope-actions">
                  <button
                    className="toggle-btn active"
                    onClick={handleSaveFocusCodes}
                    disabled={saving}
                  >
                    保存关注
                  </button>
                </div>
              </div>
            )}

            {scanScopeType === "selected" && (
              <div className="scan-setting-block">
                <label className="scan-setting-label">已下载股票选择</label>
                <input
                  className="pretty-input"
                  placeholder="输入代码或名称搜索"
                  value={candidateKeyword}
                  onChange={(e) => {
                    setCandidateKeyword(e.target.value);
                    setCandidatePage(1);
                  }}
                />
                <div className="scan-candidate-list">
                  {loadingCandidates ? (
                    <div className="empty">加载中...</div>
                  ) : candidateItems.length === 0 ? (
                    <div className="empty">暂无已下载完成的股票</div>
                  ) : (
                    candidateItems.map((item) => (
                      <label key={item.code} className="scan-candidate-item">
                        <input
                          type="checkbox"
                          checked={selectedCodes.includes(item.code)}
                          onChange={() => handleToggleCandidate(item.code)}
                        />
                        <span>{item.name}（{item.code}）</span>
                      </label>
                    ))
                  )}
                </div>
                <div className="scan-progress-meta">
                  <span>已选 {selectedCodes.length} 只，候选 {candidateTotal} 只</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      className="toggle-btn"
                      onClick={() => setCandidatePage((prev) => Math.max(1, prev - 1))}
                      disabled={candidatePage <= 1 || loadingCandidates}
                    >
                      上一页
                    </button>
                    <button
                      className="toggle-btn"
                      onClick={() => setCandidatePage((prev) => prev + 1)}
                      disabled={loadingCandidates || candidatePage * 20 >= candidateTotal}
                    >
                      下一页
                    </button>
                  </div>
                </div>
                <div className="scan-scope-actions">
                  <button
                    className="toggle-btn active"
                    onClick={() => handleSave(localEnabled, localStrategy, "selected", selectedCodes, focusedCodes, localScanPeriod)}
                    disabled={saving}
                  >
                    保存范围
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 最近扫描结果 */}
          {status?.latest_run && (
            <div className="scan-result-summary-card">
              <div className="scan-result-summary-header">
                <span>最近扫描</span>
                <span>{status.latest_run.started_at}</span>
              </div>
              <div className="scan-result-summary-main">
                候选 {status.latest_run.candidate_count} 只，实际扫描 {status.latest_run.scanned_count} 只，命中 {status.latest_run.signal_count} 条
              </div>
              {formatBuyIndustrySummary(status.latest_run.buy_industries) && (
                <div className="scan-result-summary-sub">
                  买点主要集中在 {formatBuyIndustrySummary(status.latest_run.buy_industries)}。
                </div>
              )}
            </div>
          )}

          {/* 就绪状态提示 */}
          <div className="scan-setting-summary">
            {localReadyGap > 0 && <div>还有 {localReadyGap} 只未同时满足{requiredPeriodText}本地K线条件</div>}
            <div style={{
              color: scanReady ? "var(--text-muted)" : "#ffa726",
              fontWeight: scanReady ? "normal" : 600,
              fontSize: scanReady ? undefined : 13,
            }}>{status?.scan_ready_message || "请先准备本地扫描数据"}</div>
          </div>

          {/* 规则说明：默认折叠，减少杂乱 */}
          <details className="scan-rule-details">
            <summary>扫描规则说明</summary>
            <div className="scan-setting-hint">
              <div>过滤条件：非ST、总市值大于100亿、日线收盘站上144均线。</div>
              <div>扫描范围：仅扫描本地已具备{requiredPeriodText}数据的股票，有数据即可扫描。</div>
              <div>信号判定：使用本地{scanPeriodLabel}历史K线，并叠加当前实时尾部数据，仅记录最新K线附近触发的买卖点；买入后按 T+1 交易原则处理。</div>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
