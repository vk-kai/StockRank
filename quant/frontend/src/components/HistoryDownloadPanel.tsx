import { useEffect, useMemo, useState } from "react";
import type { HistoryDownloadStatus, HistoryDownloadTimeSpanOption } from "../types";
import { HISTORY_DOWNLOAD_TIME_SPANS } from "../types";

const REQUIRED_DOWNLOAD_PERIODS = ["daily", "30min"];

interface Props {
  status: HistoryDownloadStatus | null;
  onStart: (params: { periods: string[]; force_refresh?: boolean; codes?: string[]; time_span?: string }) => Promise<void>;
  autoDownloadEnabled?: boolean;
  autoDownloadHour?: number;
  klineForceRefresh?: boolean;
  onAutoDownloadChange?: (enabled: boolean, hour: number) => void;
  onKlineForceRefreshChange?: (enabled: boolean) => void;
}

function getDownloadedPeriodLabel(period?: string) {
  return ({
    "1min": "1分钟",
    "5min": "5分钟",
    "15min": "15分钟",
    "30min": "30分钟",
    "60min": "60分钟",
    daily: "日K",
    weekly: "周K",
    monthly: "月K",
  } as Record<string, string>)[period || ""] || period || "";
}

function formatCountdown(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(safeSeconds / 60);
  const restSeconds = safeSeconds % 60;
  return `${minutes}分${String(restSeconds).padStart(2, "0")}秒`;
}

export default function HistoryDownloadPanel({
  status,
  onStart,
  autoDownloadEnabled = true,
  autoDownloadHour = 15,
  klineForceRefresh = false,
  onAutoDownloadChange,
  onKlineForceRefreshChange,
}: Props) {
  const [selectedPeriods, setSelectedPeriods] = useState<string[]>(REQUIRED_DOWNLOAD_PERIODS);
  const [targetMode, setTargetMode] = useState("filtered");
  const [codeText, setCodeText] = useState("");
  const [starting, setStarting] = useState(false);
  const [selectedTimeSpan, setSelectedTimeSpan] = useState<string>("1m");
  const [nowMs, setNowMs] = useState(Date.now());

  useEffect(() => {
    setTargetMode(status?.target_mode || "filtered");
  }, [status?.target_mode]);

  useEffect(() => {
    if (status?.time_span) {
      setSelectedTimeSpan(status.time_span);
    }
  }, [status?.time_span]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const optionMap = useMemo(
    () => new Map((status?.period_options || []).map((item) => [item.value, item])),
    [status?.period_options]
  );

  const timeSpanOption = useMemo(
    () => HISTORY_DOWNLOAD_TIME_SPANS.find((item) => item.value === selectedTimeSpan) || HISTORY_DOWNLOAD_TIME_SPANS[0],
    [selectedTimeSpan]
  );

  const downloadedPeriodSummaries = useMemo(() => {
    const dayCounts = status?.kline_period_days || {};
    return (status?.period_options || [])
      .map((item) => ({
        period: item.value,
        label: getDownloadedPeriodLabel(item.value),
        days: Math.max(0, Math.round(Number(dayCounts[item.value] || 0))),
      }))
      .filter((item) => item.days > 0);
  }, [status?.kline_period_days, status?.period_options]);

  const autoDownloadCountdownSeconds = useMemo(() => {
    if (!status?.auto_download_next_check_at) {
      return Number(status?.auto_download_next_check_seconds || 0);
    }
    const nextCheckMs = new Date(status.auto_download_next_check_at.replace(" ", "T")).getTime();
    if (!Number.isFinite(nextCheckMs)) {
      return Number(status.auto_download_next_check_seconds || 0);
    }
    return Math.max(0, Math.floor((nextCheckMs - nowMs) / 1000));
  }, [nowMs, status?.auto_download_next_check_at, status?.auto_download_next_check_seconds]);

  const shouldShowAutoDownloadCountdown = Boolean(
    autoDownloadEnabled
    && status?.auto_download_next_check_at
    && !status?.auto_download_today_started
    && !status?.auto_download_today_done
    && !["before_window", "not_trading_day", "already_updated", "disabled"].includes(status?.auto_download_status || "")
  );

  const handleTogglePeriod = (period: string) => {
    if (REQUIRED_DOWNLOAD_PERIODS.includes(period)) return;
    setSelectedPeriods((prev) => (
      prev.includes(period)
        ? prev.filter((item) => item !== period)
        : [...prev, period]
    ));
  };

  const handleForceRefreshChange = (checked: boolean) => {
    if (checked) {
      const confirmed = window.confirm("开启强制覆盖后，手动下载和自动下载都会先删除已存在的本地K线再重新下载。确定开启吗？");
      if (!confirmed) return;
    }
    onKlineForceRefreshChange?.(checked);
  };

  const handleAutoDownloadChange = (checked: boolean) => {
    const actionText = checked ? "开启" : "关闭";
    const confirmed = window.confirm(`确定${actionText}每个交易日 ${autoDownloadHour}:00 后自动下载更新K线吗？`);
    if (!confirmed) return;
    onAutoDownloadChange?.(checked, autoDownloadHour);
  };

  const handleStart = async () => {
    const requiredPeriods = Array.from(new Set(REQUIRED_DOWNLOAD_PERIODS));
    const effectivePeriods = Array.from(new Set([...selectedPeriods, ...requiredPeriods]));
    if (effectivePeriods.length === 0) return;
    const codes = Array.from(
      new Set(
        codeText
          .split(/[\s,，;；]+/)
          .map((item) => item.trim())
          .map((item) => item.replace(/\D/g, ""))
          .filter((item) => item.length === 6)
      )
    );
    if (targetMode === "selected" && codes.length === 0) return;
    if (klineForceRefresh) {
      const confirmed = window.confirm("将先删除已存在的本地K线，再重新下载所选范围的数据。确定要强制覆盖吗？");
      if (!confirmed) return;
    }
    setStarting(true);
    try {
      await onStart({
        periods: effectivePeriods,
        force_refresh: klineForceRefresh,
        codes: targetMode === "selected" ? codes : [],
        time_span: selectedTimeSpan,
      });
    } finally {
      setStarting(false);
    }
  };

  const currentPeriodLabel = status?.current_period ? optionMap.get(status.current_period)?.label || status.current_period : "";
  const aShareFetchedCount = status?.a_share_fetched_count || 0;
  const rawTotalCount = status?.raw_total_count || 0;
  const isSelectedDownload = status?.target_mode === "selected";
  const displayTotalCount = status?.total_count || (isSelectedDownload ? status?.requested_code_count || 0 : rawTotalCount) || 0;
  const removedStCount = status?.removed_st_count || 0;
  const removedMarketCapCount = status?.removed_market_cap_count || 0;
  const removedDelistedCount = status?.removed_delisted_count || 0;
  const removedMaCount = status?.removed_ma_count || 0;
  const qualifiedCount = status?.qualified_count ?? status?.total_count ?? 0;
  const finalStockCount = status?.final_stock_count || 0;
  const finalEtfCount = status?.final_etf_count || 0;
  const finalIndexCount = status?.final_index_count || 0;
  const localReadyCount = status?.kline_downloaded_count || 0;
  const scanEligibleCount = status?.scan_eligible_count || 0;
  const downloadProgress = status?.current_index || 0;
  const downloadTotal = status?.kline_downloaded_count || 0;
  const localReadyGap = Math.max(qualifiedCount - localReadyCount, 0);
  const liveReadyCount = status?.ready_count || 0;
  const liveValidatedCount = isSelectedDownload ? liveReadyCount : status?.qualified_count || 0;
  const liveRejectedCount = isSelectedDownload ? 0 : status?.removed_ma_count || 0;
  const livePendingCount = Math.max(displayTotalCount - downloadProgress, 0);
  const totalCountText = (() => {
    if (status?.total_count && status.total_count > 0) return String(status.total_count);
    if (status?.running && (status.stage === "collecting" || status.stage === "screening")) return "处理中";
    if ((status?.last_started_at || status?.last_finished_at || (status?.selection_total_count || 0) > 0)) return "0";
    return "未生成";
  })();

  const formatRemainingTime = (seconds: number | undefined): string => {
    if (!seconds || seconds <= 0) return "";
    if (seconds < 60) return `${Math.round(seconds)}秒`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return `${hours}小时${minutes > 0 ? `${minutes}分钟` : ""}`;
  };

  const estimatedRemainingText = formatRemainingTime(status?.estimated_remaining_seconds);

  const runtimeInfo = status?.runtime_info;

  const runtimeTitle = isSelectedDownload
    ? (status?.stage === "finalizing" ? "指定代码入库中" : "指定代码下载中")
    : status?.stage === "collecting"
      ? "第1步 初始化基础池"
      : status?.stage === "screening"
        ? "第1步 并行过滤基础池"
        : "下载与验证中";

  return (
    <div className="scan-setting-card">
      <div className="scan-setting-title">本地K线周期</div>
      <div className="scan-setting-desc">
        历史K线会保存到本地，实时价格与盘口继续走实时行情接口。下载完成后，其他客户端也可直接复用本地数据。
      </div>

      <div className="scan-setting-block">
        <label className="scan-setting-label">下载模式</label>
        <div className="download-mode-tabs">
          <button
            className={`toggle-btn ${targetMode === "filtered" ? "active" : ""}`}
            onClick={() => setTargetMode("filtered")}
            disabled={starting || !!status?.running}
          >
            按规则下载
          </button>
          <button
            className={`toggle-btn ${targetMode === "selected" ? "active" : ""}`}
            onClick={() => setTargetMode("selected")}
            disabled={starting || !!status?.running}
          >
            指定代码下载
          </button>
        </div>
      </div>

      <div className="scan-setting-block">
        <label className="scan-setting-label">时间跨度</label>
        <div className="download-mode-tabs">
          {HISTORY_DOWNLOAD_TIME_SPANS.map((option) => (
            <button
              key={option.value}
              className={`toggle-btn ${selectedTimeSpan === option.value ? "active" : ""}`}
              onClick={() => setSelectedTimeSpan(option.value)}
              disabled={starting || !!status?.running}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="scan-setting-desc">
          从今天起往回推 {timeSpanOption.label} 的历史K线数据
        </div>
      </div>

      {targetMode === "selected" && (
        <div className="scan-setting-block">
          <label className="scan-setting-label">指定代码</label>
          <textarea
            className="scan-textarea"
            rows={4}
            placeholder="输入 6 位股票代码，支持逗号、空格或换行分隔，例如：600519, 000001"
            value={codeText}
            onChange={(e) => setCodeText(e.target.value)}
            disabled={starting || !!status?.running}
          />
          <div className="scan-setting-desc">
            指定代码模式会跳过规则下载流程，直接下载这些标的的本地历史数据，并打上手动下载标记。
          </div>
        </div>
      )}

      <div className="download-period-grid">
        {(status?.period_options || []).map((item) => {
          const isRequired = REQUIRED_DOWNLOAD_PERIODS.includes(item.value);
          const checked = isRequired || selectedPeriods.includes(item.value);
          return (
            <label key={item.value} className={`download-period-chip ${checked ? "active" : ""}`}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => {
                  if (!isRequired) handleTogglePeriod(item.value);
                }}
                disabled={isRequired || starting || !!status?.running}
              />
              <span>{item.label}{isRequired ? "（必选）" : ""}</span>
            </label>
          );
        })}
      </div>

      <label className={`download-switch-row ${klineForceRefresh ? "active" : ""}`}>
        <input
          type="checkbox"
          checked={klineForceRefresh}
          onChange={(e) => handleForceRefreshChange(e.target.checked)}
          disabled={starting || !!status?.running}
        />
        <span className="download-switch-track" aria-hidden="true">
          <span className="download-switch-thumb" />
        </span>
        <span className="download-switch-text">强制覆盖已有本地K线</span>
      </label>

      <label className={`download-switch-row ${autoDownloadEnabled ? "active" : ""}`}>
        <input
          type="checkbox"
          checked={autoDownloadEnabled}
          onChange={(e) => handleAutoDownloadChange(e.target.checked)}
          disabled={!!status?.running}
        />
        <span className="download-switch-track" aria-hidden="true">
          <span className="download-switch-thumb" />
        </span>
        <span className="download-switch-text">每个交易日 {autoDownloadHour}:00 后自动下载更新</span>
      </label>

      {shouldShowAutoDownloadCountdown && (
        <div className="scan-setting-desc" style={{ marginTop: -6 }}>
          距离自动下载检查 {formatCountdown(autoDownloadCountdownSeconds)}
        </div>
      )}

      {status?.kline_latest_date && (
        <div className="scan-setting-desc" style={{ marginTop: 4 }}>
          数据已更新至：{status.kline_latest_date}
        </div>
      )}

      {downloadedPeriodSummaries.length > 0 && (
        <div className="kline-counts-summary">
          <span className="kline-count-label">当前已下载K线：</span>
          {downloadedPeriodSummaries.map((item) => (
            <span key={item.period} className="kline-count-tag">
              {item.label}：{item.days}天
            </span>
          ))}
        </div>
      )}

      {runtimeInfo && (
        <div className="runtime-info-card">
          <div className="download-stats-row">
            <span className="download-stat-item">
              <span className="download-stat-value">{runtimeInfo.cpu_count}</span>
              <span className="download-stat-label">CPU 核心</span>
            </span>
            <span className="download-stat-divider">|</span>
            <span className="download-stat-item" title={`环境变量 TRENDZEN_CPU_WORKER_LIMIT=${runtimeInfo.cpu_worker_limit_env}`}>
              <span className="download-stat-value">{runtimeInfo.cpu_workers_scan}</span>
              <span className="download-stat-label">扫描并发</span>
            </span>
            <span className="download-stat-divider">|</span>
            <span className="download-stat-item" title={`环境变量 TRENDZEN_CPU_WORKER_LIMIT=${runtimeInfo.cpu_worker_limit_env}`}>
              <span className="download-stat-value">{runtimeInfo.cpu_workers_backtest}</span>
              <span className="download-stat-label">回测并发</span>
            </span>
            <span className="download-stat-divider">|</span>
            <span className="download-stat-item" title={`环境变量 TRENDZEN_IO_WORKER_LIMIT=${runtimeInfo.io_worker_limit_env}`}>
              <span className="download-stat-value">{runtimeInfo.io_workers_download}</span>
              <span className="download-stat-label">下载并发</span>
            </span>
            <span className="download-stat-divider">|</span>
            <span className="download-stat-item" title={`环境变量 TRENDZEN_IO_WORKER_LIMIT=${runtimeInfo.io_worker_limit_env}`}>
              <span className="download-stat-value">{runtimeInfo.io_workers_market}</span>
              <span className="download-stat-label">行情并发</span>
            </span>
          </div>
        </div>
      )}

        <div className="download-actions">
        <button
          className={`setting-primary-btn ${status?.running ? 'progress-btn' : ''}`}
          onClick={handleStart}
          style={status?.running ? {
            '--progress-width': `${status?.progress_pct || 0}%`
          } as any : {}}
          disabled={
            starting
            || !!status?.running
            || (targetMode === "selected" && codeText.trim().length === 0)
          }
        >
          <span className="btn-text">
            {starting || status?.running 
              ? `下载中 ${status?.progress_pct || 0}%` 
              : "开始数据下载"}
          </span>
        </button>
        {!status?.running && downloadTotal > 0 && (
        <div className="download-stats-row">
          <span className="download-stat-item">
            <span className="download-stat-value">{downloadTotal}</span>
            <span className="download-stat-label">已下载</span>
          </span>
          <span className="download-stat-divider">|</span>
          <span className="download-stat-item">
            <span className="download-stat-value">{scanEligibleCount}</span>
            <span className="download-stat-label">可扫描</span>
          </span>
        </div>
        )}
      </div>

      <div className="download-hint-list">
        {!status?.running && (!status?.total_count || status.total_count <= 0) && (
          <div>当前还没有生成下载结果，开始执行后会按所选模式创建下载任务。</div>
        )}
      </div>

      {(status?.running || status?.error) && (
        <div className="scan-runtime-card">
          <div className="scan-runtime-title">{runtimeTitle}</div>
          <div className="scan-runtime-text">
            {status?.error
              ? `下载失败：${status.error}`
              : status?.current_message || "正在处理数据下载..."}
          </div>
          {(status?.stage === "collecting" || status?.stage === "screening") && (
            <div className="download-runtime-meta">
              {status?.stage === "collecting"
                ? `正在获取A股股票池，已获取 ${aShareFetchedCount} 个`
                : `已处理 ${status?.selection_index || 0}/${status?.selection_total_count || 0}，去除ST ${removedStCount} 个，去除市值不足 ${removedMarketCapCount} 个，当前基础池 ${status?.raw_stock_count || 0} 个`}
            </div>
          )}
          {status?.stage === "downloading" && (
            <>
              <div className="download-runtime-meta">
                {isSelectedDownload
                  ? `正在并行下载指定代码 ${downloadProgress}/${displayTotalCount}，本地可用 ${liveReadyCount} 个，待完成 ${livePendingCount} 个`
                  : `正在并行下载历史数据 ${downloadProgress}/${displayTotalCount}，144验证通过 ${liveValidatedCount} 个，淘汰 ${liveRejectedCount} 个，待验证 ${livePendingCount} 个`}
              </div>
              {!!status?.current_code && (
                <div className="download-runtime-meta">
                  {`当前标的：${status.current_name || status.current_code}（${status.current_code}）`}
                </div>
              )}
            </>
          )}
          {status?.stage === "finalizing" && (
            <div className="download-runtime-meta">
              {isSelectedDownload
                ? `正在写入K线元数据和手动下载标记 ${downloadProgress}/${displayTotalCount}`
                : `去除不符合日线144均线 ${removedMaCount} 个，当前最终可扫描 ${qualifiedCount} 个`}
            </div>
          )}
          {!!currentPeriodLabel && (
            <div className="download-runtime-meta">
              当前周期：{currentPeriodLabel}
            </div>
          )}
          {status?.current_download_date && (
            <div className="download-runtime-meta">
              当前日期：{status.current_download_date}
            </div>
          )}
          {!!estimatedRemainingText && (
            <div className="download-runtime-meta">
              预计剩余时间：{estimatedRemainingText}
            </div>
          )}
          <div className="scan-progress-track">
            <div
              className="scan-progress-fill"
              style={{ width: `${status?.progress_pct || 0}%` }}
            />
          </div>
          <div className="scan-progress-meta">
            <span>
              {status?.stage === "collecting"
                ? `${aShareFetchedCount}/` + `${Math.max(aShareFetchedCount, status?.selection_total_count || aShareFetchedCount)}`
                : status?.stage === "screening"
                ? `${status?.selection_index || 0}/${status?.selection_total_count || 0}`
                : `${downloadProgress}/${displayTotalCount}`}
            </span>
            <span>进度 {status?.progress_pct || 0}%</span>
          </div>
        </div>
      )}

    </div>
  );
}
