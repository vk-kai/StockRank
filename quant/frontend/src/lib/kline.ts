// 盘中K线静默刷新节流:后端分钟柱缓存 20s + 用户可接受的"十几秒级"新鲜度,
// 15s 节流把每次全量重拉(含盘中日K的腾讯单码行情补充)从 ~12 次/分钟 压到 ~4 次/分钟,防风控
export const REALTIME_KLINE_REFRESH_MS = 15000;
export const DEFAULT_KLINE_COUNT = 300;
export const HISTORY_KLINE_STEP = 300;
// 缓存命中后 loadKline 仍会立即后台刷新并替换，因此较长 TTL 只影响「秒开首帧」的新鲜度，不影响选中后的实时性
export const KLINE_FRONTEND_CACHE_TTL_MS = 5 * 60 * 1000;
export const KLINE_FRONTEND_CACHE_MAX = 240;
export const PREFETCH_NEARBY_WATCHLIST_COUNT = 1;
// 首次进入页面后，为自选股批量预取的周期及节奏（只取各周期默认可见根数，缩放/翻页历史不预取）
export const KLINE_PREFETCH_PERIODS = ["daily", "30", "5", "15", "60"];
export const KLINE_PREFETCH_INITIAL_DELAY_MS = 1000;
export const KLINE_PREFETCH_STAGGER_MS = 150;
// 盘中K线静默刷新目前只由 WS quotes 推送触发；连接断开/推送缺失/标签页隔夜
// 未刷新时，主图会冻结在首屏数据（典型表现：盘中看不到最新一根）。用低频
// 轮询+页面聚焦兜底，间隔大于 REALTIME_KLINE_REFRESH_MS，节流仍由后者保证。
export const KLINE_FALLBACK_POLL_MS = 30000;

// A股粗略交易时段判断（北京时间 9:15-15:15，不含节假日），仅用于兜底轮询开关：
// 判断错了顶多少刷/多刷一次，数据新鲜度由后端保证
export function isLikelyTradingTime(now: Date = new Date()): boolean {
  const beijing = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60_000);
  const day = beijing.getDay();
  if (day === 0 || day === 6) return false;
  const minutes = beijing.getHours() * 60 + beijing.getMinutes();
  return minutes >= 9 * 60 + 15 && minutes <= 15 * 60 + 15;
}

import type { KlineData } from "../types";

const DEFAULT_MA_PERIODS = [5, 10, 20, 60, 144];

function roundIndicatorValue(value: number, digits = 5) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : Number.NaN;
}

function getCloseValues(data: KlineData[]) {
  return data.map((item) => Number(item.close));
}

export function calculateChartMA(data: KlineData[], periods = DEFAULT_MA_PERIODS): Record<string, number[]> {
  const closeValues = getCloseValues(data);
  const result: Record<string, number[]> = {};

  periods.forEach((period) => {
    const values = Array<number>(closeValues.length).fill(Number.NaN);
    let sum = 0;
    let invalidCount = 0;

    closeValues.forEach((close, index) => {
      if (Number.isFinite(close)) {
        sum += close;
      } else {
        invalidCount += 1;
      }

      if (index >= period) {
        const previous = closeValues[index - period];
        if (Number.isFinite(previous)) {
          sum -= previous;
        } else {
          invalidCount -= 1;
        }
      }

      if (index >= period - 1 && invalidCount === 0) {
        values[index] = roundIndicatorValue(sum / period);
      }
    });

    result[`MA${period}`] = values;
  });

  return result;
}

function calculateEma(values: number[], span: number) {
  const alpha = 2 / (span + 1);
  const result = Array<number>(values.length).fill(Number.NaN);
  let previous: number | null = null;

  values.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      return;
    }

    const next = previous == null ? value : value * alpha + previous * (1 - alpha);
    result[index] = next;
    previous = next;
  });

  return result;
}

export function calculateChartMACD(data: KlineData[], fast = 12, slow = 26, signal = 9) {
  const closeValues = getCloseValues(data);
  const emaFast = calculateEma(closeValues, fast);
  const emaSlow = calculateEma(closeValues, slow);
  const difRaw = closeValues.map((_, index) => {
    const dif = emaFast[index] - emaSlow[index];
    return Number.isFinite(dif) ? dif : Number.NaN;
  });
  const deaRaw = calculateEma(difRaw, signal);

  return {
    DIF: difRaw.map((value) => roundIndicatorValue(value)),
    DEA: deaRaw.map((value) => roundIndicatorValue(value)),
    MACD: difRaw.map((value, index) => roundIndicatorValue((value - deaRaw[index]) * 2)),
  };
}

export function calculateChartBOLL(data: KlineData[], period = 20, nbdev = 2) {
  const closeValues = getCloseValues(data);
  const mid = Array<number>(closeValues.length).fill(Number.NaN);
  const upper = Array<number>(closeValues.length).fill(Number.NaN);
  const lower = Array<number>(closeValues.length).fill(Number.NaN);
  let sum = 0;
  let sumSquares = 0;
  let invalidCount = 0;

  closeValues.forEach((close, index) => {
    if (Number.isFinite(close)) {
      sum += close;
      sumSquares += close * close;
    } else {
      invalidCount += 1;
    }

    if (index >= period) {
      const previous = closeValues[index - period];
      if (Number.isFinite(previous)) {
        sum -= previous;
        sumSquares -= previous * previous;
      } else {
        invalidCount -= 1;
      }
    }

    if (index >= period - 1 && invalidCount === 0) {
      const mean = sum / period;
      const variance = Math.max(sumSquares / period - mean * mean, 0);
      const std = Math.sqrt(variance);
      mid[index] = roundIndicatorValue(mean);
      upper[index] = roundIndicatorValue(mean + nbdev * std);
      lower[index] = roundIndicatorValue(mean - nbdev * std);
    }
  });

  return {
    MID: mid,
    UPPER: upper,
    LOWER: lower,
  };
}

export function calculateChartIndicators(data: KlineData[]) {
  return {
    ma: calculateChartMA(data),
    macd: calculateChartMACD(data),
    boll: calculateChartBOLL(data),
  };
}

export function getDefaultKlineCount(period: string) {
  if (period === "1") return 240;
  if (period === "5") return 480;
  if (period === "15") return 480;
  if (period === "30") return 240;
  if (period === "60") return 120;
  if (period === "120") return 120;
  if (period === "daily") return 300;
  if (period === "weekly") return 200;
  if (period === "monthly") return 120;
  if (period === "quarter") return 60;
  if (period === "year") return 30;
  return DEFAULT_KLINE_COUNT;
}
