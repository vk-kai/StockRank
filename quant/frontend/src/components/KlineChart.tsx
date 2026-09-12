import { useEffect, useRef, useCallback, useState } from "react";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  ColorType,
  MouseEventParams,
  TickMarkType,
  LineType,
  LineStyle,
} from "lightweight-charts";
import type { BenchmarkPoint, KlineData, SignalInfo } from "../types";
import { parseChartTimestampText } from "../lib/chartTime";
import type { AutoDrawLine } from "../lib/chan";

interface Props {
  data: KlineData[];
  maData: Record<string, number[]> | null;
  macdData: { DIF: number[]; DEA: number[]; MACD: number[] } | null;
  bollData: { MID: number[]; UPPER: number[]; LOWER: number[] } | null;
  signals: SignalInfo[];
  showMA: boolean;
  showMACD: boolean;
  showBOLL: boolean;
  showVolume: boolean;
  period?: string;
  securityKind?: string;
  resetKey?: string;
  highlightedSignal?: { timestamp: number; direction: string } | null;
  onRequestMoreHistory?: () => void;
  historyLoadInfo?: { requestId: number; prependedBars: number } | null;
  onCandleDoubleClick?: (bar: KlineData) => void;
  autoDrawLines?: AutoDrawLine[];
  showAutoDraw?: boolean;
  autoDrawColor?: string;
  autoDrawWidthLevel?: 1 | 2 | 3 | 4;
  /** 分时叠加基准(仅 intraday 生效);提供时主图切到归一化涨跌幅% 双线模式 */
  benchmark?: { label: string; points: BenchmarkPoint[] } | null;
  /** 个股昨收(benchMode 归一化基准);缺省时不进入叠加模式 */
  stockPctBase?: number | null;
}

const MA_COLORS: Record<string, string> = {
  MA5: "#FFD700",
  MA10: "#00BFFF",
  MA20: "#FF69B4",
  MA60: "#9370DB",
  MA144: "#FF1493", // 更改为深粉色
};

const MA_WIDTHS: Record<string, number> = {
  MA5: 1,
  MA10: 1,
  MA20: 1,
  MA60: 1,
  MA144: 1, // 取消加粗，设为1
};

const WEEKDAY_LABELS = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
const LONG_PERIODS = ["daily", "weekly", "monthly", "quarter", "year"];

function formatHoverDateLabel(timestamp: number, period?: string) {
  const date = new Date(timestamp * 1000);
  const datePart = `${date.getUTCFullYear()}/${date.getUTCMonth() + 1}/${date.getUTCDate()} ${WEEKDAY_LABELS[date.getUTCDay()]}`;
  if (period && !LONG_PERIODS.includes(period)) {
    const hh = String(date.getUTCHours()).padStart(2, "0");
    const mm = String(date.getUTCMinutes()).padStart(2, "0");
    return `${datePart} ${hh}:${mm}`;
  }
  return datePart;
}

function getPriceDigits(period?: string, securityKind?: string) {
  if (securityKind === "index") return 2;
  return period && !LONG_PERIODS.includes(period) ? 5 : 3;
}

function formatPrice(value: number, digits: number) {
  return value.toFixed(digits);
}

function formatSignedPrice(value: number, digits: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function formatSignedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function getHighlightWindow(period?: string) {
  if (period === "daily") {
    return { before: 90, after: 30 };
  }
  if (period === "weekly" || period === "monthly") {
    return { before: 60, after: 20 };
  }
  return { before: 80, after: 40 };
}

function formatVolume(value: number) {
  if (value >= 1e8) {
    return `${(value / 1e8).toFixed(2)}亿`;
  }
  if (value >= 1e4) {
    return `${(value / 1e4).toFixed(2)}万`;
  }
  return value.toLocaleString("zh-CN");
}

function formatAmount(value: number) {
  if (value >= 1e8) {
    return `${(value / 1e8).toFixed(2)}亿`;
  }
  if (value >= 1e4) {
    return `${(value / 1e4).toFixed(2)}万`;
  }
  return value.toFixed(2);
}

function toUnixTimestamp(time: Time) {
  if (typeof time === "number") {
    return time;
  }

  if (typeof time === "string") {
    return parseChartTimestampText(time);
  }

  const year = "year" in time ? time.year : 1970;
  const month = "month" in time ? time.month - 1 : 0;
  const day = "day" in time ? time.day : 1;
  return Math.floor(Date.UTC(year, month, day) / 1000);
}

function formatAxisDateLabel(time: Time, tickMarkType: TickMarkType, period?: string) {
  const timestamp = toUnixTimestamp(time);
  if (timestamp == null) {
    return "";
  }

  const date = new Date(timestamp * 1000);
  const yyyy = date.getUTCFullYear();
  const mm = date.getUTCMonth() + 1;
  const dd = date.getUTCDate();
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const min = String(date.getUTCMinutes()).padStart(2, "0");

  if (period && LONG_PERIODS.includes(period)) {
    if (tickMarkType === TickMarkType.Year) {
      return `${yyyy}`;
    }
    if (tickMarkType === TickMarkType.Month) {
      return `${yyyy}/${mm}`;
    }
    return `${yyyy}/${mm}/${dd}`;
  }

  if (tickMarkType === TickMarkType.Time || tickMarkType === TickMarkType.TimeWithSeconds) {
    return `${hh}:${min}`;
  }

  if (tickMarkType === TickMarkType.Year) {
    return `${yyyy}`;
  }
  if (tickMarkType === TickMarkType.Month) {
    return `${yyyy}/${mm}`;
  }
  return `${yyyy}/${mm}/${dd}`;
}

function parseSignalTimestamp(value: string) {
  return parseChartTimestampText(value);
}

function getSignalTimestamp(signal: SignalInfo) {
  if (typeof signal.timestamp === "number" && Number.isFinite(signal.timestamp)) {
    return Math.floor(signal.timestamp);
  }
  return parseSignalTimestamp(signal.time);
}

function resolveSignalBarTimestamp(signal: SignalInfo, data: KlineData[]) {
  const signalTs = getSignalTimestamp(signal);
  if (signalTs == null || data.length === 0) return null;

  for (let i = 0; i < data.length; i++) {
    const currentTs = data[i].timestamp;
    if (signalTs === currentTs) {
      return currentTs;
    }

    const nextTs = i < data.length - 1 ? data[i + 1].timestamp : null;
    if (signalTs >= currentTs && (nextTs == null || signalTs < nextTs)) {
      return currentTs;
    }

    if (signalTs < currentTs) {
      return i > 0 ? data[i - 1].timestamp : null;
    }
  }

  return data[data.length - 1].timestamp;
}

/** 计算MACD红绿柱子面积并生成标注marker */
function calcMacdAreaMarkers(
  data: KlineData[],
  macdVals: number[]
): any[] {
  const markers: any[] = [];
  if (!data || data.length === 0 || !macdVals || macdVals.length === 0) {
    return markers;
  }

  const minHist = 1e-6;
  let segStart = -1;
  let segSign = 0; // 1=红柱(>0), -1=绿柱(<0)
  let segArea = 0;
  let peakIdx = -1;
  let peakAbs = 0;

  for (let i = 0; i < data.length; i++) {
    const v = macdVals[i];
    if (v === null || v === undefined || isNaN(v)) {
      // 结束当前段
      if (segStart >= 0 && segSign !== 0) {
        pushAreaMarker(markers, data, segStart, i - 1, segSign, segArea, peakIdx);
      }
      segStart = -1;
      segSign = 0;
      segArea = 0;
      peakIdx = -1;
      peakAbs = 0;
      continue;
    }

    const curSign = v > minHist ? 1 : v < -minHist ? -1 : 0;

    if (segSign === 0) {
      if (curSign !== 0) {
        segStart = i;
        segSign = curSign;
        segArea = Math.abs(v);
        peakIdx = i;
        peakAbs = Math.abs(v);
      }
    } else if (curSign === segSign) {
      segArea += Math.abs(v);
      if (Math.abs(v) > peakAbs) {
        peakAbs = Math.abs(v);
        peakIdx = i;
      }
    } else {
      // 符号变化，结束当前段
      pushAreaMarker(markers, data, segStart, i - 1, segSign, segArea, peakIdx);
      if (curSign !== 0) {
        segStart = i;
        segSign = curSign;
        segArea = Math.abs(v);
        peakIdx = i;
        peakAbs = Math.abs(v);
      } else {
        segStart = -1;
        segSign = 0;
        segArea = 0;
        peakIdx = -1;
        peakAbs = 0;
      }
    }
  }

  // 处理最后一段
  if (segStart >= 0 && segSign !== 0) {
    pushAreaMarker(markers, data, segStart, data.length - 1, segSign, segArea, peakIdx);
  }

  return markers;
}

function pushAreaMarker(
  markers: any[],
  data: KlineData[],
  segStart: number,
  segEnd: number,
  sign: number,
  area: number,
  peakIdx: number
) {
  if (segEnd < segStart || peakIdx < 0) return;
  // 只标注面积足够大的段（过滤噪声）
  if (area < 0.01) return;

  const isRed = sign === 1;
  const absArea = Math.abs(area);
  // 面积值格式化：根据大小选择精度
  const areaText =
    absArea >= 100 ? absArea.toFixed(0) :
    absArea >= 10 ? absArea.toFixed(1) :
    absArea >= 1 ? absArea.toFixed(2) :
    absArea.toFixed(3);

  markers.push({
    time: data[peakIdx].timestamp as Time,
    position: isRed ? "aboveBar" : "belowBar",
    color: isRed ? "rgba(239,83,80,0.9)" : "rgba(38,166,154,0.9)",
    shape: isRed ? "arrowDown" : "arrowUp",
    text: areaText,
  });
}

export default function KlineChart({
  data,
  maData,
  macdData,
  bollData,
  signals,
  showMA,
  showMACD,
  showBOLL,
  showVolume,
  period,
  securityKind,
  resetKey,
  highlightedSignal,
  onRequestMoreHistory,
  historyLoadInfo,
  onCandleDoubleClick,
  autoDrawLines = [],
  showAutoDraw = false,
  autoDrawColor = "#ffd166",
  autoDrawWidthLevel = 3,
  benchmark = null,
  stockPctBase = null,
}: Props) {
  const isIntraday = period === "intraday";
  const isMinutePeriod = !!period && !["intraday", "daily", "weekly", "monthly", "quarter", "year"].includes(period);
  const indicatorLineWidth = 1;
  const priceDigits = getPriceDigits(period, securityKind);
  const smoothLineType = isIntraday || isMinutePeriod ? LineType.Curved : LineType.Simple;
  const containerRef = useRef<HTMLDivElement>(null);
  const [legendValues, setLegendValues] = useState<Record<string, string>>({});
  const [hoverSignalDetails, setHoverSignalDetails] = useState<{
    x: number;
    y: number;
    items: SignalInfo[];
  } | null>(null);
  const [hoverCandleDetails, setHoverCandleDetails] = useState<{
    dateLabel: string;
    prevClose: number;
    open: number;
    high: number;
    low: number;
    close: number;
    change: number;
    changePct: number;
    amplitudePct: number;
    volume: number;
    amount: number;
  } | null>(null);
  const [hoverBenchPct, setHoverBenchPct] = useState<number | null>(null);
  const [tradeHighlightOverlay, setTradeHighlightOverlay] = useState<{
    x: number;
    y: number;
    label: string;
    direction: string;
  } | null>(null);
  const [visibleExtremaOverlays, setVisibleExtremaOverlays] = useState<
    Array<{
      kind: "high" | "low";
      x: number;
      y: number;
      price: number;
      timestamp: number;
    }>
  >([]);

  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const intradaySeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const maSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
  const autoDrawSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const benchSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const macdChartRef = useRef<IChartApi | null>(null);
  const macdDifRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdDeaRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const bollChartRef = useRef<IChartApi | null>(null);
  const bollCandleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const bollUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollMidRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollLowerRef = useRef<ISeriesApi<"Line"> | null>(null);

  const subHeights = useRef<{ macd: number; boll: number }>({ macd: 0, boll: 0 });
  const mainContainerRef = useRef<HTMLDivElement | null>(null);
  const macdContainerRef = useRef<HTMLDivElement | null>(null);
  const bollContainerRef = useRef<HTMLDivElement | null>(null);
  const dividerRefs = useRef<{ macd: HTMLDivElement | null; boll: HTMLDivElement | null }>({ macd: null, boll: null });

  const syncingRef = useRef(false);
  const syncingCrosshairRef = useRef(false);
  const restoringRangeRef = useRef(false);
  const rightPriceScaleWidthRef = useRef(72);
  const visibleLogicalRangeRef = useRef<{ from: number; to: number } | null>(null);
  const hasAutoFittedRef = useRef(false);
  const syncCrosshairAtIndexRef = useRef<((source: "main" | "macd" | "boll" | "programmatic", idx: number) => void) | null>(null);
  const historyRequestPendingRef = useRef(false);
  const lastHistoryLoadRequestIdRef = useRef<number | null>(null);
  const latestDataRef = useRef(data);
  const onCandleDoubleClickRef = useRef(onCandleDoubleClick);
  const latestSignalsRef = useRef(signals);
  const latestMaDataRef = useRef(maData);
  const latestMacdDataRef = useRef(macdData);
  const latestBollDataRef = useRef(bollData);
  const latestBenchMapRef = useRef<Map<number, number> | null>(null);
  const latestBenchModeRef = useRef(false);

  latestDataRef.current = data;
  onCandleDoubleClickRef.current = onCandleDoubleClick;
  latestSignalsRef.current = signals;
  latestMaDataRef.current = maData;
  latestMacdDataRef.current = macdData;
  latestBollDataRef.current = bollData;
  const benchMode = !!(benchmark && benchmark.points.length > 0 && stockPctBase && stockPctBase > 0 && isIntraday);
  const benchMap = benchmark && benchmark.points
    ? new Map(
        benchmark.points
          .filter((p) => p.timestamp && p.pct != null)
          .map((p) => [p.timestamp, p.pct as number])
      )
    : null;
  latestBenchMapRef.current = benchMode ? benchMap : null;
  latestBenchModeRef.current = benchMode;

  const syncRightPriceScaleWidths = useCallback(() => {
    const widths = [
      chartRef.current?.priceScale("right").width() ?? 0,
      macdChartRef.current?.priceScale("right").width() ?? 0,
      bollChartRef.current?.priceScale("right").width() ?? 0,
      rightPriceScaleWidthRef.current,
    ];
    const targetWidth = Math.max(72, ...widths);
    rightPriceScaleWidthRef.current = targetWidth;

    chartRef.current?.priceScale("right").applyOptions({ minimumWidth: targetWidth });
    macdChartRef.current?.priceScale("right").applyOptions({ minimumWidth: targetWidth });
    bollChartRef.current?.priceScale("right").applyOptions({ minimumWidth: targetWidth });
  }, []);

  const scheduleRightPriceScaleSync = useCallback(() => {
    requestAnimationFrame(() => {
      syncRightPriceScaleWidths();
      requestAnimationFrame(() => {
        syncRightPriceScaleWidths();
      });
    });
  }, [syncRightPriceScaleWidths]);

  const refreshVisibleExtremaOverlays = useCallback(() => {
    const chart = chartRef.current;
    const latestData = latestDataRef.current;
    const mainSeries = isIntraday ? intradaySeriesRef.current : candleSeriesRef.current;
    if (!chart || !mainSeries || latestData.length === 0) {
      setVisibleExtremaOverlays([]);
      return;
    }

    const timeRange = chart.timeScale().getVisibleRange();
    if (!timeRange) {
      setVisibleExtremaOverlays([]);
      return;
    }

    const visibleBars = latestData.filter(
      (bar) => bar.timestamp >= Number(timeRange.from) && bar.timestamp <= Number(timeRange.to)
    );
    if (visibleBars.length === 0) {
      setVisibleExtremaOverlays([]);
      return;
    }

    let highestBar = visibleBars[0];
    let lowestBar = visibleBars[0];
    for (let i = 1; i < visibleBars.length; i += 1) {
      const current = visibleBars[i];
      if (current.high > highestBar.high || (current.high === highestBar.high && current.timestamp > highestBar.timestamp)) {
        highestBar = current;
      }
      if (current.low < lowestBar.low || (current.low === lowestBar.low && current.timestamp > lowestBar.timestamp)) {
        lowestBar = current;
      }
    }

    const nextOverlays = [
      {
        kind: "high" as const,
        x: chart.timeScale().timeToCoordinate(highestBar.timestamp as Time),
        y: mainSeries.priceToCoordinate(highestBar.high),
        price: highestBar.high,
        timestamp: highestBar.timestamp,
      },
      {
        kind: "low" as const,
        x: chart.timeScale().timeToCoordinate(lowestBar.timestamp as Time),
        y: mainSeries.priceToCoordinate(lowestBar.low),
        price: lowestBar.low,
        timestamp: lowestBar.timestamp,
      },
    ].filter(
      (item) =>
        item.x != null &&
        item.y != null &&
        Number.isFinite(item.x) &&
        Number.isFinite(item.y)
    ) as Array<{
      kind: "high" | "low";
      x: number;
      y: number;
      price: number;
      timestamp: number;
    }>;

    setVisibleExtremaOverlays(nextOverlays);
  }, [isIntraday]);

  const maybeRequestMoreHistory = useCallback((range: { from: number; to: number } | null) => {
    if (!onRequestMoreHistory || !range || historyRequestPendingRef.current) {
      return;
    }
    if (range.from <= 30) {
      historyRequestPendingRef.current = true;
      onRequestMoreHistory();
    }
  }, [onRequestMoreHistory]);

  const buildChart = useCallback(() => {
    if (!containerRef.current) return;

    containerRef.current.innerHTML = "";

    chartRef.current = null;
    candleSeriesRef.current = null;
    intradaySeriesRef.current = null;
    volumeSeriesRef.current = null;
    maSeriesRef.current = {};
    autoDrawSeriesRef.current = [];
    benchSeriesRef.current = null;
    macdChartRef.current = null;
    macdDifRef.current = null;
    macdDeaRef.current = null;
    macdHistRef.current = null;
    bollChartRef.current = null;
    bollCandleSeriesRef.current = null;
    bollUpperRef.current = null;
    bollMidRef.current = null;
    bollLowerRef.current = null;
    syncCrosshairAtIndexRef.current = null;
    mainContainerRef.current = null;
    macdContainerRef.current = null;
    bollContainerRef.current = null;
    dividerRefs.current = { macd: null, boll: null };

    const parent = containerRef.current;
    const totalHeight = parent.clientHeight;
    const subCount = (showMACD ? 1 : 0) + (showBOLL ? 1 : 0);

    let defaultMainH = subCount === 0 ? totalHeight : subCount === 1 ? Math.floor(totalHeight * 0.65) : Math.floor(totalHeight * 0.5);
    let defaultSubH = subCount === 0 ? 0 : subCount === 1 ? totalHeight - defaultMainH - 6 : Math.floor((totalHeight - defaultMainH - 12) / 2);

    if (subHeights.current.macd === 0 && showMACD) subHeights.current.macd = defaultSubH;
    if (subHeights.current.boll === 0 && showBOLL) subHeights.current.boll = defaultSubH;

    let mainH = defaultMainH;
    if (showMACD) mainH = totalHeight - subHeights.current.macd - (showBOLL ? subHeights.current.boll + 6 : 0) - (showBOLL ? 6 : 0);
    if (showBOLL && !showMACD) mainH = totalHeight - subHeights.current.boll - 6;
    if (subCount === 0) mainH = totalHeight;
    mainH = Math.max(mainH, 200);

    const mainContainer = document.createElement("div");
    mainContainer.style.height = `${mainH}px`;
    mainContainer.style.width = "100%";
    mainContainer.style.position = "relative";
    parent.appendChild(mainContainer);
    mainContainerRef.current = mainContainer;

    const chart = createChart(mainContainer, {
      width: parent.clientWidth,
      height: mainH,
      layout: {
        background: { type: ColorType.Solid, color: "#1a1a2e" },
        textColor: "#d1d4dc",
      },
      grid: {
        vertLines: { color: "#2a2a3e" },
        horzLines: { color: "#2a2a3e" },
      },
      crosshair: {
        mode: 0,
        vertLine: { labelVisible: false },
        horzLine: { labelVisible: false },
      },
      rightPriceScale: { borderColor: "#2a2a3e" },
      timeScale: {
        borderColor: "#2a2a3e",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) =>
          formatAxisDateLabel(time, tickMarkType, period),
      },
      localization: {
        locale: "zh-CN",
        priceFormatter: (p: number) => p.toFixed(priceDigits),
      },
    });
    chartRef.current = chart;

    const handleMainChartDoubleClick = (event: MouseEvent) => {
      if (!onCandleDoubleClickRef.current || latestDataRef.current.length === 0 || !chartRef.current) {
        return;
      }

      const rect = mainContainer.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const clickedTime = chartRef.current.timeScale().coordinateToTime(x);
      const clickedTs = clickedTime == null ? null : toUnixTimestamp(clickedTime);
      let bestBar: KlineData | null = null;

      if (clickedTs != null) {
        bestBar = latestDataRef.current[0];
        let bestDistance = Math.abs(bestBar.timestamp - clickedTs);
        for (const bar of latestDataRef.current) {
          const distance = Math.abs(bar.timestamp - clickedTs);
          if (distance < bestDistance) {
            bestBar = bar;
            bestDistance = distance;
          }
        }
      }

      if (!bestBar) {
        const clickedLogical = chartRef.current.timeScale().coordinateToLogical(x);
        if (clickedLogical != null && Number.isFinite(clickedLogical)) {
          const targetIndex = Math.max(
            0,
            Math.min(latestDataRef.current.length - 1, Math.round(clickedLogical))
          );
          bestBar = latestDataRef.current[targetIndex];
        }
      }

      if (bestBar) {
        onCandleDoubleClickRef.current(bestBar);
      }
    };
    mainContainer.addEventListener("dblclick", handleMainChartDoubleClick);

    if (isIntraday) {
      const intradaySeries = chart.addLineSeries({
        color: "#f0b90b",
        lineWidth: 1,
        lineType: smoothLineType,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      intradaySeriesRef.current = intradaySeries;
    } else {
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#ef5350",
        downColor: "#26a69a",
        borderDownColor: "#26a69a",
        borderUpColor: "#ef5350",
        wickDownColor: "#26a69a",
        wickUpColor: "#ef5350",
      });
      candleSeriesRef.current = candleSeries;
    }

    if (showVolume && !isIntraday) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeriesRef.current = volumeSeries;
    }

    if (showMA && maData && !isIntraday) {
      Object.keys(maData).forEach((key) => {
        const lineSeries = chart.addLineSeries({
          color: MA_COLORS[key] || "#ffffff",
          lineWidth: Math.max(MA_WIDTHS[key] || 1, indicatorLineWidth) as any,
          lineType: smoothLineType,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        maSeriesRef.current[key] = lineSeries;
      });
    }

    const clearSubChartCrosshair = () => {
      macdChartRef.current?.clearCrosshairPosition();
      bollChartRef.current?.clearCrosshairPosition();
    };

    const syncCrosshairAtIndex = (source: "main" | "macd" | "boll" | "programmatic", idx: number) => {
      if (syncingCrosshairRef.current || idx < 0 || idx >= latestDataRef.current.length) {
        return;
      }

      const bar = latestDataRef.current[idx];
      const barTime = bar.timestamp as Time;
      const latestMacdData = latestMacdDataRef.current;
      const latestBollData = latestBollDataRef.current;
      syncingCrosshairRef.current = true;

      try {
        if (source !== "main") {
          const mainSeries = isIntraday ? intradaySeriesRef.current : candleSeriesRef.current;
          const mainAnchor = bar.close;
          if (
            chartRef.current &&
            mainSeries &&
            mainAnchor != null &&
            !isNaN(mainAnchor)
          ) {
            chartRef.current.setCrosshairPosition(mainAnchor, barTime, mainSeries);
          } else {
            chartRef.current?.clearCrosshairPosition();
          }
        }

        const dif = latestMacdData?.DIF?.[idx];
        const dea = latestMacdData?.DEA?.[idx];
        const macdAnchor = [dif, dea].find((value) => value != null && !isNaN(value as number));
        if (
          source !== "macd" &&
          macdChartRef.current &&
          showMACD &&
          macdDifRef.current &&
          macdAnchor != null &&
          !isNaN(macdAnchor)
        ) {
          macdChartRef.current.setCrosshairPosition(macdAnchor, barTime, macdDifRef.current);
        } else {
          if (source !== "macd") {
            macdChartRef.current?.clearCrosshairPosition();
          }
        }

        const bollAnchor = latestBollData?.MID?.[idx] ?? bar.close;
        if (
          source !== "boll" &&
          bollChartRef.current &&
          showBOLL &&
          bollCandleSeriesRef.current &&
          bollAnchor != null &&
          !isNaN(bollAnchor)
        ) {
          bollChartRef.current.setCrosshairPosition(bollAnchor, barTime, bollCandleSeriesRef.current);
        } else {
          if (source !== "boll") {
            bollChartRef.current?.clearCrosshairPosition();
          }
        }
      } catch {
        clearSubChartCrosshair();
      } finally {
        syncingCrosshairRef.current = false;
      }
    };
    syncCrosshairAtIndexRef.current = syncCrosshairAtIndex;

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      const latestData = latestDataRef.current;
      const latestSignals = latestSignalsRef.current;
      const latestMaData = latestMaDataRef.current;

      if (!param.time || !param.point) {
        clearSubChartCrosshair();
        const lastValues: Record<string, string> = {};
        if (showMA && latestMaData && !isIntraday) {
          Object.keys(latestMaData).forEach((key) => {
            const arr = latestMaData[key];
            for (let i = arr.length - 1; i >= 0; i--) {
              if (arr[i] != null && !isNaN(arr[i])) {
                lastValues[key] = arr[i].toFixed(priceDigits);
                break;
              }
            }
          });
        }
        setLegendValues(lastValues);
        setHoverSignalDetails(null);
        setHoverCandleDetails(null);
        setHoverBenchPct(null);
        return;
      }

      const hoveredTs = toUnixTimestamp(param.time);
      const idx = hoveredTs == null ? -1 : latestData.findIndex((d) => d.timestamp === hoveredTs);
      if (idx >= 0) {
        syncCrosshairAtIndex("main", idx);
      } else {
        clearSubChartCrosshair();
      }
      const newValues: Record<string, string> = {};
      if (showMA && latestMaData && !isIntraday && idx >= 0) {
        Object.keys(latestMaData).forEach((key) => {
          const v = latestMaData[key][idx];
          if (v != null && !isNaN(v)) {
            newValues[key] = v.toFixed(priceDigits);
          }
        });
      }
      setLegendValues(newValues);
      setHoverBenchPct(
        latestBenchModeRef.current && hoveredTs != null
          ? latestBenchMapRef.current?.get(hoveredTs) ?? null
          : null
      );
      if (idx >= 0) {
        const prevClose = idx > 0 ? latestData[idx - 1].close : latestData[idx].open;
        const change = latestData[idx].close - prevClose;
        const changePct = prevClose ? (change / prevClose) * 100 : 0;
        const amplitudePct = prevClose ? ((latestData[idx].high - latestData[idx].low) / prevClose) * 100 : 0;
        setHoverCandleDetails({
          dateLabel: formatHoverDateLabel(latestData[idx].timestamp, period),
          prevClose,
          open: latestData[idx].open,
          high: latestData[idx].high,
          low: latestData[idx].low,
          close: latestData[idx].close,
          change,
          changePct,
          amplitudePct,
          volume: latestData[idx].volume,
          amount: latestData[idx].amount ?? 0,
        });

        const matchedSignals = latestSignals.filter(
          (signal) => resolveSignalBarTimestamp(signal, latestData) === latestData[idx].timestamp
        );
        if (matchedSignals.length > 0) {
          setHoverSignalDetails({
            x: param.point.x,
            y: param.point.y,
            items: matchedSignals,
          });
        } else {
          setHoverSignalDetails(null);
        }
      } else {
        setHoverSignalDetails(null);
        setHoverCandleDetails(null);
        setHoverBenchPct(null);
      }
    });

    if (showMACD) {
      const divider1 = document.createElement("div");
      divider1.style.height = "6px";
      divider1.style.width = "100%";
      divider1.style.cursor = "ns-resize";
      divider1.style.background = "#2a2a3e";
      divider1.style.position = "relative";
      divider1.style.zIndex = "10";
      divider1.innerHTML = '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:40px;height:3px;background:#45B7D1;border-radius:2px;opacity:0.5"></div>';
      parent.appendChild(divider1);
      dividerRefs.current.macd = divider1;

      const macdH = subHeights.current.macd;
      const macdContainer = document.createElement("div");
      macdContainer.style.height = `${macdH}px`;
      macdContainer.style.width = "100%";
      parent.appendChild(macdContainer);
      macdContainerRef.current = macdContainer;

      const macdChart = createChart(macdContainer, {
        width: parent.clientWidth,
        height: macdH,
        layout: {
          background: { type: ColorType.Solid, color: "#1a1a2e" },
          textColor: "#d1d4dc",
        },
        grid: {
          vertLines: { color: "#2a2a3e" },
          horzLines: { color: "#2a2a3e" },
        },
        crosshair: {
          mode: 0,
          vertLine: { labelVisible: false },
          horzLine: { labelVisible: false },
        },
        rightPriceScale: { borderColor: "#2a2a3e" },
        timeScale: { borderColor: "#2a2a3e", timeVisible: true, visible: false },
      });
      macdChartRef.current = macdChart;

      macdDifRef.current = macdChart.addLineSeries({
        color: "#f0b90b",
        lineWidth: indicatorLineWidth,
        lineType: smoothLineType,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      macdDeaRef.current = macdChart.addLineSeries({
        color: "#ffffff",
        lineWidth: indicatorLineWidth,
        lineType: smoothLineType,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      macdHistRef.current = macdChart.addHistogramSeries({
        priceLineVisible: false,
        lastValueVisible: false,
      });

      macdChart.subscribeCrosshairMove((param: MouseEventParams) => {
        if (syncingCrosshairRef.current) {
          return;
        }
        if (!param.time) {
          chartRef.current?.clearCrosshairPosition();
          bollChartRef.current?.clearCrosshairPosition();
          return;
        }
        const hoveredTs = toUnixTimestamp(param.time);
        const idx = hoveredTs == null ? -1 : latestDataRef.current.findIndex((d) => d.timestamp === hoveredTs);
        if (idx >= 0) {
          syncCrosshairAtIndex("macd", idx);
        }
      });
    }

    if (showBOLL) {
      const divider2 = document.createElement("div");
      divider2.style.height = "6px";
      divider2.style.width = "100%";
      divider2.style.cursor = "ns-resize";
      divider2.style.background = "#2a2a3e";
      divider2.style.position = "relative";
      divider2.style.zIndex = "10";
      divider2.innerHTML = '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:40px;height:3px;background:#45B7D1;border-radius:2px;opacity:0.5"></div>';
      parent.appendChild(divider2);
      dividerRefs.current.boll = divider2;

      const bollH = subHeights.current.boll;
      const bollContainer = document.createElement("div");
      bollContainer.style.height = `${bollH}px`;
      bollContainer.style.width = "100%";
      parent.appendChild(bollContainer);
      bollContainerRef.current = bollContainer;

      const bollChart = createChart(bollContainer, {
        width: parent.clientWidth,
        height: bollH,
        layout: {
          background: { type: ColorType.Solid, color: "#1a1a2e" },
          textColor: "#d1d4dc",
        },
        grid: {
          vertLines: { color: "#2a2a3e" },
          horzLines: { color: "#2a2a3e" },
        },
        crosshair: {
          mode: 0,
          vertLine: { labelVisible: false },
          horzLine: { labelVisible: false },
        },
        rightPriceScale: { borderColor: "#2a2a3e" },
        timeScale: { borderColor: "#2a2a3e", timeVisible: true, visible: false },
      });
      bollChartRef.current = bollChart;

      const bollCandleSeries = bollChart.addCandlestickSeries({
        upColor: "#ef5350",
        downColor: "#26a69a",
        borderDownColor: "#26a69a",
        borderUpColor: "#ef5350",
        wickDownColor: "#26a69a",
        wickUpColor: "#ef5350",
      });
      bollCandleSeriesRef.current = bollCandleSeries;

      bollUpperRef.current = bollChart.addLineSeries({
        color: "#FF6B6B",
        lineWidth: indicatorLineWidth,
        lineType: smoothLineType,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      bollMidRef.current = bollChart.addLineSeries({
        color: "#4ECDC4",
        lineWidth: indicatorLineWidth,
        lineType: smoothLineType,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      bollLowerRef.current = bollChart.addLineSeries({
        color: "#45B7D1",
        lineWidth: indicatorLineWidth,
        lineType: smoothLineType,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });

      bollChart.subscribeCrosshairMove((param: MouseEventParams) => {
        if (syncingCrosshairRef.current) {
          return;
        }
        if (!param.time) {
          chartRef.current?.clearCrosshairPosition();
          macdChartRef.current?.clearCrosshairPosition();
          return;
        }
        const hoveredTs = toUnixTimestamp(param.time);
        const idx = hoveredTs == null ? -1 : latestDataRef.current.findIndex((d) => d.timestamp === hoveredTs);
        if (idx >= 0) {
          syncCrosshairAtIndex("boll", idx);
        }
      });
    }

    const mainTimeScale = chart.timeScale();
    const subCharts: IChartApi[] = [];
    if (showMACD && macdChartRef.current) subCharts.push(macdChartRef.current);
    if (showBOLL && bollChartRef.current) subCharts.push(bollChartRef.current);

    mainTimeScale.subscribeVisibleLogicalRangeChange((range) => {
      if (syncingRef.current || !range) return;
      if (!restoringRangeRef.current) {
        visibleLogicalRangeRef.current = range;
      }
      maybeRequestMoreHistory(range);
      refreshVisibleExtremaOverlays();
      syncingRef.current = true;
      subCharts.forEach((subChart) => {
        try {
          subChart.timeScale().setVisibleLogicalRange(range);
        } catch {}
      });
      syncingRef.current = false;
    });

    subCharts.forEach((subChart) => {
      subChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncingRef.current || !range) return;
        if (!restoringRangeRef.current) {
          visibleLogicalRangeRef.current = range;
        }
        maybeRequestMoreHistory(range);
        refreshVisibleExtremaOverlays();
        syncingRef.current = true;
        try {
          mainTimeScale.setVisibleLogicalRange(range);
        } catch {}
        subCharts.forEach((other) => {
          if (other !== subChart) {
            try {
              other.timeScale().setVisibleLogicalRange(range);
            } catch {}
          }
        });
        syncingRef.current = false;
      });
    });
    scheduleRightPriceScaleSync();
    requestAnimationFrame(() => {
      refreshVisibleExtremaOverlays();
    });
  }, [showMA, showMACD, showBOLL, showVolume, period, isIntraday, indicatorLineWidth, priceDigits, smoothLineType, scheduleRightPriceScaleSync, maybeRequestMoreHistory, refreshVisibleExtremaOverlays]);

  useEffect(() => {
    buildChart();
  }, [buildChart]);

  useEffect(() => {
    setHoverSignalDetails(null);
    setHoverCandleDetails(null);
    setTradeHighlightOverlay(null);
    setVisibleExtremaOverlays([]);
  }, [data, period]);

  useEffect(() => {
    refreshVisibleExtremaOverlays();
  }, [data, refreshVisibleExtremaOverlays]);

  useEffect(() => {
    historyRequestPendingRef.current = false;
    lastHistoryLoadRequestIdRef.current = null;
  }, [period]);

  useEffect(() => {
    if (!historyLoadInfo || lastHistoryLoadRequestIdRef.current === historyLoadInfo.requestId) {
      return;
    }

    lastHistoryLoadRequestIdRef.current = historyLoadInfo.requestId;
    historyRequestPendingRef.current = false;

    if (
      historyLoadInfo.prependedBars <= 0 ||
      !visibleLogicalRangeRef.current ||
      !chartRef.current
    ) {
      return;
    }

    const shiftedRange = {
      from: visibleLogicalRangeRef.current.from + historyLoadInfo.prependedBars,
      to: visibleLogicalRangeRef.current.to + historyLoadInfo.prependedBars,
    };

    visibleLogicalRangeRef.current = shiftedRange;
    restoringRangeRef.current = true;
    try {
      chartRef.current.timeScale().setVisibleLogicalRange(shiftedRange);
      macdChartRef.current?.timeScale().setVisibleLogicalRange(shiftedRange);
      bollChartRef.current?.timeScale().setVisibleLogicalRange(shiftedRange);
    } catch {}
    restoringRangeRef.current = false;
  }, [historyLoadInfo]);

  useEffect(() => {
    visibleLogicalRangeRef.current = null;
    hasAutoFittedRef.current = false;
  }, [period, resetKey]);

  useEffect(() => {
    if (!data || data.length === 0) return;

    if (isIntraday && intradaySeriesRef.current) {
      const intradayData: LineData[] = data.map((d) => ({
        time: d.timestamp as Time,
        value: benchMode && stockPctBase ? ((d.close / stockPctBase) - 1) * 100 : d.close,
      }));
      intradaySeriesRef.current.setData(intradayData);
      // 叠加模式: 主线切到 % 格式;退出时还原价格格式
      intradaySeriesRef.current.applyOptions(
        benchMode
          ? {
              priceFormat: {
                type: "custom",
                formatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`,
                minMove: 0.01,
              },
              lastValueVisible: true,
            }
          : {
              priceFormat: { type: "price", precision: priceDigits, minMove: Math.pow(10, -priceDigits) },
              lastValueVisible: false,
            }
      );
      chartRef.current?.applyOptions({
        localization: {
          priceFormatter: benchMode
            ? (p: number) => `${p > 0 ? "+" : ""}${p.toFixed(2)}%`
            : (p: number) => p.toFixed(priceDigits),
        },
      });
    } else if (candleSeriesRef.current) {
      const candleData: CandlestickData[] = data.map((d) => ({
        time: d.timestamp as Time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));
      candleSeriesRef.current.setData(candleData);
    }

    if (volumeSeriesRef.current && showVolume && !isIntraday) {
      const volData: HistogramData[] = data.map((d) => ({
        time: d.timestamp as Time,
        value: d.volume,
        color: d.close >= d.open ? "rgba(239,83,80,0.3)" : "rgba(38,166,154,0.3)",
      }));
      volumeSeriesRef.current.setData(volData);
    }

    if (showMA && maData && !isIntraday) {
      Object.keys(maData).forEach((key) => {
        const series = maSeriesRef.current[key];
        if (series && maData[key]) {
          const lineData: LineData[] = data
            .map((d, i) => {
              const v = maData[key][i];
              if (v === null || v === undefined || isNaN(v)) return null;
              return { time: d.timestamp as Time, value: v };
            })
            .filter(Boolean) as LineData[];
          series.setData(lineData);
        }
      });

      const lastValues: Record<string, string> = {};
      Object.keys(maData).forEach((key) => {
        const arr = maData[key];
        for (let i = arr.length - 1; i >= 0; i--) {
          if (arr[i] != null && !isNaN(arr[i])) {
            lastValues[key] = arr[i].toFixed(priceDigits);
            break;
          }
        }
      });
      setLegendValues(lastValues);
    }

    const markerSeries = isIntraday ? intradaySeriesRef.current : candleSeriesRef.current;

    if (signals && signals.length > 0 && markerSeries) {
      const markers = signals
        .map((s) => {
          const bestBarTs = resolveSignalBarTimestamp(s, data);
          if (bestBarTs === null) return null;
          const signalTs = getSignalTimestamp(s);
          const isHighlighted =
            !!highlightedSignal &&
            highlightedSignal.direction === s.direction &&
            highlightedSignal.timestamp === signalTs;

          return {
            time: bestBarTs as Time,
            position: (s.direction === "buy" ? "belowBar" : "aboveBar") as
              | "belowBar"
              | "aboveBar",
            color: isHighlighted ? "#f0b90b" : s.direction === "buy" ? "#f23645" : "#089981",
            shape: (s.direction === "buy" ? "arrowUp" : "arrowDown") as
              | "arrowUp"
              | "arrowDown",
            size: isHighlighted ? 2.8 : 2.2,
            text: isHighlighted ? (s.direction === "buy" ? "B*" : "S*") : s.direction === "buy" ? "B" : "S",
          };
        })
        .filter(Boolean) as any[];

      if (markers.length > 0) {
        const uniqueMarkers = markers
          .sort((a, b) => Number(a.time) - Number(b.time))
          .filter((m, i, self) => i === self.findIndex((t) => t.time === m.time && t.position === m.position));
        markerSeries.setMarkers(uniqueMarkers);
      } else {
        markerSeries.setMarkers([]);
      }
    } else if (markerSeries) {
      markerSeries.setMarkers([]);
    }

    const mainChart = chartRef.current;
    if (mainChart) {
      autoDrawSeriesRef.current.forEach((series) => {
        try {
          mainChart.removeSeries(series);
        } catch {}
      });
      autoDrawSeriesRef.current = [];

      // 基准叠加线(仿 autoDraw 生命周期: 每次数据更新先移除重建)
      if (benchSeriesRef.current) {
        try {
          mainChart.removeSeries(benchSeriesRef.current);
        } catch {}
        benchSeriesRef.current = null;
      }
      if (benchMode && benchmark) {
        const benchSeries = mainChart.addLineSeries({
          color: "#4f9dff",
          lineWidth: 1,
          lineType: smoothLineType,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: benchmark.label.slice(0, 8),
        });
        const benchEntries = Array.from(benchMap?.entries() ?? [])
          .filter(([ts, pct]) => Number.isFinite(ts) && Number.isFinite(pct))
          .sort((a, b) => a[0] - b[0])
          .map(([ts, pct]) => ({ time: ts as Time, value: pct }));
        benchSeries.applyOptions({
          priceFormat: {
            type: "custom",
            formatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`,
            minMove: 0.01,
          },
        });
        benchSeries.setData(benchEntries as LineData[]);
        benchSeriesRef.current = benchSeries;
      }

      if (showAutoDraw && autoDrawLines.length > 0) {
        autoDrawLines.forEach((line) => {
          if (line.startTimestamp === line.endTimestamp) {
            return;
          }

          const color = line.kind === "segment" ? autoDrawColor : `${autoDrawColor}aa`;
          const segmentWidth = autoDrawWidthLevel;
          const penWidth = Math.max(1, autoDrawWidthLevel - 1) as 1 | 2 | 3;

          const overlaySeries = mainChart.addLineSeries({
            color,
            lineWidth: line.kind === "segment" ? segmentWidth : penWidth,
            lineStyle: line.kind === "segment" ? LineStyle.Solid : LineStyle.Dotted,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });

          overlaySeries.setData([
            { time: line.startTimestamp as Time, value: line.startPrice },
            { time: line.endTimestamp as Time, value: line.endPrice },
          ]);
          autoDrawSeriesRef.current.push(overlaySeries);
        });
      }
    }

    if (showMACD && macdData) {
      if (macdDifRef.current) {
        const difData: LineData[] = data
          .map((d, i) => {
            const v = macdData.DIF[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return { time: d.timestamp as Time, value: v };
          })
          .filter(Boolean) as LineData[];
        macdDifRef.current.setData(difData);
      }
      if (macdDeaRef.current) {
        const deaData: LineData[] = data
          .map((d, i) => {
            const v = macdData.DEA[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return { time: d.timestamp as Time, value: v };
          })
          .filter(Boolean) as LineData[];
        macdDeaRef.current.setData(deaData);
      }
      if (macdHistRef.current) {
        const macdHistData: HistogramData[] = data
          .map((d, i) => {
            const v = macdData.MACD[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return {
              time: d.timestamp as Time,
              value: v,
              color: v >= 0 ? "rgba(239,83,80,0.6)" : "rgba(38,166,154,0.6)",
            };
          })
          .filter(Boolean) as HistogramData[];
        macdHistRef.current.setData(macdHistData);

        // 计算红绿柱子面积并标注
        const areaMarkers = calcMacdAreaMarkers(data, macdData.MACD);
        if (areaMarkers.length > 0) {
          macdHistRef.current.setMarkers(areaMarkers);
        } else {
          macdHistRef.current.setMarkers([]);
        }
      }
    }

    if (showBOLL && bollData) {
      if (bollCandleSeriesRef.current) {
        const bollCandleData: CandlestickData[] = data.map((d) => ({
          time: d.timestamp as Time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }));
        bollCandleSeriesRef.current.setData(bollCandleData);
      }
      if (bollUpperRef.current) {
        const upperData: LineData[] = data
          .map((d, i) => {
            const v = bollData.UPPER[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return { time: d.timestamp as Time, value: v };
          })
          .filter(Boolean) as LineData[];
        bollUpperRef.current.setData(upperData);
      }
      if (bollMidRef.current) {
        const midData: LineData[] = data
          .map((d, i) => {
            const v = bollData.MID[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return { time: d.timestamp as Time, value: v };
          })
          .filter(Boolean) as LineData[];
        bollMidRef.current.setData(midData);
      }
      if (bollLowerRef.current) {
        const lowerData: LineData[] = data
          .map((d, i) => {
            const v = bollData.LOWER[i];
            if (v === null || v === undefined || isNaN(v)) return null;
            return { time: d.timestamp as Time, value: v };
          })
          .filter(Boolean) as LineData[];
        bollLowerRef.current.setData(lowerData);
      }
    }

    const savedRange = visibleLogicalRangeRef.current;
    if (savedRange && chartRef.current) {
      restoringRangeRef.current = true;
      try {
        chartRef.current.timeScale().setVisibleLogicalRange(savedRange);
        macdChartRef.current?.timeScale().setVisibleLogicalRange(savedRange);
        bollChartRef.current?.timeScale().setVisibleLogicalRange(savedRange);
      } catch {}
      restoringRangeRef.current = false;
      return;
    }

    if (!hasAutoFittedRef.current) {
      restoringRangeRef.current = true;
      chartRef.current?.timeScale().fitContent();
      macdChartRef.current?.timeScale().fitContent();
      bollChartRef.current?.timeScale().fitContent();
      restoringRangeRef.current = false;
      hasAutoFittedRef.current = true;
    }
    scheduleRightPriceScaleSync();
  }, [data, maData, macdData, bollData, signals, showMA, showMACD, showBOLL, showVolume, isIntraday, priceDigits, highlightedSignal, scheduleRightPriceScaleSync, autoDrawLines, showAutoDraw, autoDrawColor, autoDrawWidthLevel, benchmark, stockPctBase]);

  useEffect(() => {
    if (!chartRef.current || data.length === 0) {
      setTradeHighlightOverlay(null);
      return;
    }

    if (!highlightedSignal) {
      setTradeHighlightOverlay(null);
      chartRef.current.clearCrosshairPosition();
      macdChartRef.current?.clearCrosshairPosition();
      bollChartRef.current?.clearCrosshairPosition();
      return;
    }

    const matchedSignal =
      signals.find((signal) => {
        const signalTs = getSignalTimestamp(signal);
        return signal.direction === highlightedSignal.direction && signalTs === highlightedSignal.timestamp;
      }) ||
      ({
        direction: highlightedSignal.direction,
        price: 0,
        time: String(highlightedSignal.timestamp),
        reason: "",
        timestamp: highlightedSignal.timestamp,
      } as SignalInfo);

    const highlightedBarTs = resolveSignalBarTimestamp(matchedSignal, data);
    if (highlightedBarTs == null) {
      setTradeHighlightOverlay(null);
      return;
    }

    const idx = data.findIndex((item) => item.timestamp === highlightedBarTs);
    if (idx < 0) {
      setTradeHighlightOverlay(null);
      return;
    }

    const prevClose = idx > 0 ? data[idx - 1].close : data[idx].open;
    const change = data[idx].close - prevClose;
    const changePct = prevClose ? (change / prevClose) * 100 : 0;
    const amplitudePct = prevClose ? ((data[idx].high - data[idx].low) / prevClose) * 100 : 0;
    setHoverCandleDetails({
      dateLabel: formatHoverDateLabel(data[idx].timestamp, period),
      prevClose,
      open: data[idx].open,
      high: data[idx].high,
      low: data[idx].low,
      close: data[idx].close,
      change,
      changePct,
      amplitudePct,
      volume: data[idx].volume,
      amount: data[idx].amount ?? 0,
    });

    const matchedSignalsAtBar = signals.filter(
      (signal) => resolveSignalBarTimestamp(signal, data) === data[idx].timestamp
    );

    const highlightPrice =
      typeof matchedSignal.price === "number" && Number.isFinite(matchedSignal.price)
        ? matchedSignal.price
        : data[idx].close;
    const markerSeries = isIntraday ? intradaySeriesRef.current : candleSeriesRef.current;
    const highlightWindow = getHighlightWindow(period);
    const from = data[Math.max(0, idx - highlightWindow.before)].timestamp as Time;
    const to = data[Math.min(data.length - 1, idx + highlightWindow.after)].timestamp as Time;

    restoringRangeRef.current = true;
    chartRef.current.timeScale().setVisibleRange({ from, to });
    macdChartRef.current?.timeScale().setVisibleRange({ from, to });
    bollChartRef.current?.timeScale().setVisibleRange({ from, to });
    visibleLogicalRangeRef.current = chartRef.current.timeScale().getVisibleLogicalRange();
    restoringRangeRef.current = false;

    const rafId = requestAnimationFrame(() => {
      if (!chartRef.current || !markerSeries) {
        setTradeHighlightOverlay(null);
        return;
      }

      syncCrosshairAtIndexRef.current?.("programmatic", idx);

      const x = chartRef.current.timeScale().timeToCoordinate(highlightedBarTs as Time);
      const y = markerSeries.priceToCoordinate(highlightPrice);

      if (x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) {
        setTradeHighlightOverlay(null);
        return;
      }

      if (matchedSignalsAtBar.length > 0) {
        setHoverSignalDetails({
          x,
          y,
          items: matchedSignalsAtBar,
        });
      } else {
        setHoverSignalDetails(null);
      }

      setTradeHighlightOverlay({
        x,
        y,
        direction: highlightedSignal.direction,
        label: highlightedSignal.direction === "buy" ? "买点" : "卖点",
      });
    });

    return () => {
      cancelAnimationFrame(rafId);
    };
  }, [highlightedSignal, data, signals, isIntraday, period]);

  useEffect(() => {
    const parent = containerRef.current;
    if (!parent) return;

    let dragging: "macd" | "boll" | null = null;
    let startY = 0;
    let startMainH = 0;
    let startSubH = 0;

    const onMouseDown = (e: MouseEvent, target: "macd" | "boll") => {
      dragging = target;
      startY = e.clientY;
      startMainH = mainContainerRef.current?.clientHeight || 0;
      startSubH = target === "macd"
        ? macdContainerRef.current?.clientHeight || 0
        : bollContainerRef.current?.clientHeight || 0;
      e.preventDefault();
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!dragging || !parent) return;
      const dy = e.clientY - startY;
      const newMainH = Math.max(200, startMainH + dy);
      const newSubH = Math.max(80, startSubH - dy);

      if (mainContainerRef.current) {
        mainContainerRef.current.style.height = `${newMainH}px`;
        chartRef.current?.applyOptions({ height: newMainH });
      }
      if (dragging === "macd" && macdContainerRef.current) {
        macdContainerRef.current.style.height = `${newSubH}px`;
        macdChartRef.current?.applyOptions({ height: newSubH });
        subHeights.current.macd = newSubH;
      }
      if (dragging === "boll" && bollContainerRef.current) {
        bollContainerRef.current.style.height = `${newSubH}px`;
        bollChartRef.current?.applyOptions({ height: newSubH });
        subHeights.current.boll = newSubH;
      }
    };

    const onMouseUp = () => {
      dragging = null;
    };

    const macdDivider = dividerRefs.current.macd;
    const bollDivider = dividerRefs.current.boll;

    if (macdDivider) {
      macdDivider.addEventListener("mousedown", (e: any) => onMouseDown(e as MouseEvent, "macd"));
    }
    if (bollDivider) {
      bollDivider.addEventListener("mousedown", (e: any) => onMouseDown(e as MouseEvent, "boll"));
    }
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);

    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, [showMACD, showBOLL]);

  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
      if (macdChartRef.current && macdContainerRef.current) {
        macdChartRef.current.applyOptions({
          width: macdContainerRef.current.clientWidth,
        });
      }
      if (bollChartRef.current && bollContainerRef.current) {
        bollChartRef.current.applyOptions({
          width: bollContainerRef.current.clientWidth,
        });
      }
      scheduleRightPriceScaleSync();
      refreshVisibleExtremaOverlays();
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [scheduleRightPriceScaleSync]);

  useEffect(() => {
    const target = containerRef.current;
    if (!target) return;

    let startX = 0;
    let startY = 0;
    let lastY = 0;
    let verticalScrolling = false;

    const isMobileLayout = () => window.matchMedia("(max-width: 900px)").matches;

    const handleTouchStart = (event: TouchEvent) => {
      if (!isMobileLayout() || event.touches.length !== 1) return;
      const touch = event.touches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      lastY = touch.clientY;
      verticalScrolling = false;
    };

    const handleTouchMove = (event: TouchEvent) => {
      if (!isMobileLayout() || event.touches.length !== 1) return;

      const touch = event.touches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;

      if (!verticalScrolling && Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx) * 1.15) {
        verticalScrolling = true;
      }

      if (!verticalScrolling) return;

      window.scrollBy({ top: lastY - touch.clientY, behavior: "auto" });
      lastY = touch.clientY;
      event.preventDefault();
      event.stopPropagation();
    };

    const handleTouchEnd = () => {
      verticalScrolling = false;
    };

    target.addEventListener("touchstart", handleTouchStart, { capture: true, passive: true });
    target.addEventListener("touchmove", handleTouchMove, { capture: true, passive: false });
    target.addEventListener("touchend", handleTouchEnd, { capture: true });
    target.addEventListener("touchcancel", handleTouchEnd, { capture: true });

    return () => {
      target.removeEventListener("touchstart", handleTouchStart, { capture: true });
      target.removeEventListener("touchmove", handleTouchMove, { capture: true });
      target.removeEventListener("touchend", handleTouchEnd, { capture: true });
      target.removeEventListener("touchcancel", handleTouchEnd, { capture: true });
    };
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div
        ref={containerRef}
        style={{ width: "100%", height: "100%", position: "relative" }}
      />

      {hoverCandleDetails && (
        <div style={{
          position: "absolute",
          top: 8,
          left: 12,
          right: 12,
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
          zIndex: 5,
          pointerEvents: "none",
          padding: "6px 10px",
          background: "rgba(10, 14, 20, 0.88)",
          border: "1px solid rgba(230,237,243,0.12)",
          borderRadius: 6,
          color: "#e6edf3",
          fontSize: 11,
          lineHeight: 1.5,
          boxShadow: "0 4px 14px rgba(0,0,0,0.28)",
        }}>
          <span style={{ color: "#9fb3c8", fontWeight: 600 }}>{hoverCandleDetails.dateLabel}</span>
          <span>昨收: {formatPrice(hoverCandleDetails.prevClose, priceDigits)}</span>
          <span>开: {formatPrice(hoverCandleDetails.open, priceDigits)}</span>
          <span style={{ color: "#f59e0b" }}>高: {formatPrice(hoverCandleDetails.high, priceDigits)}</span>
          <span style={{ color: "#22c55e" }}>低: {formatPrice(hoverCandleDetails.low, priceDigits)}</span>
          <span style={{ color: hoverCandleDetails.change >= 0 ? "#f23645" : "#089981" }}>
            收: {formatPrice(hoverCandleDetails.close, priceDigits)}
          </span>
          <span style={{ color: hoverCandleDetails.change >= 0 ? "#f23645" : "#089981" }}>
            涨跌: {formatSignedPrice(hoverCandleDetails.change, priceDigits)}
          </span>
          <span style={{ color: hoverCandleDetails.change >= 0 ? "#f23645" : "#089981" }}>
            涨幅: {formatSignedPercent(hoverCandleDetails.changePct)}
          </span>
          <span>振幅: {hoverCandleDetails.amplitudePct.toFixed(2)}%</span>
          <span>成交量: {formatVolume(hoverCandleDetails.volume)}</span>
          <span>成交额: {formatAmount(hoverCandleDetails.amount)}</span>
          {hoverBenchPct != null && benchmark && (
            <span style={{ color: "#4f9dff" }}>
              基准 {benchmark.label}: {formatSignedPercent(hoverBenchPct)}
            </span>
          )}
        </div>
      )}

      {hoverSignalDetails && (
        <div style={{
          position: "absolute",
          left: Math.max(8, Math.min(hoverSignalDetails.x + 14, (containerRef.current?.clientWidth || 0) - 180)),
          top: Math.max(8, hoverSignalDetails.y - 10),
          zIndex: 7,
          pointerEvents: "none",
          minWidth: 160,
          padding: "6px 10px",
          background: "rgba(10, 14, 20, 0.96)",
          border: "1px solid rgba(230,237,243,0.14)",
          borderRadius: 6,
          color: "#e6edf3",
          fontSize: 11,
          lineHeight: 1.5,
          boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
          whiteSpace: "nowrap",
        }}>
          {hoverSignalDetails.items.map((item, index) => {
            const isBuy = item.direction === "buy";
            const dealAmount = item.amount ?? 0;
            const commission = item.commission ?? 0;
            const totalAmount = isBuy ? dealAmount + commission : dealAmount - commission;
            const signalTs = getSignalTimestamp(item);
            const signalTimeLabel =
              signalTs != null ? formatHoverDateLabel(signalTs, period) : item.time || "--";
            return (
              <div key={`${item.time}-${item.direction}-${index}`} style={{ marginBottom: index === hoverSignalDetails.items.length - 1 ? 0 : 6 }}>
                <div style={{ color: isBuy ? "#f23645" : "#089981", fontWeight: 700 }}>
                  {isBuy ? "B 买入" : "S 卖出"}
                </div>
                <div>{isBuy ? "买入时间" : "卖出时间"}: {signalTimeLabel}</div>
                <div>成交价: {formatPrice(item.price, priceDigits)}</div>
                <div>数量: {item.size ?? "--"}</div>
                <div>{isBuy ? "买入成本" : "卖出到账"}: {totalAmount.toFixed(2)}</div>
                <div>手续费: {commission.toFixed(2)}</div>
                <div
                  style={{
                    maxWidth: 260,
                    whiteSpace: "normal",
                    wordBreak: "break-word",
                    color: "#9fb3c8",
                    marginTop: 2,
                  }}
                >
                  原因: {item.reason || "--"}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showMA && maData && !isIntraday && Object.keys(legendValues).length > 0 && (
        <div style={{
          position: "absolute",
          top: hoverCandleDetails ? 52 : 8,
          left: 12,
          display: "flex",
          gap: 10,
          zIndex: 5,
          pointerEvents: "none",
        }}>
          {Object.keys(maData).map((key) => (
            <span key={key} style={{
              color: MA_COLORS[key] || "#ffffff",
              fontSize: 11,
              fontWeight: 500,
              textShadow: "0 0 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.5)",
              whiteSpace: "nowrap",
            }}>
              均线 {key}：{legendValues[key] || "--"}
            </span>
          ))}
        </div>
      )}

      {tradeHighlightOverlay && (
        <>
          <div
            style={{
              position: "absolute",
              left: tradeHighlightOverlay.x - 1,
              top: 0,
              width: 2,
              height: "100%",
              background: "linear-gradient(180deg, rgba(240,185,11,0.95), rgba(240,185,11,0.2))",
              boxShadow: "0 0 10px rgba(240,185,11,0.65)",
              pointerEvents: "none",
              zIndex: 6,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: tradeHighlightOverlay.x - 11,
              top: tradeHighlightOverlay.y - 11,
              width: 22,
              height: 22,
              borderRadius: "50%",
              border: `2px solid ${tradeHighlightOverlay.direction === "buy" ? "#f23645" : "#089981"}`,
              background: "rgba(240,185,11,0.18)",
              boxShadow: "0 0 0 6px rgba(240,185,11,0.12), 0 0 16px rgba(240,185,11,0.45)",
              pointerEvents: "none",
              zIndex: 7,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: Math.max(8, tradeHighlightOverlay.x + 14),
              top: Math.max(8, tradeHighlightOverlay.y - 34),
              padding: "4px 8px",
              borderRadius: 6,
              background: "rgba(10,14,20,0.96)",
              border: "1px solid rgba(240,185,11,0.55)",
              color: "#f0b90b",
              fontSize: 11,
              fontWeight: 700,
              lineHeight: 1.2,
              boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
              pointerEvents: "none",
              zIndex: 7,
              whiteSpace: "nowrap",
            }}
          >
            {tradeHighlightOverlay.label}
          </div>
        </>
      )}

      {visibleExtremaOverlays.length > 0 && (
        <svg
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
            zIndex: 6,
            overflow: "visible",
          }}
        >
          <defs>
            <marker
              id="visible-extrema-arrow"
              markerWidth="6"
              markerHeight="6"
              refX="3"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L6,3 L0,6 Z" fill="#ffffff" />
            </marker>
          </defs>
          {visibleExtremaOverlays.map((item) => {
            const containerWidth = containerRef.current?.clientWidth || 0;
            const preferRight = item.x <= containerWidth - 72;
            const direction = preferRight ? 1 : -1;
            const textX = item.x + 21 * direction;
            const textY = item.kind === "high" ? item.y - 2 : item.y + 4;
            const labelAnchor = preferRight ? "start" : "end";
            const lineStartX = item.x + 18 * direction;
            const lineStartY = item.y;

            return (
              <g key={`${item.kind}-${item.timestamp}-${item.price}`}>
                <line
                  x1={lineStartX}
                  y1={lineStartY}
                  x2={item.x}
                  y2={item.y}
                  fill="none"
                  stroke="#ffffff"
                  strokeWidth="0.8"
                  markerEnd="url(#visible-extrema-arrow)"
                />
                <text
                  x={textX}
                  y={textY}
                  fill="#d8d8d8"
                  fontSize="10"
                  fontWeight="600"
                  textAnchor={labelAnchor}
                  style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,0.85)", strokeWidth: 2 }}
                >
                  {formatPrice(item.price, priceDigits)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
