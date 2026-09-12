import { useEffect, useRef } from "react";
import { createChart, IChartApi, LineStyle, Time, ColorType } from "lightweight-charts";

interface CurvePoint {
  timestamp: number;
  value: number;
}

interface Props {
  equity?: CurvePoint[] | null;
  benchmark?: CurvePoint[] | null;
  benchmarkLabel?: string;
}

/** 资金曲线 + 基准对比(策略 vs 沪深300 ETF 等),用 lightweight-charts 双线叠加。 */
export default function EquityCurveChart({
  equity,
  benchmark,
  benchmarkLabel = "沪深300 ETF",
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 260,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9aa3b2",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: { borderColor: "rgba(255,255,255,0.1)" },
    });
    chartRef.current = chart;

    const hasEquity = !!equity && equity.length > 0;
    const hasBench = !!benchmark && benchmark.length > 0;

    if (hasEquity) {
      const s = chart.addLineSeries({
        color: "#4f9dff",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      s.setData(equity!.map((p) => ({ time: p.timestamp as unknown as Time, value: p.value })));
    }
    if (hasBench) {
      const s = chart.addLineSeries({
        color: "#8a8f9c",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      s.setData(benchmark!.map((p) => ({ time: p.timestamp as unknown as Time, value: p.value })));
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [equity, benchmark]);

  return (
    <div className="equity-curve-block" style={{ marginTop: 12 }}>
      <div className="equity-curve-title" style={{ fontSize: 13, marginBottom: 6, color: "var(--text-secondary, #9aa3b2)" }}>
        资金曲线 <span style={{ color: "#4f9dff" }}>●</span> 策略
        {benchmark && benchmark.length > 0 ? (
          <>
            {" "}
            <span style={{ color: "#8a8f9c" }}>●</span> {benchmarkLabel}
          </>
        ) : null}
      </div>
      <div ref={containerRef} style={{ width: "100%", height: 260 }} />
    </div>
  );
}
