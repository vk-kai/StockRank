export function parseChartTimestampText(value: string) {
  const numeric = Number(value);
  if (!Number.isNaN(numeric) && numeric > 100000) {
    return Math.floor(numeric);
  }

  const normalized = value.replace("T", " ").trim();
  const match = normalized.match(
    /^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$/
  );
  if (!match) {
    return null;
  }

  const [, year, month, day, hour = "0", minute = "0", second = "0"] = match;
  return Math.floor(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second)
    ) / 1000
  );
}

export function normalizeSignalChartPeriod(periodValue?: string) {
  return ({
    "1min": "1",
    "5min": "5",
    "15min": "15",
    "30min": "30",
    "60min": "60",
  } as Record<string, string>)[periodValue || ""] || periodValue || "30";
}

export function formatSignalPeriodLabel(periodValue?: string) {
  const chartPeriod = normalizeSignalChartPeriod(periodValue);
  if (chartPeriod === "daily") return "日K";
  if (chartPeriod === "weekly") return "周K";
  if (chartPeriod === "monthly") return "月K";
  return `${chartPeriod}分钟`;
}
