import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteFullBacktestHistory,
  fetchBacktestSettings,
  fetchBacktestStatus,
  fetchFullBacktestHistory,
  fetchFullBacktestHistoryDetail,
  fetchFullBacktestStockDetail,
  fetchScanStatus,
  fetchStrategies,
  startBacktest,
} from "../api";
import { fetchKline } from "../api/market";
import EquityCurveChart from "./EquityCurveChart";
import { buildBiaoliResult, BIAOLI_GROUPS, type BiaoliGroupKey, type BiaoliResult } from "../lib/biaoli";
import type { AuthUser } from "../api/auth";
import type {
  BacktestResult,
  BatchBucketItem,
  BatchExtremeDetail,
  BacktestRuntimeStatus,
  FullBacktestHistoryItem,
  FullBacktestSummary,
  KlineData,
  StrategyInfo,
  TradeRecordItem,
} from "../types";

interface Props {
  code: string;
  name: string;
  selectedPeriod?: string;
  onRunComplete?: (result: BacktestResult) => void;
  onClearSignals?: () => void;
  onSelectTrade?: (trade: TradeRecordItem) => void;
  onInspectBatchDetail?: (detail: BatchExtremeDetail, focusTrade?: TradeRecordItem) => void;
  selectedTrade?: { timestamp?: number; direction: string } | null;
  authUser?: AuthUser | null;
  defaultStrategy?: string;
  onRequireLogin?: (reason?: string) => void;
}

async function requestBacktestNotificationPermission() {
  if (!("Notification" in window) || Notification.permission !== "default") return;
  try {
    await Notification.requestPermission();
  } catch {
    // A denied or unsupported browser notification must not block a backtest.
  }
}

type QuickRangePreset =
  | "1d" | "1w" | "1m" | "6m" | "1y" | "2y"
  | "stress_2015" | "stress_2018" | "stress_2020" | "stress_2024_01" | "stress_2024_09"
  | null;
const BACKTEST_PERIODS = new Set(["1", "5", "15", "30", "60", "120", "daily", "weekly", "monthly"]);

function normalizeBacktestPeriod(period?: string) {
  if (period === "intraday") return "1";
  return period && BACKTEST_PERIODS.has(period) ? period : "daily";
}

function formatDateInput(date: Date) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function getMostRecentTradingDay(date: Date) {
  const d = new Date(date);
  const day = d.getDay();
  if (day === 0) d.setDate(d.getDate() - 2);
  else if (day === 6) d.setDate(d.getDate() - 1);
  return d;
}

function shiftTradingDays(date: Date, tradingDays: number) {
  const d = new Date(date);
  let left = tradingDays;
  while (left > 0) {
    d.setDate(d.getDate() - 1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) {
      left -= 1;
    }
  }
  return d;
}

function getTradeMarkerTimestamp(trade: TradeRecordItem) {
  return trade.timestamp ?? trade.signal_timestamp;
}

function getQuickRange(preset: Exclude<QuickRangePreset, null>) {
  // 极端区间(固定历史日期,用于压力测试;需本地有足够长的历史数据)
  const stressRanges: Record<string, { startDate: string; endDate: string }> = {
    stress_2015: { startDate: "2015-06-15", endDate: "2015-09-15" }, // 杠杆牛市崩盘
    stress_2018: { startDate: "2018-06-01", endDate: "2018-12-31" }, // 中美贸易战
    stress_2020: { startDate: "2020-02-01", endDate: "2020-04-30" }, // 新冠疫情冲击
    stress_2024_01: { startDate: "2024-01-01", endDate: "2024-03-31" }, // 微盘股崩盘
    stress_2024_09: { startDate: "2024-09-24", endDate: "2024-10-08" }, // 9·24 政策行情
  };
  if ((preset as string) in stressRanges) {
    return stressRanges[preset as string];
  }

  const end = getMostRecentTradingDay(new Date());
  let start = new Date(end);

  if (preset === "1d") {
    start = shiftTradingDays(end, 1);
  } else if (preset === "1w") {
    start = shiftTradingDays(end, 5);
  } else if (preset === "1m") {
    start = shiftTradingDays(end, 21);
  } else if (preset === "6m") {
    start = shiftTradingDays(end, 126);
  } else if (preset === "1y") {
    start = shiftTradingDays(end, 252);
  } else if (preset === "2y") {
    start = shiftTradingDays(end, 504);
  }

  return {
    startDate: formatDateInput(start),
    endDate: formatDateInput(end),
  };
}

function getSuggestedRange(period: string) {
  const end = new Date();
  const start = new Date(end);

  const tradingDay = getMostRecentTradingDay(end);

  if (period === "1" || period === "5" || period === "15" || period === "intraday") {
    return {
      startDate: formatDateInput(tradingDay),
      endDate: formatDateInput(tradingDay),
    };
  }

  if (period === "30") {
    return {
      startDate: formatDateInput(shiftTradingDays(tradingDay, 4)),
      endDate: formatDateInput(tradingDay),
    };
  }

  if (period === "60") {
    return {
      startDate: formatDateInput(shiftTradingDays(tradingDay, 9)),
      endDate: formatDateInput(tradingDay),
    };
  }

  if (period === "120") {
    return {
      startDate: formatDateInput(shiftTradingDays(tradingDay, 18)),
      endDate: formatDateInput(tradingDay),
    };
  }

  // 日线级别默认选择过去一年
  start.setFullYear(end.getFullYear() - 1);
  return {
    startDate: formatDateInput(start),
    endDate: formatDateInput(end),
  };
}

function getTradePriceDigits(period?: string) {
  return period && !["daily", "weekly", "monthly", "quarter", "year"].includes(period) ? 5 : 3;
}

function formatTradeDate(dateText: string) {
  const normalized = dateText.replace("T", " ").trim();
  const match = normalized.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (!match) {
    return dateText;
  }

  const [, yyyy, mm, dd, hh = "00", min = "00"] = match;
  return `${yyyy}/${Number(mm)}/${Number(dd)} ${hh.padStart(2, "0")}:${min}`;
}

function formatPct(value?: number | null, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatRatioPct(value?: number | null, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${Math.max(0, value).toFixed(digits)}%`;
}

function getReturnColor(value?: number | null) {
  if (value == null || Number.isNaN(value) || value === 0) return "var(--text-muted)";
  return value > 0 ? "var(--accent-red)" : "var(--accent-green)";
}

// 趋势质量评级配色：A=强主升(红/好) B=一般(琥珀) C=下跌中继风险(绿/差)
function qualityBadgeColor(score?: number | null) {
  if (score == null) return "var(--text-muted)";
  if (score >= 75) return "var(--accent-red)";
  if (score >= 55) return "#d8a017";
  return "var(--accent-green)";
}

function getPeriodLabel(period: string) {
  if (period === "daily") return "日线";
  if (period === "weekly") return "周线";
  if (period === "monthly") return "月线";
  if (period === "quarter") return "季线";
  if (period === "year") return "年线";
  return `${period}分钟`;
}

function getStrategyLabel(strategyName: string, strategies: StrategyInfo[]) {
  return strategies.find((item) => item.name === strategyName)?.description || strategyName;
}

function getShortStrategyLabel(strategyName: string, strategies: StrategyInfo[]) {
  return Array.from(getStrategyLabel(strategyName, strategies)).slice(0, 5).join("");
}

function formatStockBucket(count: number, avgReturn?: number | null) {
  return `${count} (${formatPct(avgReturn ?? null)})`;
}

function formatProfitAmount(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function hasValidNumber(value?: number | null): value is number {
  return value != null && !Number.isNaN(value);
}

function averageBucketReturn(items?: BatchBucketItem[]) {
  if (!items || items.length === 0) return undefined;
  return items.reduce((sum, item) => sum + item.total_return, 0) / items.length;
}

function getProfitableAverageReturn(summary?: FullBacktestSummary | null) {
  if (!summary) return null;
  if (hasValidNumber(summary.profitable_average_return)) return summary.profitable_average_return;
  return summary.profitable_count === 0 ? 0 : null;
}

function getLossAverageReturn(summary?: FullBacktestSummary | null) {
  if (!summary) return null;
  if (hasValidNumber(summary.loss_average_return)) return summary.loss_average_return;
  return summary.loss_count === 0 ? 0 : null;
}

function getRoundTripReturnSpread(summary?: FullBacktestSummary | null) {
  if (!summary) return null;
  const profitableAvg = getProfitableAverageReturn(summary);
  const lossAvg = getLossAverageReturn(summary);
  if (profitableAvg == null || lossAvg == null) return null;
  return Math.abs(profitableAvg) - Math.abs(lossAvg);
}

function getRoundTripSpreadSubtitle(summary?: FullBacktestSummary | null) {
  if (!summary) return "历史数据暂无完整交易均值明细";
  const profitableAvg = getProfitableAverageReturn(summary);
  const lossAvg = getLossAverageReturn(summary);
  if (profitableAvg == null || lossAvg == null) {
    return "历史数据暂无完整交易均值明细";
  }
  return `均盈 ${formatPct(profitableAvg)} / 均亏 ${formatPct(lossAvg)}`;
}

function formatRoundTripReturnSpread(summary?: FullBacktestSummary | null) {
  return formatPct(getRoundTripReturnSpread(summary));
}

function formatRangeEdge(value: number) {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

function formatDistributionRange(start: number, end: number, bucketType: "profit" | "loss") {
  const prefix = bucketType === "profit" ? "收益率" : "亏损幅度";
  return `${prefix} ${formatRangeEdge(start)}%-${formatRangeEdge(end)}%`;
}

function calculateJenksBreaks(values: number[], desiredClassCount = 6) {
  const sorted = values
    .filter((value) => Number.isFinite(value))
    .map((value) => Math.max(0, value))
    .sort((a, b) => a - b);
  if (sorted.length === 0) return [0, 0];

  const uniqueCount = new Set(sorted.map((value) => value.toFixed(6))).size;
  const classCount = Math.max(1, Math.min(desiredClassCount, uniqueCount));
  if (classCount === 1) {
    return [0, sorted[sorted.length - 1]];
  }

  const lowerClassLimits = Array.from({ length: sorted.length + 1 }, () => Array(classCount + 1).fill(0));
  const varianceCombinations = Array.from({ length: sorted.length + 1 }, () => Array(classCount + 1).fill(Number.POSITIVE_INFINITY));

  for (let i = 1; i <= classCount; i += 1) {
    lowerClassLimits[1][i] = 1;
    varianceCombinations[1][i] = 0;
    for (let j = 2; j <= sorted.length; j += 1) {
      varianceCombinations[j][i] = Number.POSITIVE_INFINITY;
    }
  }

  for (let l = 2; l <= sorted.length; l += 1) {
    let sum = 0;
    let sumSquares = 0;
    let w = 0;

    for (let m = 1; m <= l; m += 1) {
      const lowerClassLimit = l - m + 1;
      const value = sorted[lowerClassLimit - 1];

      w += 1;
      sum += value;
      sumSquares += value * value;

      const variance = sumSquares - (sum * sum) / w;
      const previousIndex = lowerClassLimit - 1;
      if (previousIndex !== 0) {
        for (let j = 2; j <= classCount; j += 1) {
          const candidate = variance + varianceCombinations[previousIndex][j - 1];
          if (varianceCombinations[l][j] >= candidate) {
            lowerClassLimits[l][j] = lowerClassLimit;
            varianceCombinations[l][j] = candidate;
          }
        }
      }
    }

    lowerClassLimits[l][1] = 1;
    varianceCombinations[l][1] = sumSquares - (sum * sum) / w;
  }

  const breaks = Array(classCount + 1).fill(0);
  breaks[classCount] = sorted[sorted.length - 1];
  breaks[0] = 0;

  let k = sorted.length;
  for (let j = classCount; j >= 2; j -= 1) {
    const index = lowerClassLimits[k][j] - 1;
    breaks[j - 1] = sorted[Math.max(0, index)];
    k = lowerClassLimits[k][j] - 1;
  }

  const normalizedBreaks = breaks.map((value, index) => {
    if (index === 0) return 0;
    if (index === breaks.length - 1) return Math.max(value, sorted[sorted.length - 1]);
    return Math.max(value, breaks[index - 1]);
  });

  return normalizedBreaks.filter((value, index) => index === 0 || value > normalizedBreaks[index - 1]);
}

function buildJenksSegments(values: number[], bucketType: "profit" | "loss", desiredClassCount = 6) {
  const breaks = calculateJenksBreaks(values, desiredClassCount);
  if (breaks.length < 2) return [];

  const segments = [];
  for (let index = 0; index < breaks.length - 1; index += 1) {
    const start = breaks[index];
    const end = breaks[index + 1];
    const isLast = index === breaks.length - 2;
    const count = values.filter((value) => (isLast ? value >= start && value <= end : value >= start && value < end)).length;
    if (count <= 0) continue;
    segments.push({
      start,
      end,
      isLast,
      count,
      label: formatDistributionRange(start, end, bucketType),
    });
  }
  return segments;
}

function buildBucketOverview(items: BatchBucketItem[], bucketType: "profit" | "loss") {
  if (items.length === 0) return null;

  const absoluteReturns = items
    .map((item) => Math.abs(item.total_return))
    .filter((value) => Number.isFinite(value));

  if (absoluteReturns.length === 0) return null;

  const stockCount = items.length;
  const totalTrades = items.reduce((sum, item) => sum + item.round_trip_trades, 0);
  const totalReturn = items.reduce((sum, item) => sum + item.total_return, 0);
  const averageStockReturn = totalReturn / stockCount;
  const averageTradeReturn = totalTrades > 0 ? totalReturn / totalTrades : null;
  const maxAbsReturn = Math.max(...absoluteReturns);
  const jenksSegments = buildJenksSegments(absoluteReturns, bucketType, 6);
  const modeSegment = jenksSegments.reduce(
    (best, current) => (current.count > best.count ? current : best),
    jenksSegments[0],
  );
  const distributionSegments = jenksSegments.map((item) => ({
    start: item.start,
    end: item.end,
    isLast: item.isLast,
    label: item.label,
    count: item.count,
    emphasis: item.label === modeSegment.label,
  }));

  return {
    bucketType,
    stockCount,
    totalTrades,
    averageStockReturn,
    averageTradeReturn,
    maxAbsReturn,
    distributionSegments,
    modeLabel: modeSegment.label,
    modeCount: modeSegment.count,
    classCount: jenksSegments.length,
    breaksHint: "按 Jenks 自然断点自动分组，再取股票数量最多的区间作为分布中心。",
  };
}

function formatBatchPeriod(summary: FullBacktestSummary) {
  const end = summary.range_end || "至今";
  return `${summary.range_start} - ${end} | ${getPeriodLabel(summary.period)}`;
}

function resolveHistorySummary(item?: FullBacktestHistoryItem | null): FullBacktestSummary | null {
  if (!item) return null;
  return item.payload?.summary || {
    strategy_name: item.strategy_name,
    period: item.period,
    range_start: item.start_date,
    range_end: item.end_date,
    target_count: item.target_count,
    success_count: item.success_count,
    failed_count: item.failed_count,
    backtest_failed_count: item.failed_count,
    backtest_success_target_count: item.success_count,
    traded_target_count: item.profitable_count + item.loss_count,
    profitable_count: item.profitable_count,
    loss_count: item.loss_count,
    win_rate: item.win_rate,
    cumulative_return: item.cumulative_return,
    average_return: item.average_return,
    max_drawdown: item.max_drawdown,
    max_gain: item.max_gain,
    profitable_average_return: averageBucketReturn(item.payload?.profitable_items),
    loss_average_return: averageBucketReturn(item.payload?.loss_items),
  };
}

function buildBatchResultFromHistory(item: FullBacktestHistoryItem): BacktestResult {
  const summary = resolveHistorySummary(item);
  return {
    success: true,
    mode: "batch",
    strategy_name: item.strategy_name,
    period: item.period,
    range_start: item.start_date,
    range_end: item.end_date,
    batch_run_id: item.id,
    batch_summary: summary || undefined,
    message: "已加载指定全量回测结果",
  };
}

function CompareModal({
  current,
  history,
  historyOptions,
  selectedHistoryId,
  onSelectHistory,
  resolveStrategyLabel,
  onClose,
}: {
  current: FullBacktestSummary;
  history: FullBacktestSummary | null;
  historyOptions: FullBacktestHistoryItem[];
  selectedHistoryId: number | null;
  onSelectHistory: (id: number) => void;
  resolveStrategyLabel: (strategyName: string) => string;
  onClose: () => void;
}) {
  const currentTradedTargetCount = current.traded_target_count ?? (current.profitable_count + current.loss_count);
  const historyTradedTargetCount = history ? (history.traded_target_count ?? (history.profitable_count + history.loss_count)) : 0;
  const currentSpread = getRoundTripReturnSpread(current);
  const historySpread = history ? getRoundTripReturnSpread(history) : null;
  const rows = [
    { label: "回测周期", current: formatBatchPeriod(current), history: history ? formatBatchPeriod(history) : "--", delta: "--", currentValue: null },
    { label: "累计收益率", current: formatPct(current.cumulative_return), history: history ? formatPct(history.cumulative_return) : "--", delta: history ? formatPct(current.cumulative_return - history.cumulative_return) : "--", deltaValue: history ? current.cumulative_return - history.cumulative_return : null, currentValue: current.cumulative_return },
    { label: "平均收益率", current: formatPct(current.average_return), history: history ? formatPct(history.average_return) : "--", delta: history ? formatPct(current.average_return - history.average_return) : "--", deltaValue: history ? current.average_return - history.average_return : null, currentValue: current.average_return },
    { label: "最大回撤", current: formatPct(current.max_drawdown), history: history ? formatPct(history.max_drawdown) : "--", delta: history ? formatPct(current.max_drawdown - history.max_drawdown) : "--", deltaValue: history ? current.max_drawdown - history.max_drawdown : null, currentValue: null },
    { label: "最大涨幅", current: formatPct(current.max_gain), history: history ? formatPct(history.max_gain) : "--", delta: history ? formatPct(current.max_gain - history.max_gain) : "--", deltaValue: history ? current.max_gain - history.max_gain : null, currentValue: current.max_gain },
    { label: "交易股票数", current: `${currentTradedTargetCount}/${current.target_count}`, history: history ? `${historyTradedTargetCount}/${history.target_count}` : "--", delta: history ? `${currentTradedTargetCount - historyTradedTargetCount}` : "--", deltaValue: history ? currentTradedTargetCount - historyTradedTargetCount : null, currentValue: null },
    { label: "盈利股票", current: formatStockBucket(current.profitable_count, current.profitable_cumulative_return), history: history ? formatStockBucket(history.profitable_count, history.profitable_cumulative_return) : "--", delta: history ? `${current.profitable_count - history.profitable_count}` : "--", deltaValue: history ? current.profitable_count - history.profitable_count : null, currentValue: null },
    { label: "亏损股票", current: formatStockBucket(current.loss_count, current.loss_cumulative_return), history: history ? formatStockBucket(history.loss_count, history.loss_cumulative_return) : "--", delta: history ? `${current.loss_count - history.loss_count}` : "--", deltaValue: history ? current.loss_count - history.loss_count : null, currentValue: null },
    { label: "单笔平均收益率", current: formatRoundTripReturnSpread(current), history: history ? formatRoundTripReturnSpread(history) : "--", historyValue: historySpread, delta: history && currentSpread != null && historySpread != null ? formatPct(currentSpread - historySpread) : "--", deltaValue: history && currentSpread != null && historySpread != null ? currentSpread - historySpread : null, currentValue: currentSpread },
    { label: "回测成功标的", current: `${current.backtest_success_target_count ?? "--"}`, history: history ? `${history.backtest_success_target_count ?? "--"}` : "--", delta: history ? `${(current.backtest_success_target_count ?? 0) - (history.backtest_success_target_count ?? 0)}` : "--", deltaValue: history ? (current.backtest_success_target_count ?? 0) - (history.backtest_success_target_count ?? 0) : null, currentValue: null },
    { label: "回测失败标的", current: `${current.backtest_failed_count ?? "--"}`, history: history ? `${history.backtest_failed_count ?? "--"}` : "--", delta: history ? `${(current.backtest_failed_count ?? 0) - (history.backtest_failed_count ?? 0)}` : "--", deltaValue: history ? (current.backtest_failed_count ?? 0) - (history.backtest_failed_count ?? 0) : null, currentValue: null },
    { label: "使用策略", current: resolveStrategyLabel(current.strategy_name), history: history ? resolveStrategyLabel(history.strategy_name) : "--", delta: "--" },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal full-backtest-compare-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>全量回测结果对比</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <select
              className="pretty-select"
              style={{ minWidth: 260 }}
              value={selectedHistoryId ?? ""}
              onChange={(e) => onSelectHistory(Number(e.target.value))}
            >
              {historyOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.created_at} | {formatPct(item.cumulative_return)} | {item.success_count}/{item.target_count}
                </option>
              ))}
            </select>
            <button className="modal-close-btn" onClick={onClose}>关闭</button>
          </div>
        </div>

        <div className="trade-table-wrap" style={{ maxHeight: "70vh" }}>
          <table className="trade-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>本次全量回测</th>
                <th>历史全量回测</th>
                <th>变化</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td style={{ color: typeof row.currentValue === "number" ? getReturnColor(row.currentValue) : undefined }}>
                    {row.current}
                  </td>
                  <td style={{ color: typeof row.historyValue === "number" ? getReturnColor(row.historyValue) : undefined }}>
                    {row.history}
                  </td>
                  <td style={{ color: typeof row.deltaValue === "number" ? getReturnColor(row.deltaValue) : undefined }}>
                    {row.delta}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MetricDetailModal({
  title,
  detail,
  onInspect,
  onClose,
}: {
  title: string;
  detail: BatchExtremeDetail;
  onInspect: (detail: BatchExtremeDetail, focusTrade?: TradeRecordItem) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal full-backtest-compare-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>{title}</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button className="toggle-btn" onClick={() => onInspect(detail)}>
              查看主图
            </button>
            <button className="modal-close-btn" onClick={onClose}>关闭</button>
          </div>
        </div>

        <div className="result-grid">
          <div className="result-item">
            <span className="label">对应股票</span>
            <span className="value">{detail.name} ({detail.code})</span>
          </div>
          <div className="result-item">
            <span className="label">回测周期</span>
            <span className="value" title={`${detail.range_start} - ${detail.range_end}`}>
              {`${detail.range_start} - ${detail.range_end}`}
            </span>
          </div>
          <div className="result-item">
            <span className="label">总收益率</span>
            <span className="value" style={{ color: getReturnColor(detail.total_return) }}>{formatPct(detail.total_return)}</span>
          </div>
          <div className="result-item">
            <span className="label">最大回撤</span>
            <span className="value">{formatPct(detail.max_drawdown)}</span>
          </div>
          <div className="result-item">
            <span className="label">完整交易</span>
            <span className="value">{detail.round_trip_trades}</span>
          </div>
          <div className="result-item">
            <span className="label">胜率</span>
            <span className="value">{formatRatioPct(detail.win_rate)}</span>
          </div>
        </div>

        {detail.drawdown_detail && (
          <div className="backtest-detail-note">
            最大回撤区间：{detail.drawdown_detail.peak_date || "--"} ({detail.drawdown_detail.peak_value ?? "--"})
            {" "}→ {detail.drawdown_detail.trough_date || "--"} ({detail.drawdown_detail.trough_value ?? "--"})
          </div>
        )}

        {(detail.best_trade || detail.worst_trade) && (
          <div className="backtest-detail-note">
            {detail.best_trade?.pnl_pct != null && `最佳单笔 ${formatPct(detail.best_trade.pnl_pct)} `}
            {detail.worst_trade?.pnl_pct != null && `最差单笔 ${formatPct(detail.worst_trade.pnl_pct)}`}
          </div>
        )}

        {detail.trade_records.length > 0 ? (
          <div className="trade-table-wrap" style={{ maxHeight: "56vh" }}>
            <table className="trade-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>方向</th>
                  <th>质量</th>
                  <th>价格</th>
                  <th>数量</th>
                  <th>收益率</th>
                  <th>收益金额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {detail.trade_records.map((trade, index) => (
                  <tr key={`${trade.direction}-${trade.timestamp ?? trade.signal_timestamp ?? index}`}>
                    <td>{formatTradeDate(trade.date)}</td>
                    <td style={{ color: trade.direction === "buy" ? "var(--accent-red)" : "var(--accent-green)", fontWeight: 700 }}>
                      {trade.direction === "buy" ? "买" : "卖"}
                    </td>
                    <td title={trade.quality?.summary || undefined}>
                      {trade.direction === "buy" && trade.quality?.score != null ? (
                        <span style={{ fontWeight: 700, color: qualityBadgeColor(trade.quality.score) }}>
                          {trade.quality.score}·{trade.quality.grade || "?"}
                        </span>
                      ) : (
                        "--"
                      )}
                    </td>
                    <td>{trade.price.toFixed(getTradePriceDigits(detail.period))}</td>
                    <td>{trade.size}</td>
                    <td style={{ color: getReturnColor(trade.pnl_pct) }}>
                      {trade.pnl_pct != null ? formatPct(trade.pnl_pct) : "--"}
                    </td>
                    <td style={{ color: getReturnColor(trade.pnl) }}>
                      {trade.pnl != null ? `${trade.pnl > 0 ? "+" : ""}${trade.pnl.toFixed(2)}` : "--"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="toggle-btn"
                        onClick={() => onInspect(detail, trade)}
                      >
                        跳主图
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">该股票在当前区间内没有可展示的交易记录。</div>
        )}
      </div>
    </div>
  );
}

function BucketDetailModal({
  title,
  cumulativeReturn,
  items,
  bucketType,
  note,
  loadingCode,
  onInspectStock,
  onClose,
}: {
  title: string;
  cumulativeReturn?: number | null;
  items: BatchBucketItem[];
  bucketType: "profit" | "loss";
  note?: string;
  loadingCode?: string | null;
  onInspectStock: (item: BatchBucketItem) => void;
  onClose: () => void;
}) {
  const overview = buildBucketOverview(items, bucketType);
  const summaryColor = bucketType === "profit" ? "var(--accent-red)" : "var(--accent-green)";
  const summaryBg = bucketType === "profit" ? "rgba(255, 77, 79, 0.08)" : "rgba(82, 196, 26, 0.08)";
  const [sortConfig, setSortConfig] = useState<{
    key: "total_profit" | "total_return" | "max_drawdown" | "round_trip_trades" | "trade_mix" | null;
    direction: "asc" | "desc";
  }>({
    key: null,
    direction: "desc",
  });
  const [activeSegmentLabel, setActiveSegmentLabel] = useState<string | null>(null);
  const activeSegment = overview?.distributionSegments.find((item) => item.label === activeSegmentLabel) || null;
  const filteredItems = useMemo(() => {
    if (!activeSegment) return items;
    return items.filter((item) => {
      const value = Math.abs(item.total_return);
      if (activeSegment.isLast) {
        return value >= activeSegment.start && value <= activeSegment.end;
      }
      return value >= activeSegment.start && value < activeSegment.end;
    });
  }, [activeSegment, items]);

  useEffect(() => {
    if (activeSegmentLabel && !overview?.distributionSegments.some((item) => item.label === activeSegmentLabel)) {
      setActiveSegmentLabel(null);
    }
  }, [activeSegmentLabel, overview]);

  const sortedItems = useMemo(() => {
    if (!sortConfig.key) return filteredItems;
    const sorted = [...filteredItems];
    sorted.sort((a, b) => {
      let compareValue = 0;
      switch (sortConfig.key) {
        case "total_profit":
          compareValue = a.total_profit - b.total_profit;
          break;
        case "total_return":
          compareValue = a.total_return - b.total_return;
          break;
        case "max_drawdown":
          compareValue = a.max_drawdown - b.max_drawdown;
          break;
        case "round_trip_trades":
          compareValue = a.round_trip_trades - b.round_trip_trades;
          break;
        case "trade_mix": {
          const aTotal = a.won_trades + a.lost_trades;
          const bTotal = b.won_trades + b.lost_trades;
          const aWinRate = aTotal > 0 ? a.won_trades / aTotal : 0;
          const bWinRate = bTotal > 0 ? b.won_trades / bTotal : 0;
          compareValue = aWinRate - bWinRate;
          if (compareValue === 0) {
            compareValue = aTotal - bTotal;
          }
          break;
        }
        default:
          compareValue = 0;
      }

      if (compareValue === 0) {
        compareValue = a.code.localeCompare(b.code, "zh-CN");
      }
      return sortConfig.direction === "asc" ? compareValue : -compareValue;
    });
    return sorted;
  }, [filteredItems, sortConfig]);

  const toggleSort = useCallback(
    (key: NonNullable<typeof sortConfig.key>) => {
      setSortConfig((current) => {
        if (current.key === key) {
          return {
            key,
            direction: current.direction === "desc" ? "asc" : "desc",
          };
        }
        return {
          key,
          direction: "desc",
        };
      });
    },
    [],
  );

  const renderSortHeader = useCallback(
    (label: string, key: NonNullable<typeof sortConfig.key>) => {
      const isActive = sortConfig.key === key;
      const arrow = !isActive ? "↕" : sortConfig.direction === "desc" ? "↓" : "↑";
      return (
        <button
          type="button"
          className={`trade-table-sort-btn ${isActive ? "active" : ""}`}
          onClick={() => toggleSort(key)}
          title={`按${label}排序`}
        >
          <span>{label}</span>
          <span>{arrow}</span>
        </button>
      );
    },
    [sortConfig, toggleSort],
  );
  const toggleSegmentFilter = useCallback((label: string) => {
    setActiveSegmentLabel((current) => (current === label ? null : label));
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal full-backtest-compare-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>{title}</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="panel-card-meta">收益率合计 {formatPct(cumulativeReturn ?? null)}</span>
            <button className="modal-close-btn" onClick={onClose}>关闭</button>
          </div>
        </div>

        <div className="backtest-detail-note">
          仅统计已完成交易，不包含未平仓浮盈浮亏。
          {note ? ` ${note}` : ""}
        </div>

        {overview && (
          <>
            <div className="result-grid" style={{ marginTop: 12 }}>
              <div className="result-item">
                <span className="label">股票平均收益率</span>
                <span className="value" style={{ color: getReturnColor(overview.averageStockReturn) }}>
                  {formatPct(overview.averageStockReturn)}
                </span>
                <span className="panel-card-meta">共 {overview.stockCount} 只股票</span>
              </div>
              <div className="result-item">
                <span className="label">完整操作平均收益率</span>
                <span className="value" style={{ color: getReturnColor(overview.averageTradeReturn) }}>
                  {formatPct(overview.averageTradeReturn)}
                </span>
                <span className="panel-card-meta">共 {overview.totalTrades} 次完整交易</span>
              </div>
              <div className="result-item">
                <span className="label">交易股票数量</span>
                <span className="value">{overview.stockCount}</span>
                <span className="panel-card-meta">当前分组内已完成交易股票数</span>
              </div>
            </div>
            <div className="backtest-detail-note" style={{ marginTop: 10 }}>
              {`分布中心：${overview.modeLabel} 共 ${overview.modeCount} 只股票。全区间按 Jenks 自然断点自动切成 ${overview.classCount} 组，${overview.breaksHint}`}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8, marginBottom: 12 }}>
              {overview.distributionSegments.length > 0 ? (
                overview.distributionSegments.map((item) => (
                  <button
                    type="button"
                    key={`${bucketType}-${item.label}`}
                    className={`distribution-chip ${item.emphasis ? "emphasis" : ""} ${activeSegmentLabel === item.label ? "active" : ""}`}
                    style={{
                      background: activeSegmentLabel === item.label ? summaryColor : summaryBg,
                      color: activeSegmentLabel === item.label ? "#fff" : summaryColor,
                      borderColor: summaryColor,
                    }}
                    onClick={() => toggleSegmentFilter(item.label)}
                    title={activeSegmentLabel === item.label ? "再次点击取消筛选" : `点击筛选 ${item.label}`}
                  >
                    {`${item.emphasis ? "🌟 " : ""}${item.label} ${item.count} 只`}
                  </button>
                ))
              ) : (
                <span className="panel-card-meta">
                  当前暂无可展示的区间分布统计
                </span>
              )}
            </div>
          </>
        )}

        {items.length > 0 ? (
          <div className="trade-table-wrap" style={{ maxHeight: "60vh" }}>
            <div className="backtest-detail-note" style={{ marginBottom: 8 }}>
              {activeSegment
                ? `当前已筛选：${activeSegment.label}，命中 ${filteredItems.length} 只股票。再次点击上方同一区间可取消筛选。`
                : `当前展示全部 ${items.length} 只股票。点击上方区间块可按收益率区间筛选。`}
            </div>
            <table className="trade-table">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>名称</th>
                  <th>{renderSortHeader("收益金额", "total_profit")}</th>
                  <th>{renderSortHeader("收益率", "total_return")}</th>
                  <th>区间涨跌幅</th>
                  <th>相对不操作</th>
                  <th>{renderSortHeader("最大回撤", "max_drawdown")}</th>
                  <th>{renderSortHeader("本组完整交易", "round_trip_trades")}</th>
                  <th>{renderSortHeader("完整交易构成", "trade_mix")}</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item) => (
                  <tr key={`${item.code}-${item.name}`}>
                    <td>
                      <button type="button" className="trade-date-btn" onClick={() => onInspectStock(item)}>
                        {item.code}
                      </button>
                    </td>
                    <td>
                      <button type="button" className="trade-date-btn" onClick={() => onInspectStock(item)}>
                        {item.name}
                      </button>
                    </td>
                    <td style={{ color: getReturnColor(item.total_profit), fontWeight: 600 }}>
                      {formatProfitAmount(item.total_profit)}
                    </td>
                    <td style={{ color: getReturnColor(item.total_return), fontWeight: 600 }}>
                      {formatPct(item.total_return)}
                    </td>
                    <td style={{ color: getReturnColor(item.stock_change_pct ?? 0), fontWeight: 600 }}>
                      {formatPct(item.stock_change_pct ?? 0)}
                    </td>
                    <td style={{ color: getReturnColor(item.vs_hold_return ?? 0), fontWeight: 600 }}>
                      {formatPct(item.vs_hold_return ?? 0)}
                    </td>
                    <td>{formatPct(item.max_drawdown)}</td>
                    <td>{item.round_trip_trades}</td>
                    <td>{`${item.won_trades}/${item.lost_trades}`}</td>
                    <td>
                      <button
                        type="button"
                        className="toggle-btn"
                        onClick={() => onInspectStock(item)}
                        disabled={loadingCode === item.code}
                      >
                        {loadingCode === item.code ? "加载中..." : "跳主图"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">当前这条全量回测结果还没有逐股明细，请重新运行一次全量回测后查看。</div>
        )}
      </div>
    </div>
  );
}

function RoundTripSpreadModal({
  summary,
  onClose,
}: {
  summary: FullBacktestSummary;
  onClose: () => void;
}) {
  const profitableAvg = getProfitableAverageReturn(summary);
  const lossAvg = getLossAverageReturn(summary);
  const roundTripSpread = getRoundTripReturnSpread(summary);
  const totalRoundTripTrades = summary.total_round_trip_trades ?? (summary.success_count + summary.failed_count);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>单笔平均收益率说明</h3>
          <button className="modal-close-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="result-grid">
          <div className="result-item">
            <span className="label">盈利股票均值</span>
            <span className="value" style={{ color: "var(--accent-red)" }}>{formatPct(profitableAvg)}</span>
          </div>
          <div className="result-item">
            <span className="label">亏损股票均值</span>
            <span className="value" style={{ color: "var(--accent-green)" }}>{formatPct(lossAvg)}</span>
          </div>
          <div className="result-item">
            <span className="label">单笔平均收益率</span>
            <span className="value" style={{ color: getReturnColor(roundTripSpread) }}>{formatPct(roundTripSpread)}</span>
          </div>
          <div className="result-item">
            <span className="label">总完整交易</span>
            <span className="value">{totalRoundTripTrades}</span>
          </div>
          <div className="result-item">
            <span className="label">盈利股票数</span>
            <span className="value" style={{ color: "var(--accent-red)" }}>{summary.success_count}</span>
          </div>
          <div className="result-item">
            <span className="label">亏损股票数</span>
            <span className="value" style={{ color: "var(--accent-green)" }}>{summary.failed_count}</span>
          </div>
        </div>
        <div className="backtest-detail-note">
          计算方式：盈利股票平均总收益率 - 亏损股票平均总收益率。
        </div>
        <div className="backtest-detail-note">
          可粗略理解为：每完成一笔完整交易，平均能赚多少收益率。比如这个值是 10%，总共完成 100 笔交易，可以近似理解为累计贡献了 1000% 的收益率。
        </div>
        <div className="backtest-detail-note">
          {`${getRoundTripSpreadSubtitle(summary)}，更适合看单笔交易质量，不直接等同于严格复利口径下的最终累计收益率。`}
        </div>
      </div>
    </div>
  );
}

export default function BacktestPanel({
  code,
  name,
  selectedPeriod,
  onRunComplete,
  onClearSignals,
  onSelectTrade,
  onInspectBatchDetail,
  selectedTrade,
  authUser,
  defaultStrategy = "MACD_Cross",
  onRequireLogin,
}: Props) {
  const initialPeriod = normalizeBacktestPeriod(selectedPeriod);
  const [strategy, setStrategy] = useState(defaultStrategy);
  const [runMode, setRunMode] = useState<"single" | "full" | "biaoli">("single");
  const [biaoliGroup, setBiaoliGroup] = useState<BiaoliGroupKey>("long");
  const [biaoliResult, setBiaoliResult] = useState<BiaoliResult | null>(null);
  const [biaoliError, setBiaoliError] = useState<string | null>(null);
  const [biaoliLoading, setBiaoliLoading] = useState(false);
  const [startDate, setStartDate] = useState(() => getSuggestedRange(initialPeriod).startDate);
  const [endDate, setEndDate] = useState(() => getSuggestedRange(initialPeriod).endDate);
  const [cash, setCash] = useState("100000");
  const [period, setPeriod] = useState(initialPeriod);
  const [minQualityScore, setMinQualityScore] = useState("0");
  const [quickRangePreset, setQuickRangePreset] = useState<QuickRangePreset>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<BacktestRuntimeStatus | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [fullHistory, setFullHistory] = useState<FullBacktestHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [batchDetailLoading, setBatchDetailLoading] = useState(false);
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [compareBaseDetail, setCompareBaseDetail] = useState<FullBacktestHistoryItem | null>(null);
  const [compareRunId, setCompareRunId] = useState<number | null>(null);
  const [compareRunDetail, setCompareRunDetail] = useState<FullBacktestHistoryItem | null>(null);
  const [currentBatchDetail, setCurrentBatchDetail] = useState<FullBacktestHistoryItem | null>(null);
  const [metricModal, setMetricModal] = useState<{ title: string; detail: BatchExtremeDetail } | null>(null);
  const [bucketModal, setBucketModal] = useState<{ title: string; cumulativeReturn?: number | null; items: BatchBucketItem[]; bucketType: "profit" | "loss"; note?: string } | null>(null);
  const [spreadModalOpen, setSpreadModalOpen] = useState(false);
  const [bucketInspectCode, setBucketInspectCode] = useState<string | null>(null);
  const [scannableCount, setScannableCount] = useState<number | null>(null);
  const skipRunModeResetRef = useRef(false);
  const activeBacktestJobIdRef = useRef("");
  const notifiedBacktestJobIdRef = useRef("");
  const historyLongPressTimerRef = useRef<number | null>(null);
  const [longPressHistoryId, setLongPressHistoryId] = useState<number | null>(null);
  const [deletingHistoryId, setDeletingHistoryId] = useState<number | null>(null);
  const totalCommission = (result?.trade_records || []).reduce((sum, item) => sum + (item.commission || 0), 0);
  const batchSummary = result?.batch_summary || null;
  const compareBaseSummary = resolveHistorySummary(compareBaseDetail);
  const compareSummary = resolveHistorySummary(compareRunDetail);
  const batchPayload = currentBatchDetail?.payload;
  const filteredCompareOptions = useMemo(
    () => fullHistory.filter((item) => item.id !== compareBaseDetail?.id),
    [fullHistory, compareBaseDetail?.id]
  );
  const strategyLabelResolver = (strategyName: string) => getStrategyLabel(strategyName, strategies);
  const shortStrategyLabelResolver = (strategyName: string) => getShortStrategyLabel(strategyName, strategies);
  const notifyBacktestCompleted = (completed: BacktestResult) => {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const isBatch = completed.mode === "batch";
    const summary = completed.batch_summary;
    const title = isBatch ? "✅ 全量回测完成" : `✅ ${name || code} 回测完成`;
    const body = isBatch
      ? `策略：${strategyLabelResolver(completed.strategy_name || strategy)}｜成功 ${summary?.success_count ?? 0}/${summary?.target_count ?? 0}`
      : `策略：${strategyLabelResolver(completed.strategy_name || strategy)}｜收益 ${completed.total_return == null ? "--" : `${completed.total_return >= 0 ? "+" : ""}${completed.total_return.toFixed(2)}%`}`;
    try {
      const notification = new Notification(title, { body, tag: `backtest-${activeBacktestJobIdRef.current}` });
      notification.onclick = () => { window.focus(); notification.close(); };
    } catch {
      // Browser notification failures should not affect the completed result.
    }
  };

  const mergeFullHistoryItem = useCallback((item: FullBacktestHistoryItem) => {
    setFullHistory((prev) => [item, ...prev.filter((historyItem) => historyItem.id !== item.id)]);
  }, []);

  const loadFullHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetchFullBacktestHistory({ limit: 30 });
      if (res.success && res.data) {
        setFullHistory(res.data);
        return res.data;
      }
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const hydrateBatchResultById = useCallback(async (runId: number) => {
    setBatchDetailLoading(true);
    try {
      const detailRes = await fetchFullBacktestHistoryDetail(runId);
      if (detailRes.success && detailRes.data) {
        mergeFullHistoryItem(detailRes.data);
        setCurrentBatchDetail(detailRes.data);
        setCompareBaseDetail(detailRes.data);
        setResult(buildBatchResultFromHistory(detailRes.data));
        return detailRes.data;
      }
      const items = await loadFullHistory();
      const matched = items.find((item) => item.id === runId);
      if (matched) {
        setCurrentBatchDetail(matched);
        setCompareBaseDetail(matched);
        setResult(buildBatchResultFromHistory(matched));
        return matched;
      }
      return null;
    } finally {
      setBatchDetailLoading(false);
    }
  }, [loadFullHistory, mergeFullHistoryItem]);

  const hydrateLatestBatchResult = useCallback(async () => {
    const items = await loadFullHistory();
    if (items.length === 0) return;
    const latest = items[0];
    if (latest.id) {
      await hydrateBatchResultById(latest.id);
    } else {
      setCurrentBatchDetail(latest);
      setCompareBaseDetail(latest);
      setResult(buildBatchResultFromHistory(latest));
    }
    skipRunModeResetRef.current = true;
    setRunMode("full");
  }, [hydrateBatchResultById, loadFullHistory]);

  const applyRemoteBacktestStatus = (status: BacktestRuntimeStatus) => {
    setRuntimeStatus(status);
    if (status.mode === "full") {
      setRunMode("full");
    } else if (status.mode === "single") {
      setRunMode("single");
    }

    if (status.running) {
      setLoading(true);
      return;
    }

    setLoading(false);
    if (status.result) {
      setResult(status.result);
      if (status.result.mode === "batch") {
        if (status.result.batch_run_id) {
          hydrateBatchResultById(status.result.batch_run_id);
        } else {
          loadFullHistory();
          setCompareBaseDetail(null);
        }
        skipRunModeResetRef.current = true;
        setRunMode("full");
      }
      if (status.result.success && onRunComplete) {
        onRunComplete(status.result);
      }
      if (
        status.result.success
        && status.job_id
        && status.job_id === activeBacktestJobIdRef.current
        && status.job_id !== notifiedBacktestJobIdRef.current
      ) {
        notifiedBacktestJobIdRef.current = status.job_id;
        notifyBacktestCompleted(status.result);
      }
    } else if (!status.running && !status.error) {
      if (runMode === "full") {
        hydrateLatestBatchResult();
      }
    } else if (status.error) {
      setResult({ success: false, message: status.error });
    }
  };

  useEffect(() => {
    fetchStrategies().then((res) => {
      if (res.success && res.data) {
        setStrategies(res.data);
        const defaultOption = res.data.find((s: StrategyInfo) => s.name === defaultStrategy && !s.locked);
        const currentOption = res.data.find((s: StrategyInfo) => s.name === strategy && !s.locked);
        if (defaultOption) {
          setStrategy(defaultOption.name);
        } else if (!currentOption && res.data.length > 0) {
          setStrategy((res.data.find((s: StrategyInfo) => !s.locked) || res.data[0]).name);
        }
      }
    });

    // 从后端恢复回测设置
    fetchBacktestSettings().then((res) => {
      if (res.success && res.data) {
        const s = res.data;
        if (s.strategy) setStrategy(s.strategy);
        if (s.start_date) {
          // 后端格式 YYYYMMDD -> 前端格式 YYYY-MM-DD
          setStartDate(`${s.start_date.slice(0, 4)}-${s.start_date.slice(4, 6)}-${s.start_date.slice(6, 8)}`);
        }
        if (s.end_date) {
          setEndDate(`${s.end_date.slice(0, 4)}-${s.end_date.slice(4, 6)}-${s.end_date.slice(6, 8)}`);
        }
        if (s.cash) setCash(String(s.cash));
        if (s.period) setPeriod(normalizeBacktestPeriod(s.period));
        if (s.mode === "single" || s.mode === "full") setRunMode(s.mode);
        if (typeof s.min_quality_score === "number") setMinQualityScore(String(s.min_quality_score));
      }
    });

    fetchScanStatus().then((res) => {
      if (res.success && res.data) {
        if (typeof res.data.local_ready_count === "number") {
          setScannableCount(res.data.local_ready_count);
        } else if (typeof res.data.scan_universe_count === "number") {
          setScannableCount(res.data.scan_universe_count);
        } else {
          setScannableCount(null);
        }
      }
    });
  }, [authUser?.username, defaultStrategy]);

  useEffect(() => {
    if (runMode === "full" || result?.mode === "batch") {
      loadFullHistory();
    }
  }, [runMode, strategy, result?.mode, loadFullHistory]);
  useEffect(() => {
    if (runMode !== "full") return;
    if (loading || runtimeStatus?.running) return;
    if (result?.mode === "batch" && result.batch_run_id) return;
    hydrateLatestBatchResult();
  }, [runMode, loading, runtimeStatus?.running, result?.mode, result?.batch_run_id, code, period, hydrateLatestBatchResult]);
  useEffect(() => {
    const handleDocMouseDown = (e: MouseEvent) => {
      if (longPressHistoryId) {
        const target = e.target as HTMLElement;
        if (!target.closest(".history-delete-popup")) {
          setLongPressHistoryId(null);
        }
      }
    };
    document.addEventListener("mousedown", handleDocMouseDown);
    return () => document.removeEventListener("mousedown", handleDocMouseDown);
  }, [longPressHistoryId]);

  useEffect(() => {
    setPeriod(normalizeBacktestPeriod(selectedPeriod));
  }, [code, selectedPeriod]);

  useEffect(() => {
    const suggested = getSuggestedRange(period);
    setStartDate(suggested.startDate);
    setEndDate(suggested.endDate);
    setQuickRangePreset(null);
    if (runMode !== "full") {
      setResult(null);
    }
  }, [code, period, runMode]);

  useEffect(() => {
    if (skipRunModeResetRef.current) {
      skipRunModeResetRef.current = false;
      return;
    }
    setResult(null);
    setRuntimeStatus(null);
    setCompareBaseDetail(null);
    setCompareRunId(null);
    setCompareRunDetail(null);
    setCurrentBatchDetail(null);
    setMetricModal(null);
    if (runMode === "full") {
      onClearSignals?.();
    }
  }, [runMode]);

  useEffect(() => {
    fetchBacktestStatus().then((res) => {
      if (!res.success) return;
      applyRemoteBacktestStatus(res.data);
    });
  }, []);

  useEffect(() => {
    if (!loading && !runtimeStatus?.running) return;
    const timer = window.setInterval(async () => {
      const res = await fetchBacktestStatus();
      if (!res.success) return;
      applyRemoteBacktestStatus(res.data);
    }, 900);

    return () => {
      window.clearInterval(timer);
    };
  }, [loading, runtimeStatus?.running, onRunComplete]);

  const applyQuickRange = (preset: Exclude<QuickRangePreset, null>) => {
    const range = getQuickRange(preset);
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    setQuickRangePreset(preset);
    setResult(null);
  };

  // 表里状态：取当前股票三个级别的K线，算出 (X,Y) 状态与综合判定
  const runBiaoli = async () => {
    setBiaoliLoading(true);
    setBiaoliResult(null);
    setBiaoliError(null);
    try {
      const periods = BIAOLI_GROUPS[biaoliGroup].periods;
      const klinesByPeriod: Record<string, KlineData[]> = {};
      await Promise.all(
        periods.map(async (p) => {
          try {
            const res = await fetchKline(code, name, p, 300);
            klinesByPeriod[p] = res && res.success && res.data ? res.data : [];
          } catch {
            klinesByPeriod[p] = [];
          }
        })
      );
      const r = buildBiaoliResult(biaoliGroup, klinesByPeriod);
      setBiaoliResult(r);
      const tooFew = r.levels.find((l) => l.klineCount < 10);
      if (tooFew) {
        setBiaoliError(`${tooFew.level} K线数据不足（仅 ${tooFew.klineCount} 根），该级别结果可能不准`);
      }
    } catch (e: any) {
      setBiaoliResult(null);
      setBiaoliError("获取表里状态失败：" + (e?.message || "未知错误"));
    } finally {
      setBiaoliLoading(false);
    }
  };

  const handleRun = async () => {
    if (!authUser) {
      onRequireLogin?.("请先登录后再运行回测");
      return;
    }
    if (runMode === "biaoli") {
      await runBiaoli();
      return;
    }
    if ((authUser.role || "").toLowerCase() === "trial") {
      onRequireLogin?.("临时账号不能运行回测，请先开通 VIP 后再操作");
      return;
    }
    const strategyInfo = strategies.find((item) => item.name === strategy);
    if (strategyInfo?.locked) {
      onRequireLogin?.(strategyInfo.lock_message || "请先登录后使用该策略");
      return;
    }

    if (!startDate || !endDate) {
      setResult({ success: false, message: "请选择完整的回测起止日期" });
      return;
    }

    if (startDate > endDate) {
      setResult({ success: false, message: "开始日期不能晚于结束日期" });
      return;
    }

    if (!cash || Number(cash) <= 0) {
      setResult({ success: false, message: "请输入大于 0 的起始资金" });
      return;
    }

    await requestBacktestNotificationPermission();
    activeBacktestJobIdRef.current = "";
    setLoading(true);
    setResult(null);
    setRuntimeStatus({
      job_id: "",
      running: true,
      mode: runMode === "full" ? "full" : "single",
      progress_pct: 0,
      current_step: "排队中",
      message: "正在创建回测任务...",
      total_targets: 0,
      completed_targets: 0,
      success_targets: 0,
      failed_targets: 0,
      current_target_index: 0,
      current_target_code: "",
      current_target_name: "",
    });
    if (onClearSignals) {
      onClearSignals();
    }
    try {
      const formatApiDate = (d: string) => d.replace(/-/g, "");
      const res = await startBacktest({
        code,
        name,
        strategy,
        start_date: formatApiDate(startDate),
        end_date: endDate ? formatApiDate(endDate) : "",
        cash: parseFloat(cash),
        period,
        mode: runMode === "full" ? "full" : "single",
        min_quality_score: Number(minQualityScore) || 0,
      });
      if (!res.success) {
        const message = (res as any).message || res.message || "回测请求失败";
        if ((res as any).status === 401 || (res as any).status === 403 || /登录|临时账号/.test(message)) {
          onRequireLogin?.(message);
        }
        if (res.data) {
          applyRemoteBacktestStatus(res.data);
          setResult({ success: false, message });
        } else {
          setResult({ success: false, message });
          setRuntimeStatus(null);
          setLoading(false);
        }
        return;
      }
      if (res.data) {
        activeBacktestJobIdRef.current = res.data.job_id || "";
        applyRemoteBacktestStatus(res.data);
      }
    } catch (e: any) {
      setResult({ success: false, message: e.message || "回测请求失败" });
      setRuntimeStatus(null);
      setLoading(false);
    }
  };

  const handleClear = () => {
    setResult(null);
    setRuntimeStatus(null);
    setCompareBaseDetail(null);
    setBiaoliResult(null);
    setBiaoliError(null);
    if (onClearSignals) {
      onClearSignals();
    }
  };

  const openCompareModal = async (baseRun?: FullBacktestHistoryItem | null) => {
    const latestDetail = currentBatchDetail || fullHistory[0] || null;
    if (!latestDetail) return;
    setCompareBaseDetail(latestDetail);
    const targetId = baseRun?.id || fullHistory.find((item) => item.id !== latestDetail.id)?.id;
    if (!targetId) {
      setShowCompareModal(true);
      setCompareRunId(null);
      setCompareRunDetail(null);
      return;
    }
    setCompareRunId(targetId);
    setShowCompareModal(true);
    const res = await fetchFullBacktestHistoryDetail(targetId);
    if (res.success && res.data) {
      setCompareRunDetail(res.data);
    }
  };

  useEffect(() => {
    if (!showCompareModal || !compareRunId) return;
    fetchFullBacktestHistoryDetail(compareRunId).then((res) => {
      if (res.success && res.data) {
        setCompareRunDetail(res.data);
      }
    });
  }, [showCompareModal, compareRunId]);

  useEffect(() => {
    if (result?.mode !== "batch" || !result.batch_run_id) {
      setCurrentBatchDetail(null);
      return;
    }
    fetchFullBacktestHistoryDetail(result.batch_run_id).then((res) => {
      if (res.success && res.data) {
        setCurrentBatchDetail(res.data);
        setCompareBaseDetail(res.data);
      }
    });
  }, [result?.mode, result?.batch_run_id]);

  const openMetricDetail = (type: "drawdown" | "gain") => {
    const detail = type === "drawdown" ? batchPayload?.max_drawdown_detail : batchPayload?.max_gain_detail;
    if (!detail) return;
    setMetricModal({
      title: type === "drawdown" ? "最大回撤明细" : "最大涨幅明细",
      detail,
    });
  };

  const openBucketDetail = (type: "profit" | "loss") => {
    const items = type === "profit" ? (batchPayload?.profitable_items || batchSummary?.profitable_items || []) : (batchPayload?.loss_items || batchSummary?.loss_items || []);
    const cumulativeReturn = type === "profit"
      ? (batchSummary?.profitable_cumulative_return ?? null)
      : (batchSummary?.loss_cumulative_return ?? null);
    setBucketModal({
      title: type === "profit" ? "盈利股票明细" : "亏损股票明细",
      cumulativeReturn,
      items,
      bucketType: type,
      note: items.length > 0 ? undefined : "当前展示的是较早生成的全量回测结果，尚未保存逐股盈亏明细。",
    });
  };

  const inspectMetricDetail = (detail: BatchExtremeDetail, focusTrade?: TradeRecordItem) => {
    onInspectBatchDetail?.(detail, focusTrade);
    setMetricModal(null);
  };

  const inspectBucketStock = async (item: BatchBucketItem) => {
    const runId = currentBatchDetail?.id || result?.batch_run_id;
    if (!runId) return;
    setBucketInspectCode(item.code);
    try {
      const res = await fetchFullBacktestStockDetail(runId, item.code);
      if (!res.success || !res.data) {
        alert(res.message || "加载个股回测详情失败");
        return;
      }
      onInspectBatchDetail?.(res.data);
      setBucketModal(null);
    } finally {
      setBucketInspectCode(null);
    }
  };

  const handleActivateBatchHistory = (item: FullBacktestHistoryItem) => {
    setLongPressHistoryId(null);
    setCurrentBatchDetail(item);
    setCompareBaseDetail(item);
    setResult(buildBatchResultFromHistory(item));
    skipRunModeResetRef.current = true;
    setRunMode("full");
  };

  const renderBatchHistorySection = () => (
    <div className="trade-records">
      <div className="panel-card-header" style={{ marginBottom: 8 }}>
        <h4 style={{ margin: 0 }}>历史全量回测结果 {fullHistory.length} 条</h4>
        <div style={{ display: "flex", gap: 8 }}>
          {currentBatchDetail && (
            <button type="button" className="toggle-btn" onClick={() => openCompareModal()}>
              一键对比
            </button>
          )}
          <button type="button" className="toggle-btn" onClick={() => loadFullHistory()}>
            刷新
          </button>
        </div>
      </div>
      {historyLoading ? (
        <div className="backtest-inline-loading">
          <span className="backtest-spinner" aria-hidden="true" />
          <span>正在加载历史全量回测结果...</span>
        </div>
      ) : fullHistory.length === 0 ? (
        <div className="empty">暂无全量回测历史结果。</div>
      ) : (
        <div className="trade-table-wrap">
          <table className="trade-table">
            <thead>
              <tr>
                <th>策略</th>
                <th>累计收益率</th>
                <th>平均收益率</th>
                <th>最大回撤</th>
                <th>最大涨幅</th>
                <th>交易股票数</th>
                <th>盈利股票/亏损股票</th>
                <th>单笔平均收益率</th>
                <th>操作</th>
                <th>时间</th>
                <th>回测周期</th>
              </tr>
            </thead>
            <tbody>
              {fullHistory.map((item) => {
                const summary = resolveHistorySummary(item);
                if (!summary) return null;
                const tradedTargetCount = summary.traded_target_count ?? (summary.profitable_count + summary.loss_count);
                return (
                  <tr key={item.id}>
                    <td
                      style={{ position: "relative" }}
                      onPointerDown={() => {
                        if (historyLongPressTimerRef.current) {
                          window.clearTimeout(historyLongPressTimerRef.current);
                          historyLongPressTimerRef.current = null;
                        }
                        historyLongPressTimerRef.current = window.setTimeout(() => {
                          historyLongPressTimerRef.current = null;
                          setLongPressHistoryId(item.id);
                        }, 600);
                      }}
                      onPointerUp={() => {
                        if (historyLongPressTimerRef.current) {
                          window.clearTimeout(historyLongPressTimerRef.current);
                          historyLongPressTimerRef.current = null;
                        }
                      }}
                      onPointerLeave={() => {
                        if (historyLongPressTimerRef.current) {
                          window.clearTimeout(historyLongPressTimerRef.current);
                          historyLongPressTimerRef.current = null;
                        }
                      }}
                      onContextMenu={(e) => e.preventDefault()}
                      onDoubleClick={() => handleActivateBatchHistory(item)}
                      title="双击策略加载这条回测结果，长按策略可删除"
                    >
                      <span
                        className="table-text-ellipsis strategy-name-copy"
                        title={`${strategyLabelResolver(summary.strategy_name)}（单击复制名称，双击切换结果）`}
                        onClick={(e) => {
                          e.stopPropagation();
                          const fullName = strategyLabelResolver(summary.strategy_name);
                          navigator.clipboard.writeText(fullName).catch(() => {});
                        }}
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          handleActivateBatchHistory(item);
                        }}
                      >
                        {shortStrategyLabelResolver(summary.strategy_name)}
                        {(item.payload?.min_quality_score ?? 0) > 0 && (
                          <span
                            style={{ marginLeft: 6, fontSize: 11, fontWeight: 700, color: qualityBadgeColor(item.payload!.min_quality_score) }}
                            title={`本次全量回测启用了买点质量过滤（≥${item.payload!.min_quality_score}分）`}
                          >
                            ≥{item.payload!.min_quality_score}分
                          </span>
                        )}
                      </span>
                      {longPressHistoryId === item.id && (
                        <button
                          className="history-delete-popup"
                          onPointerDown={(e) => e.stopPropagation()}
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={async (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setDeletingHistoryId(item.id);
                            try {
                              const res = await deleteFullBacktestHistory(item.id);
                              if (!res.success) {
                                if ((res as any).status === 401) {
                                  onRequireLogin?.((res as any).message || "请先登录后再删除回测结果");
                                } else {
                                  alert(res.message || "删除失败");
                                }
                              } else {
                                setLongPressHistoryId(null);
                                await loadFullHistory();
                              }
                            } finally {
                              setDeletingHistoryId(null);
                            }
                          }}
                          disabled={deletingHistoryId === item.id}
                        >
                          删除
                        </button>
                      )}
                    </td>
                    <td style={{ color: getReturnColor(summary.cumulative_return), fontWeight: 600 }}>{formatPct(summary.cumulative_return)}</td>
                    <td style={{ color: getReturnColor(summary.average_return), fontWeight: 600 }}>{formatPct(summary.average_return)}</td>
                    <td>{formatPct(summary.max_drawdown)}</td>
                    <td style={{ color: getReturnColor(summary.max_gain), fontWeight: 600 }}>{formatPct(summary.max_gain)}</td>
                    <td>{`${tradedTargetCount}/${summary.target_count}`}</td>
                    <td>{`${summary.success_count}/${summary.failed_count}`}</td>
                    <td
                      title={getRoundTripSpreadSubtitle(summary)}
                      style={{ color: getReturnColor(getRoundTripReturnSpread(summary)), fontWeight: 600 }}
                    >
                      {formatRoundTripReturnSpread(summary)}
                    </td>
                    <td>
                      <button type="button" className="toggle-btn" onClick={() => openCompareModal(item)}>
                        对比
                      </button>
                    </td>
                    <td title={item.created_at}>{item.created_at}</td>
                    <td>
                      <span className="table-text-ellipsis" title={formatBatchPeriod(summary)}>
                        {formatBatchPeriod(summary)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <div className="backtest-workspace">
      <div className="panel-card backtest-panel">
        <div className="panel-card-header">
          <h3>回测设置</h3>
          <span className="panel-card-meta">
            {name} ({code})
          </span>
        </div>

        <div className="backtest-form">
          {runMode === "biaoli" && (
            <div className="backtest-row">
              <div className="backtest-field">
                <label>级别组合</label>
                <select
                  value={biaoliGroup}
                  onChange={(e) => {
                    setBiaoliGroup(e.target.value as BiaoliGroupKey);
                    setBiaoliResult(null);
                    setBiaoliError(null);
                  }}
                  disabled={biaoliLoading}
                >
                  <option value="long">长线（30分钟 / 日线 / 周线）</option>
                  <option value="short">短线（5分钟 / 30分钟 / 日线）</option>
                </select>
              </div>
              <div className="backtest-field" style={{ flex: 1, minWidth: 260 }}>
                <label>说明</label>
                <span style={{ fontSize: 12, color: "var(--muted-text, #8ba4c7)" }}>
                  按缠论「走势结构的两重表里关系」：每个级别用 (方向, 位置) 编码当前笔状态，多级别连读判断行情阶段。点上方"获取表里状态"按钮即可。
                </span>
              </div>
            </div>
          )}
          {runMode !== "biaoli" && (
            <>
          <div className="backtest-row">
            <div className="backtest-field">
              <label>策略模型</label>
              <select
                value={strategy}
                onChange={(e) => {
                  const next = e.target.value;
                  const selected = strategies.find((item) => item.name === next);
                  if (selected?.locked) {
                    onRequireLogin?.(selected.lock_message || "请先登录后使用该策略");
                    return;
                  }
                  setStrategy(next);
                }}
              >
                {strategies.length > 0 ? (
                  strategies.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.description || s.name}{s.locked ? " · 需登录" : ""}
                    </option>
                  ))
                ) : (
                  <>
                    <option value="MACD_Cross">MACD 金叉死叉策略</option>
                  </>
                )}
              </select>
            </div>
            <div className="backtest-field">
              <label>K线周期</label>
              <select value={period} onChange={(e) => setPeriod(e.target.value)}>
                <option value="weekly">周线</option>
                <option value="monthly">月线</option>
                <option value="1">1分钟</option>
                <option value="5">5分钟</option>
                <option value="15">15分钟</option>
                <option value="30">30分钟</option>
                <option value="60">60分钟</option>
                <option value="120">120分钟</option>
                <option value="daily">日线</option>
              </select>
            </div>
            <div className="backtest-field">
              <label>起始资金</label>
              <input type="number" value={cash} onChange={(e) => setCash(e.target.value)} />
            </div>
          </div>
          <div className="backtest-row">
            <div className="backtest-field">
              <label>开始日期</label>
              <input type="date" value={startDate} onChange={(e) => {
                setStartDate(e.target.value);
                setQuickRangePreset(null);
              }} />
            </div>
            <div className="backtest-field">
              <label>结束日期</label>
              <input type="date" value={endDate} onChange={(e) => {
                setEndDate(e.target.value);
                setQuickRangePreset(null);
              }} />
            </div>
            {strategy === "MACD_NON_DIVERGENCE_PULLBACK" && (
              <div className="backtest-field">
                <label>质量过滤</label>
                <select
                  value={minQualityScore}
                  onChange={(e) => setMinQualityScore(e.target.value)}
                  title="按买点趋势质量评分过滤：同一策略跑两次（不筛 vs 筛）即可对比胜率差异"
                >
                  <option value="0">不过滤（对照）</option>
                  <option value="55">≥55分（滤掉C级）</option>
                  <option value="75">≥75分（仅A级）</option>
                  <option value="85">≥85分（强A）</option>
                </select>
              </div>
            )}
          </div>
          <div className="backtest-row">
            <div className="backtest-field backtest-quick-field">
              <label>快捷区间</label>
              <div className="backtest-quick-actions">
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "1d" ? "active" : ""}`}
                  onClick={() => applyQuickRange("1d")}
                >
                  一天
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "1w" ? "active" : ""}`}
                  onClick={() => applyQuickRange("1w")}
                >
                  一周
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "1m" ? "active" : ""}`}
                  onClick={() => applyQuickRange("1m")}
                >
                  一个月
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "6m" ? "active" : ""}`}
                  onClick={() => applyQuickRange("6m")}
                >
                  半年
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "1y" ? "active" : ""}`}
                  onClick={() => applyQuickRange("1y")}
                >
                  一年
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "2y" ? "active" : ""}`}
                  onClick={() => applyQuickRange("2y")}
                >
                  两年
                </button>
                <span className="backtest-quick-sep" style={{ color: "var(--text-secondary)", margin: "0 4px" }}>｜压力测试</span>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "stress_2015" ? "active" : ""}`}
                  onClick={() => applyQuickRange("stress_2015")}
                  title="2015-06-15 ~ 2015-09-15 杠杆牛市崩盘(需足够历史数据)"
                >
                  2015股灾
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "stress_2018" ? "active" : ""}`}
                  onClick={() => applyQuickRange("stress_2018")}
                  title="2018-06-01 ~ 2018-12-31 中美贸易战"
                >
                  2018贸易战
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "stress_2020" ? "active" : ""}`}
                  onClick={() => applyQuickRange("stress_2020")}
                  title="2020-02-01 ~ 2020-04-30 新冠疫情冲击"
                >
                  2020疫情
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "stress_2024_01" ? "active" : ""}`}
                  onClick={() => applyQuickRange("stress_2024_01")}
                  title="2024-01-01 ~ 2024-03-31 微盘股崩盘"
                >
                  2024微盘
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${quickRangePreset === "stress_2024_09" ? "active" : ""}`}
                  onClick={() => applyQuickRange("stress_2024_09")}
                  title="2024-09-24 ~ 2024-10-08 9·24 政策行情"
                >
                  9·24行情
                </button>
                <span className="backtest-quick-hint">
                  {runMode === "full" ? "全量回测将使用当前可扫描目标池" : "自动取最近交易日为结束日期"}
                </span>
              </div>
            </div>
          </div>
            </>
          )}
          <div className="backtest-row">
            <div className="backtest-field backtest-submit-field">
              <div className="backtest-run-toolbar">
                <div className="backtest-run-toolbar-head">
                  <span className={`backtest-run-mode-pill ${runMode === "full" ? "full" : runMode === "biaoli" ? "biaoli" : "single"}`}>
                    {runMode === "full" ? "批量模式" : runMode === "biaoli" ? "表里状态" : "单标模式"}
                  </span>
                  <span className="backtest-run-toolbar-hint">
                    {runMode === "full"
                      ? "会对当前可扫描目标池并行回测"
                      : runMode === "biaoli"
                      ? "查看当前股票多级别缠论笔的表里状态"
                      : "只回测当前选中的标的"}
                  </span>
                </div>
                <div className="backtest-run-group">
                  <button
                    className="backtest-run-btn"
                    onClick={handleRun}
                    disabled={loading || biaoliLoading}
                  >
                    {runMode === "biaoli"
                      ? biaoliLoading
                        ? "获取中..."
                        : "获取表里状态"
                      : loading
                      ? runMode === "full"
                        ? "全量回测中..."
                        : "回测中..."
                      : runMode === "full"
                      ? `开始全量回测${scannableCount !== null ? ` (${scannableCount} 只股票)` : ""}`
                      : "开始回测"}
                  </button>
                  <div className="backtest-run-select-shell">
                    <span className="backtest-run-select-label">模式</span>
                    <select
                      className="backtest-run-mode-select"
                      value={runMode}
                      onChange={(e) => {
                        const next = e.target.value as "single" | "full" | "biaoli";
                        setRunMode(next);
                        // 切换模式时清空上一模式的结果，避免串显
                        setResult(null);
                        setRuntimeStatus(null);
                        setBiaoliResult(null);
                        setBiaoliError(null);
                      }}
                      disabled={loading || biaoliLoading}
                    >
                      <option value="single">开始回测</option>
                      <option value="full">全量回测</option>
                      <option value="biaoli">获取表里状态</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <div className="panel-card backtest-result-card">
        <div className="panel-card-header">
          <h3>{runMode === "biaoli" ? "表里状态" : "回测结果"}</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {result?.success && (
              <button 
                className="toggle-btn" 
                onClick={handleClear}
                style={{ padding: "2px 8px", fontSize: "11px" }}
              >
                清除
              </button>
            )}
            {result?.success && (
              <span className="panel-card-meta" title={`${result.range_start} - ${result.range_end}`}>
                {result.range_start} - {result.range_end}
              </span>
            )}
            {runMode === "biaoli" && biaoliResult && (
              <button
                className="toggle-btn"
                onClick={handleClear}
                style={{ padding: "2px 8px", fontSize: "11px" }}
              >
                清除
              </button>
            )}
          </div>
        </div>

        {loading && (
          <div className="backtest-progress-card">
            <span className="backtest-spinner backtest-progress-spinner" aria-hidden="true" />
            <div className="backtest-progress-title">回测进行中</div>
            <div className="backtest-progress-step">
              {runtimeStatus?.current_step || "正在准备回测流程"}
            </div>
            <div className="backtest-progress-desc">
              {runtimeStatus?.message || "正在进行回测，请稍等"}
            </div>
            {runtimeStatus?.node_used ? (
              <div className="backtest-progress-node">
                执行节点：
                <span className={`node-used node-used-${runtimeStatus.node_used}`}>
                  {runtimeStatus.node_used === "pi"
                    ? "树莓派节点"
                    : runtimeStatus.node_used === "mixed"
                      ? "节点 + 本机（混合）"
                      : "本机"}
                </span>
              </div>
            ) : null}
            {runtimeStatus?.mode === "full" && (
              <div className="backtest-progress-meta">
                <span>
                  正在回测 {runtimeStatus.current_target_index || runtimeStatus.completed_targets || 0}/{runtimeStatus.total_targets || 0}
                </span>
                <span>
                  成功 {runtimeStatus.success_targets || 0} / 失败 {runtimeStatus.failed_targets || 0}
                </span>
              </div>
            )}
            <div className="backtest-progress-track">
              <div
                className="backtest-progress-fill"
                style={{ width: `${runtimeStatus?.progress_pct || 0}%` }}
              />
            </div>
            <div className="backtest-progress-meta">
              <span>{runtimeStatus?.progress_pct || 0}%</span>
              <span>{runtimeStatus?.updated_at || ""}</span>
            </div>
          </div>
        )}

        {!loading && batchDetailLoading && (
          <div className="backtest-progress-card">
            <span className="backtest-spinner backtest-progress-spinner" aria-hidden="true" />
            <div className="backtest-progress-title">正在加载回测结果</div>
            <div className="backtest-progress-desc">全量回测已完成，正在拉取汇总和历史明细...</div>
          </div>
        )}

        {!loading && !batchDetailLoading && !result && (
          runMode === "biaoli" ? (
            biaoliLoading ? (
              <div className="backtest-progress-card">
                <span className="backtest-spinner backtest-progress-spinner" aria-hidden="true" />
                <div className="backtest-progress-title">正在获取表里状态</div>
                <div className="backtest-progress-desc">拉取多级别K线并计算缠论笔状态...</div>
              </div>
            ) : biaoliResult ? (
              <div className="biaoli-result">
                {biaoliError && <div className="result-error">{biaoliError}</div>}
                <div className="biaoli-summary-card">
                  <div className="biaoli-summary-head">
                    <span className="biaoli-stage">{biaoliResult.stage}</span>
                    <span className="biaoli-concept">缠论概念：{biaoliResult.zenConcept}</span>
                  </div>
                  <div className="biaoli-group-label">{biaoliResult.groupLabel}</div>
                  <div className="biaoli-verdict">{biaoliResult.verdict}</div>
                  <div className="biaoli-stage-desc">{biaoliResult.stageDesc}</div>
                </div>
                <div className="biaoli-level-list">
                  {biaoliResult.levels.map((l) => (
                    <div className="biaoli-level-card" key={l.period}>
                      <div className="biaoli-level-top">
                        <span className="biaoli-level-name">{l.level}</span>
                        <span className="biaoli-kline-count">{l.klineCount} 根K线</span>
                      </div>
                      <div className={`biaoli-level-state ${l.X === 1 ? "up" : "down"}`}>
                        <span className="biaoli-code">{l.code}</span>
                        <span>{l.penLabel}</span>
                      </div>
                      <div className="biaoli-level-hint">{l.hint}</div>
                    </div>
                  ))}
                </div>
                <div className="biaoli-legend">
                  <div>
                    <b>编码：</b>(1,1) 上涨延伸 / (-1,1) 下跌延伸 / (1,0) 顶分型 / (-1,0) 底分型
                  </div>
                  <div>
                    <b>读法：</b>小级别先变是预警；大级别进入 (1,0) 或 (-1,0) 后，要继续看小级别走势类型和中枢震荡。
                  </div>
                </div>
              </div>
            ) : biaoliError ? (
              <div className="result-error">{biaoliError}</div>
            ) : (
              <div className="empty">
                选择级别组合后，点上方“获取表里状态”，这里会展示当前股票多级别的缠论笔状态与行情阶段。
              </div>
            )
          ) : (
            <>
              <div className="empty">
                {runMode === "full"
                  ? "运行全量回测后，这里会展示汇总统计、历史全量回测结果和对比入口。"
                  : "运行回测后，这里会展示收益、回撤、胜率和交易记录。"}
              </div>
              {runMode === "full" && renderBatchHistorySection()}
            </>
          )
        )}

        {result && !loading && !batchDetailLoading && !result.success && (
          <div className="result-error">{result.message || "回测失败"}</div>
        )}

        {result && !loading && !batchDetailLoading && result.success && (
          <>
            {result.mode === "batch" && batchSummary ? (
              <>
                {(() => {
                  const tradedTargetCount = batchSummary.traded_target_count ?? (batchSummary.profitable_count + batchSummary.loss_count);
                  return (
                <div className="result-grid">
                  <div className="result-item">
                    <span className="label">使用策略</span>
                    <span className="value strategy-text-ellipsis" title={strategyLabelResolver(batchSummary.strategy_name)}>
                      {shortStrategyLabelResolver(batchSummary.strategy_name)}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">累计收益率</span>
                    <span className="value" style={{ color: getReturnColor(batchSummary.cumulative_return) }}>
                      {formatPct(batchSummary.cumulative_return)}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">平均收益率</span>
                    <span className="value" style={{ color: getReturnColor(batchSummary.average_return) }}>
                      {formatPct(batchSummary.average_return)}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">最大回撤</span>
                    <button
                      type="button"
                      className={`metric-link-btn ${batchPayload?.max_drawdown_detail ? "interactive" : ""}`}
                      onClick={() => openMetricDetail("drawdown")}
                      disabled={!batchPayload?.max_drawdown_detail}
                    >
                      {formatPct(batchSummary.max_drawdown)}
                    </button>
                  </div>
                  <div className="result-item">
                    <span className="label">最大涨幅</span>
                    <button
                      type="button"
                      className={`metric-link-btn ${batchPayload?.max_gain_detail ? "interactive" : ""}`}
                      style={{ color: getReturnColor(batchSummary.max_gain) }}
                      onClick={() => openMetricDetail("gain")}
                      disabled={!batchPayload?.max_gain_detail}
                    >
                      {formatPct(batchSummary.max_gain)}
                    </button>
                  </div>
                  <div className="result-item">
                    <span className="label">交易股票数</span>
                    <span className="value">{`${tradedTargetCount}/${batchSummary.target_count}`}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">盈利股票</span>
                    <button
                      type="button"
                      className="metric-link-btn interactive"
                      style={{ color: "var(--accent-red)" }}
                      onClick={() => openBucketDetail("profit")}
                    >
                      {formatStockBucket(batchSummary.profitable_count, batchSummary.profitable_cumulative_return)}
                    </button>
                  </div>
                  <div className="result-item">
                    <span className="label">亏损股票</span>
                    <button
                      type="button"
                      className="metric-link-btn interactive"
                      style={{ color: "var(--accent-green)" }}
                      onClick={() => openBucketDetail("loss")}
                    >
                      {formatStockBucket(batchSummary.loss_count, batchSummary.loss_cumulative_return)}
                    </button>
                  </div>
                  <div className="result-item">
                    <span className="label">单笔平均收益率</span>
                    <button
                      type="button"
                      className="metric-link-btn interactive"
                      style={{ color: getReturnColor(getRoundTripReturnSpread(batchSummary)) }}
                      onClick={() => setSpreadModalOpen(true)}
                    >
                      {formatRoundTripReturnSpread(batchSummary)}
                    </button>
                  </div>
                  <div className="result-item">
                    <span className="label">回测成功标的</span>
                    <span className="value">{batchSummary.backtest_success_target_count ?? "--"}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">回测失败标的</span>
                    <span className="value">{batchSummary.backtest_failed_count ?? "--"}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">回测周期</span>
                    <span className="value" title={formatBatchPeriod(batchSummary)}>
                      {formatBatchPeriod(batchSummary)}
                    </span>
                  </div>
                </div>
                  );
                })()}
                {batchPayload?.failed_items && batchPayload.failed_items.length > 0 && (
                  <div className="trade-records">
                    <div className="panel-card-header" style={{ marginBottom: 8 }}>
                      <h4 style={{ margin: 0 }}>
                        回测失败标的 {batchPayload.failed_items.length} 个
                      </h4>
                    </div>
                    <div className="trade-table-wrap">
                      <table className="trade-table">
                        <thead>
                          <tr>
                            <th>代码</th>
                            <th>名称</th>
                            <th>失败原因</th>
                          </tr>
                        </thead>
                        <tbody>
                          {batchPayload.failed_items.map((item) => (
                            <tr key={`${item.code}-${item.name}`}>
                              <td>{item.code}</td>
                              <td>{item.name}</td>
                              <td style={{ textAlign: "left" }}>{item.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
                {renderBatchHistorySection()}
              </>
            ) : (
              <>
                <div className="result-grid">
                  <div className="result-item">
                    <span className="label">初始资金</span>
                    <span className="value">{result.start_value?.toFixed(2)}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">最终资金</span>
                    <span className="value">{result.end_value?.toFixed(2)}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">总收益率</span>
                    <span
                      className="value"
                      title={`总收益率 ${result.total_return?.toFixed(2)}%｜收益金额 ${result.total_profit != null ? `${result.total_profit > 0 ? "+" : ""}${result.total_profit.toFixed(2)}` : "--"}`}
                      style={{
                        color: getReturnColor(result.total_return),
                        lineHeight: 1.25,
                        whiteSpace: "normal",
                      }}
                    >
                      <span style={{ fontSize: "18px", display: "block" }}>
                        {result.total_return?.toFixed(2)}%
                      </span>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: "normal",
                          color: getReturnColor(result.total_profit),
                          display: "block",
                        }}
                      >
                        收益金额 {result.total_profit != null ? `${result.total_profit > 0 ? "+" : ""}${result.total_profit.toFixed(2)}` : "--"}
                      </span>
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">买入后区间涨跌幅</span>
                    <span
                      className="value"
                      title="从第一次买点出现后的买入价，到回测周期结束时股价的涨跌幅；用于和策略总收益率对比。"
                      style={{
                        color: getReturnColor(result.stock_change_from_first_buy_pct ?? result.stock_change_pct),
                        fontSize: "18px",
                      }}
                    >
                      {result.stock_change_from_first_buy_pct != null
                        ? `${result.stock_change_from_first_buy_pct > 0 ? "+" : ""}${result.stock_change_from_first_buy_pct.toFixed(2)}%`
                        : result.stock_change_pct != null
                        ? `${result.stock_change_pct > 0 ? "+" : ""}${result.stock_change_pct.toFixed(2)}%`
                        : "--"}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">相对不操作</span>
                    <span
                      className="value"
                      title="策略总收益率 - 第一次买点后若一直持有到回测周期结束的涨跌幅。正数表示比不操作多赚，负数表示比不操作少赚或多亏。"
                      style={{
                        color: getReturnColor(result.vs_hold_return),
                        fontSize: "18px",
                      }}
                    >
                      {result.vs_hold_return != null
                        ? `${result.vs_hold_return > 0 ? "+" : ""}${result.vs_hold_return.toFixed(2)}%`
                        : "--"}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">最大回撤</span>
                    <span className="value" style={{ color: "var(--accent-green)", fontSize: "16px" }}>
                      {result.max_drawdown?.toFixed(2)}%
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">K线数量</span>
                    <span className="value">{result.bar_count}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">回测周期</span>
                    <span className="value">{getPeriodLabel(result.period || period)}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">成交笔数</span>
                    <span className="value">{result.total_trades}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">总手续费(万一)</span>
                    <span className="value">{totalCommission.toFixed(2)}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">已平仓笔数</span>
                    <span className="value">{result.closed_trade_count ?? 0}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">完整交易</span>
                    <span className="value">{result.round_trip_trades ?? 0}</span>
                  </div>
                  <div className="result-item">
                    <span className="label">盈利股票</span>
                    <span className="value" style={{ color: "var(--accent-red)" }}>
                      {result.won_trades}
                    </span>
                  </div>
                  <div className="result-item">
                    <span className="label">完整交易胜率</span>
                    <span className="value" style={{
                      color: (result.win_rate ?? 0) >= 50 ? "var(--accent-red)" : "var(--accent-green)"
                    }}>{formatRatioPct(result.win_rate)}</span>
                  </div>
                </div>

                {result.equity_curve && result.equity_curve.length > 0 ? (
                  <EquityCurveChart equity={result.equity_curve} benchmark={result.benchmark_curve} />
                ) : null}

                {result.trade_records && result.trade_records.length > 0 ? (
                  <div className="trade-records">
                    <h4>交易记录</h4>
                    <div className="trade-table-wrap">
                      <table className="trade-table">
                        <thead>
                          <tr>
                            <th>日期</th>
                            <th>方向</th>
                            <th>质量</th>
                            <th>收益率</th>
                            <th>金额</th>
                            <th>手续费</th>
                            <th>收益金额</th>
                            <th>价格</th>
                            <th>数量</th>
                            <th>成本价</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.trade_records.slice(-30).reverse().map((t, i) => {
                            const tradeTs = getTradeMarkerTimestamp(t);
                            const tradeKey = `${t.direction}-${tradeTs ?? "na"}-${i}`;
                            const isSelected =
                              !!selectedTrade &&
                              selectedTrade.direction === t.direction &&
                              selectedTrade.timestamp === tradeTs;

                            return (
                            <tr key={tradeKey} className={isSelected ? "trade-row-selected" : undefined}>
                              <td>
                                <button
                                  type="button"
                                  className="trade-date-btn"
                                  onClick={() => onSelectTrade?.(t)}
                                >
                                  {formatTradeDate(t.date)}
                                </button>
                              </td>
                              <td style={{
                                color: t.direction === "buy" ? "var(--accent-red)" : "var(--accent-green)",
                                fontWeight: "bold"
                              }}>
                                {t.direction === "buy" ? "买" : "卖"}
                              </td>
                              <td title={t.quality?.summary || undefined}>
                                {t.direction === "buy" && t.quality?.score != null ? (
                                  <span style={{ fontWeight: 700, color: qualityBadgeColor(t.quality.score) }}>
                                    {t.quality.score}·{t.quality.grade || "?"}
                                  </span>
                                ) : (
                                  "--"
                                )}
                              </td>
                              <td style={{
                                color: (t.pnl_pct ?? 0) > 0 ? "var(--accent-red)" : (t.pnl_pct ?? 0) < 0 ? "var(--accent-green)" : "var(--text-muted)",
                                fontWeight: 600,
                              }}>
                                {t.pnl_pct != null ? `${t.pnl_pct > 0 ? "+" : ""}${t.pnl_pct.toFixed(2)}%` : "--"}
                              </td>
                              <td>{t.value.toFixed(2)}</td>
                              <td>{t.commission.toFixed(2)}</td>
                              <td style={{
                                color: (t.pnl ?? 0) > 0 ? "var(--accent-red)" : (t.pnl ?? 0) < 0 ? "var(--accent-green)" : "var(--text-muted)",
                                fontWeight: 600,
                              }}>
                                {t.pnl != null ? `${t.pnl > 0 ? "+" : ""}${t.pnl.toFixed(2)}` : "--"}
                              </td>
                              <td style={{ fontWeight: "600" }}>
                                {t.price.toFixed(getTradePriceDigits(result.period || period))}
                              </td>
                              <td>{t.size}</td>
                              <td>{t.avg_cost != null ? t.avg_cost.toFixed(getTradePriceDigits(result.period || period)) : "--"}</td>
                            </tr>
                          )})}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="empty">当前策略在该区间内没有产生交易。</div>
                )}
              </>
            )}
          </>
        )}
      </div>
      {showCompareModal && compareBaseSummary && (
        <CompareModal
          current={compareBaseSummary}
          history={compareSummary}
          historyOptions={filteredCompareOptions}
          selectedHistoryId={compareRunId}
          onSelectHistory={setCompareRunId}
          resolveStrategyLabel={strategyLabelResolver}
          onClose={() => {
            setShowCompareModal(false);
            setCompareRunDetail(null);
          }}
        />
      )}
      {metricModal && (
        <MetricDetailModal
          title={metricModal.title}
          detail={metricModal.detail}
          onInspect={inspectMetricDetail}
          onClose={() => setMetricModal(null)}
        />
      )}
      {bucketModal && (
        <BucketDetailModal
          title={bucketModal.title}
          cumulativeReturn={bucketModal.cumulativeReturn}
          items={bucketModal.items}
          bucketType={bucketModal.bucketType}
          note={bucketModal.note}
          loadingCode={bucketInspectCode}
          onInspectStock={inspectBucketStock}
          onClose={() => setBucketModal(null)}
        />
      )}
      {spreadModalOpen && batchSummary && (
        <RoundTripSpreadModal
          summary={batchSummary}
          onClose={() => setSpreadModalOpen(false)}
        />
      )}
    </div>
  );
}
